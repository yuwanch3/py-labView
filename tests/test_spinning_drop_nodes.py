from __future__ import annotations

from types import SimpleNamespace
from pathlib import Path
from tempfile import TemporaryDirectory
import math
import unittest

from pylabview.execution import RunSession
from pylabview.panel_widgets import gauge_fraction, image_to_ppm, next_dropdown_value, table_rows
from pylabview.integrations.serial_adapter import SerialAdapter
from pylabview.integrations.vision_adapter import ImageFrame, VisionAdapter
from pylabview.model import NODE_DEFINITIONS, Node
from pylabview.persistence import load_project
from pylabview.resources import ResourceManager
from pylabview.runtime import DataflowRuntime
from pylabview.typesystem import ErrorCluster


class ArduinoStream:
    def __init__(self, replies):
        self.replies = list(replies)
        self.writes = []
        self.closed = False

    def write(self, data):
        self.writes.append(data)
        return len(data)

    def readline(self, size):
        return self.replies.pop(0)[:size]

    def close(self):
        self.closed = True


class ArduinoBackend:
    def __init__(self, stream):
        self.stream = stream

    def serial_for_url(self, port, **kwargs):
        self.port, self.kwargs = port, kwargs
        return self.stream


class FailedStopStream(ArduinoStream):
    def write(self, data):
        self.writes.append(data)
        return 0 if data == b"SET_PWM:0\n" else len(data)


class Matrix:
    def __init__(self, rows):
        self.rows = rows
        self.shape = (len(rows), len(rows[0]))
        self.dtype = SimpleNamespace(name="uint8", itemsize=1)
        self.nbytes = self.shape[0] * self.shape[1]

    def tolist(self):
        return [list(row) for row in self.rows]


class EdgeCv2:
    THRESH_BINARY = 1

    @staticmethod
    def threshold(payload, threshold, maximum, mode):
        return threshold, Matrix([[maximum if value > threshold else 0 for value in row]
                                  for row in payload.tolist()])


class Capture:
    def __init__(self):
        self.released = False

    def isOpened(self):
        return True

    def read(self):
        return True, Matrix([[255, 10, 10, 255], [255, 10, 10, 255]])

    def release(self):
        self.released = True


class CaptureCv2(EdgeCv2):
    def __init__(self):
        self.sources = []
        self.captures = []

    def VideoCapture(self, source):
        self.sources.append(source)
        capture = Capture()
        self.captures.append(capture)
        return capture


class SpinningDropNodeTests(unittest.TestCase):
    def evaluate(self, node_type, inputs, properties=None, runtime=None, session=None):
        node = Node("node", node_type, 0, 0, node_type, properties or {})
        return (runtime or DataflowRuntime())._evaluate(node, inputs, {}, [], session=session)

    def test_node_port_contracts(self):
        expected = {"arduino_motor_rpm", "camera_capture_dual_mode", "edge_intensity_profile",
                    "wire_calibration", "pixel_to_mm", "vonnegut_ift", "pycnometer_density",
                    "delta_density", "spinning_drop_log_row"}
        self.assertTrue(expected <= NODE_DEFINITIONS.keys())
        for node_type in expected:
            definition = NODE_DEFINITIONS[node_type]
            self.assertEqual(len(definition.inputs), len(definition.input_types), node_type)
            self.assertEqual(len(definition.outputs), len(definition.output_types), node_type)
        self.assertEqual(NODE_DEFINITIONS["wire_calibration"].defaults, {})

    def test_pycnometer_reference_measurements(self):
        rows = ((11.2, 14.55, 25.23, 953), (11.4, 14.42, 25.55, 976),
                (11.8, 14.91, 26.58, 988), (11.7, 14.78, 25.8, 941),
                (12.2, 14.97, 27.30, 1010))
        for volume, empty, gross, handwritten_integer in rows:
            result = self.evaluate("pycnometer_density", {
                "bottle_weight_empty_g": empty, "bottle_weight_gross_g": gross, "volume_ml": volume})
            expected = (gross - empty) / volume * 1000.0
            self.assertAlmostEqual(result["density_kg_m3"], expected, places=12)
            # The source notebook records whole kg/m3 by truncation, not nearest-integer rounding.
            self.assertEqual(int(result["density_kg_m3"]), handwritten_integer)
            self.assertAlmostEqual(result["density_g_ml"] * 1000.0, result["density_kg_m3"])

    def test_delta_density_is_absolute(self):
        self.assertEqual(self.evaluate("delta_density", {"density_1": 1010, "density_2": 953}), 57)

    def test_vonnegut_radius_path_matches_diameter_over_32(self):
        rpm, diameter_mm, delta_rho = 3000.0, 2.4, 57.0
        result = self.evaluate("vonnegut_ift", {
            "rpm": rpm, "diameter_mm": diameter_mm, "delta_rho": delta_rho, "sensor_status": "OK"})
        omega_squared = (2 * math.pi * rpm / 60) ** 2
        diameter_m = diameter_mm / 1000
        diameter_formula = delta_rho * omega_squared * diameter_m ** 3 / 32
        self.assertFalse(result["error"].status)
        self.assertAlmostEqual(result["ift_N_m"], diameter_formula, places=15)
        self.assertAlmostEqual(result["radius_cubed"], (diameter_m / 2) ** 3, places=20)
        self.assertAlmostEqual(result["ift_mN_m"], result["ift_N_m"] * 1000)

    def test_no_sensor_interlock_rejects_vonnegut(self):
        result = self.evaluate("vonnegut_ift", {
            "rpm": 3000, "diameter_mm": 2, "delta_rho": 50, "sensor_status": "NO_SENSOR"})
        self.assertTrue(result["error"].status)
        self.assertEqual(result["ift_N_m"], 0)
        self.assertIn("verified RPM sensor", result["error"].source)

    def test_arduino_verified_rpm_protocol(self):
        stream = ArduinoStream([b"ACK_PWM:128\n", b"RPM:3000.5:SENSOR_OK\n"])
        backend = ArduinoBackend(stream)
        session = RunSession(resources=ResourceManager())
        runtime = DataflowRuntime(serial=SerialAdapter(backend))
        result = self.evaluate("arduino_motor_rpm", {"port": "COM7", "pwm": 128},
                               runtime=runtime, session=session)
        self.assertEqual(stream.writes, [b"SET_PWM:128\n"])
        self.assertEqual((backend.port, backend.kwargs["baudrate"]), ("COM7", 115200))
        self.assertEqual((result["rpm"], result["pwm_actual"], result["sensor_status"]),
                         (3000.5, 128, "OK"))
        self.assertFalse(result["error"].status)

    def test_arduino_no_sensor_blocks_hilir_calculation(self):
        stream = ArduinoStream([b"ACK_PWM:90\n", b"RPM:0:NO_SENSOR:PWM=90\n"])
        backend = ArduinoBackend(stream)
        session = RunSession(resources=ResourceManager())
        runtime = DataflowRuntime(serial=SerialAdapter(backend))
        motor = self.evaluate("arduino_motor_rpm", {"port": "COM7", "pwm": 90},
                              runtime=runtime, session=session)
        self.assertEqual(motor["sensor_status"], "NO_SENSOR")
        ift = self.evaluate("vonnegut_ift", {"rpm": motor["rpm"], "diameter_mm": 2,
                                             "delta_rho": 50, "sensor_status": motor["sensor_status"]})
        self.assertTrue(ift["error"].status)
        self.assertEqual(ift["ift_mN_m"], 0)
        self.assertEqual(stream.writes[-1], b"SET_PWM:0\n")

    def test_arduino_rejects_mismatched_pwm_ack_and_safe_stops_on_close(self):
        mismatch = ArduinoStream([b"ACK_PWM:0\n", b"RPM:3000:SENSOR_OK\n"])
        session = RunSession(resources=ResourceManager())
        result = self.evaluate("arduino_motor_rpm", {"port": "COM7", "pwm": 120},
                               runtime=DataflowRuntime(serial=SerialAdapter(ArduinoBackend(mismatch))), session=session)
        self.assertTrue(result["error"].status)
        self.assertEqual(mismatch.writes[-1], b"SET_PWM:0\n")
        session.close()
        self.assertTrue(mismatch.closed)
        self.assertEqual(mismatch.writes[-1], b"SET_PWM:0\n")

    def test_cancellation_callback_commands_motor_safe_stop_immediately(self):
        stream = ArduinoStream([b"ACK_PWM:120\n", b"RPM:3000:SENSOR_OK\n"])
        session = RunSession(resources=ResourceManager())
        self.evaluate("arduino_motor_rpm", {"port": "COM7", "pwm": 120},
                      runtime=DataflowRuntime(serial=SerialAdapter(ArduinoBackend(stream))), session=session)
        session.token.cancel()
        self.assertEqual(stream.writes[-1], b"SET_PWM:0\n")
        self.assertEqual(session.token.callback_errors, ())
        session.close()
        self.assertTrue(stream.closed)

    def test_cancellation_exposes_failed_motor_safe_stop(self):
        stream = FailedStopStream([b"ACK_PWM:120\n", b"RPM:3000:SENSOR_OK\n"])
        session = RunSession(resources=ResourceManager())
        self.evaluate("arduino_motor_rpm", {"port": "COM7", "pwm": 120},
                      runtime=DataflowRuntime(serial=SerialAdapter(ArduinoBackend(stream))), session=session)
        session.token.cancel()
        self.assertTrue(any("safe-stop" in error for error in session.token.callback_errors))

    def test_wire_calibration_and_pixel_conversion(self):
        scale = self.evaluate("wire_calibration", {"diameter_px": 40, "known_wire_diameter_mm": 0.8})
        self.assertAlmostEqual(scale, 0.02)
        self.assertAlmostEqual(self.evaluate("pixel_to_mm", {
            "diameter_px": 75, "scale_factor_mm_per_px": scale}), 1.5)
        with self.assertRaisesRegex(Exception, "known wire diameter"):
            self.evaluate("wire_calibration", {"diameter_px": 40, "known_wire_diameter_mm": 0})

    def test_edge_profile_detects_dark_region_in_both_orientations(self):
        matrix = Matrix([[255, 10, 10, 255], [255, 10, 10, 255]])
        frame = ImageFrame(matrix, 4, 2, 1)
        vision = VisionAdapter(EdgeCv2(), object())
        horizontal = vision.edge_intensity_profile(frame, "horizontal", 127, "dark")
        self.assertEqual(horizontal["intensity_profile"], [255.0, 10.0, 10.0, 255.0])
        self.assertEqual(horizontal["diameter_px"], 2.0)
        vertical = vision.edge_intensity_profile(frame, "vertical", 200, "dark")
        self.assertEqual(vertical["diameter_px"], 2.0)

    def test_camera_dual_mode_passes_index_or_url_to_opencv(self):
        cv2 = CaptureCv2()
        vision = VisionAdapter(cv2, object())
        vision.capture_source("usb", 2, "http://unused.invalid/video", 1)
        vision.capture_source("network", 0, "http://192.168.1.5:4747/video", 1)
        self.assertEqual(cv2.sources, [2, "http://192.168.1.5:4747/video"])
        self.assertTrue(all(capture.released for capture in cv2.captures))

    def test_log_rejects_error_clusters_and_accumulates_valid_rows(self):
        ports = {"rpm": 3000, "diameter_px": 40, "diameter_mm": 2,
                 "delta_rho": 57, "omega_squared": 10, "radius_cubed": 1e-9,
                 "ift_N_m": 1e-4, "ift_mN_m": .1,
                 "motor_error": ErrorCluster(), "ift_error": ErrorCluster()}
        session = RunSession(resources=ResourceManager())
        first = self.evaluate("spinning_drop_log_row", ports, session=session)
        second = self.evaluate("spinning_drop_log_row", ports, session=session)
        self.assertEqual(len(first), 2)
        self.assertEqual(len(second), 3)
        ports["motor_error"] = ErrorCluster(True, 60, "no sensor")
        with self.assertRaisesRegex(Exception, "measurement rejected"):
            self.evaluate("spinning_drop_log_row", ports, session=session)

    def test_spinning_drop_panel_gauge_and_table_helpers(self):
        self.assertEqual(gauge_fraction(3000, 0, 6000), 0.5)
        self.assertEqual(gauge_fraction(300, 0, 255), 1.0)
        self.assertEqual(table_rows([["RPM", "IFT"], [3000, 0.01]]),
                         [["RPM", "IFT"], [3000, 0.01]])
        self.assertEqual(next_dropdown_value("COM1", ["COM1", "COM2"]), "COM2")
        ppm = image_to_ppm(ImageFrame(Matrix([[0, 255]]), 2, 1, 1))
        self.assertTrue(ppm.startswith(b"P5\n2 1\n255\n"))

    def test_spinning_drop_example_loads_and_wires_full_use_case(self):
        path = Path(__file__).parents[1] / "examples" / "spinning_drop_ift.json"
        project = load_project(path)
        graph = project.main.graph
        required = {"arduino_motor_rpm", "camera_capture_dual_mode", "edge_intensity_profile",
                    "wire_calibration", "pixel_to_mm", "vonnegut_ift", "pycnometer_density",
                    "delta_density", "spinning_drop_log_row", "report_generate"}
        self.assertTrue(required <= {node.type for node in graph.nodes.values()})
        self.assertEqual(DataflowRuntime().validate(graph, project, project.main_vi), [])
        labels = {item["properties"].get("label", "") for item in project.main.front_panel["items"]}
        for label in ("Motor", "RPM ACT", "PWM ACT", "COM Arduino", "WIFI IP / Camera URL",
                      "Picture Oil", "Picture Comparison — Known Wire", "Grafik Oil", "Grafik Kawat",
                      "Selisih Densitas (kg/m3)", "w²", "r³", "IFT N/m", "IFT mN/m"):
            self.assertIn(label, labels)
        table = next(item for item in project.main.front_panel["items"]
                     if item["properties"].get("display_type") == "table")
        self.assertIn("Dia(px)", table["properties"]["label"])
        self.assertEqual(project.main.front_panel["extensions"]["physical_validation"], "not performed")
        self.assertEqual(graph.nodes["wire_known"].properties["value"], 0.0)

    def test_failed_sensor_cannot_write_example_report(self):
        path = Path(__file__).parents[1] / "examples" / "spinning_drop_ift.json"
        project = load_project(path)
        serial = ArduinoStream([b"ACK_PWM:0\n", b"RPM:0:NO_SENSOR:PWM=0\n"])
        cv2 = CaptureCv2()
        with TemporaryDirectory() as directory:
            runtime = DataflowRuntime(serial=SerialAdapter(ArduinoBackend(serial)),
                                      vision=VisionAdapter(cv2, object()), data_root=directory)
            result = runtime.run(project.main.graph, {"wire_known": 0.5}, project, project.main_vi)
            self.assertTrue(any("measurement rejected" in error for error in result.errors))
            self.assertFalse(Path(directory, "spinning-drop-ift.csv").exists())


if __name__ == "__main__":
    unittest.main()
