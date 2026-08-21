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


class TelemetryStream:
    """Scripted serial stream for the real firmware protocol.

    readline() pops queued chunks; once the queue is empty it returns b""
    (the read timeout expired with no data), exactly like a pyserial port
    idling between 100ms telemetry frames.
    """

    def __init__(self, chunks=()):
        self.chunks = list(chunks)
        self.writes = []
        self.closed = False

    def write(self, data):
        self.writes.append(bytes(data))
        return len(data)

    def readline(self, size):
        return self.chunks.pop(0)[:size] if self.chunks else b""

    def close(self):
        self.closed = True


class SilentStopStream(TelemetryStream):
    def write(self, data):
        self.writes.append(bytes(data))
        return 0 if bytes(data) == b"STOP\n" else len(data)


class ArduinoBackend:
    def __init__(self, stream):
        self.stream = stream

    def serial_for_url(self, port, **kwargs):
        self.port, self.kwargs = port, kwargs
        return self.stream


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


def watcher_inputs(**overrides):
    inputs = {"run": True, "rpm": 987.0, "pwm": 142.0, "elapsed_time_s": 45.231,
              "current_target_rpm": 1000.0, "stage_changed": False, "autostop": False,
              "error": ErrorCluster(), "stalled": False, "diameter_px": 40.0,
              "diameter_mm": 1.5, "delta_rho": 57.0, "omega_squared": 98.7,
              "radius_cubed": 1.7e-9, "ift_N_m": 0.0042, "ift_mN_m": 4.2}
    inputs.update(overrides)
    return inputs


class SpinningDropNodeTests(unittest.TestCase):
    def evaluate(self, node_type, inputs, properties=None, runtime=None, session=None):
        node = Node("node", node_type, 0, 0, node_type, properties or {})
        return (runtime or DataflowRuntime())._evaluate(node, inputs, {}, [], session=session)

    # ------------------------------------------------------------------
    # protocol ground truth: lab Arduino firmware source (2026-08-21)
    # ------------------------------------------------------------------

    def reader_pass(self, runtime, session, run=True, node_id="node"):
        node = Node(node_id, "arduino_telemetry_reader", 0, 0, "reader", {})
        return runtime._evaluate(node, {"port": "COM7", "run": run}, {}, [], session=session)

    def test_node_port_contracts(self):
        expected = {"arduino_telemetry_reader", "rpm_stall_watchdog", "spinning_drop_stage_watcher",
                    "camera_capture_dual_mode", "edge_intensity_profile", "wire_calibration",
                    "pixel_to_mm", "vonnegut_ift", "pycnometer_density", "delta_density"}
        self.assertTrue(expected <= NODE_DEFINITIONS.keys())
        for node_type in expected:
            definition = NODE_DEFINITIONS[node_type]
            self.assertEqual(len(definition.inputs), len(definition.input_types), node_type)
            self.assertEqual(len(definition.outputs), len(definition.output_types), node_type)
        self.assertNotIn("arduino_motor_rpm", NODE_DEFINITIONS)
        self.assertNotIn("spinning_drop_sequencer", NODE_DEFINITIONS)
        self.assertNotIn("spinning_drop_log_row", NODE_DEFINITIONS)

    def test_telemetry_line_parsed(self):
        stream = TelemetryStream([b"RPM:987;PWM:142;TIME:45.231;TARGET:1000\n"])
        session = RunSession(resources=ResourceManager())
        runtime = DataflowRuntime(serial=SerialAdapter(ArduinoBackend(stream)))
        result = self.reader_pass(runtime, session)
        self.assertEqual(stream.writes[0], b"START\n")
        self.assertEqual((result["rpm"], result["pwm"], result["elapsed_time_s"],
                          result["current_target_rpm"]), (987.0, 142.0, 45.231, 1000.0))
        self.assertFalse(result["stage_changed"])
        self.assertFalse(result["autostop"])
        self.assertFalse(result["error"].status)

    def test_ack_and_stage_events(self):
        # TARGET_RPM:2000: the first stage event a real firmware ever sends
        # (the initial 1000 target is implicit at START, never announced).
        stream = TelemetryStream([b"ACK:START\n", b"TARGET_RPM:2000\n"])
        session = RunSession(resources=ResourceManager())
        runtime = DataflowRuntime(serial=SerialAdapter(ArduinoBackend(stream)))
        first = self.reader_pass(runtime, session)
        self.assertTrue(first["stage_changed"])
        self.assertEqual(first["current_target_rpm"], 2000.0)
        second = self.reader_pass(runtime, session, run=True)  # no new lines
        self.assertFalse(second["stage_changed"], "stage_changed must be true for exactly one tick")
        third = self.reader_pass(runtime, session)
        stream.chunks.append(b"ACK:AUTOSTOP_6000\n")
        fourth = self.reader_pass(runtime, session)
        self.assertTrue(fourth["autostop"])
        fifth = self.reader_pass(runtime, session)
        self.assertFalse(fifth["autostop"], "autostop must be true for exactly one tick")
        # falling edge sends STOP exactly once and tolerates the ACK
        sixth = self.reader_pass(runtime, session, run=False)
        self.assertEqual(stream.writes.count(b"START\n"), 1)
        self.assertIn(b"STOP\n", stream.writes)
        self.assertFalse(sixth["error"].status)

    def test_garbage_and_partial_lines_are_tolerated(self):
        stream = TelemetryStream([b"junk noise\n", b"\n", b"RPM:10;PW"])
        session = RunSession(resources=ResourceManager())
        runtime = DataflowRuntime(serial=SerialAdapter(ArduinoBackend(stream)))
        first = self.reader_pass(runtime, session)
        self.assertEqual(first["rpm"], 0.0, "partial line must not be parsed as data")
        self.assertFalse(first["error"].status)
        stream.chunks.append(b"M:5;TIME:1.000;TARGET:1000\n")
        second = self.reader_pass(runtime, session)
        self.assertEqual((second["rpm"], second["pwm"], second["elapsed_time_s"],
                          second["current_target_rpm"]), (10.0, 5.0, 1.0, 1000.0),
                         "partial chunk must be reassembled across passes")

    def test_pc_never_sends_pwm_commands(self):
        stream = TelemetryStream([])
        session = RunSession(resources=ResourceManager())
        runtime = DataflowRuntime(serial=SerialAdapter(ArduinoBackend(stream)))
        self.reader_pass(runtime, session, run=True)
        self.reader_pass(runtime, session, run=True)  # no duplicate START
        self.reader_pass(runtime, session, run=False)
        self.assertEqual(stream.writes, [b"START\n", b"STOP\n"])
        self.assertTrue(all(not write.startswith(b"SET_PWM") for write in stream.writes))

    def test_cancellation_sends_stop_not_pwm(self):
        stream = TelemetryStream([b"ACK:START\n"])
        session = RunSession(resources=ResourceManager())
        runtime = DataflowRuntime(serial=SerialAdapter(ArduinoBackend(stream)))
        self.reader_pass(runtime, session)
        session.token.cancel()
        self.assertEqual(stream.writes[-1], b"STOP\n")
        self.assertEqual(session.token.callback_errors, ())
        session.close()
        self.assertTrue(stream.closed)

    def test_cancellation_exposes_failed_safe_stop(self):
        stream = SilentStopStream([b"ACK:START\n"])
        session = RunSession(resources=ResourceManager())
        runtime = DataflowRuntime(serial=SerialAdapter(ArduinoBackend(stream)))
        self.reader_pass(runtime, session)
        session.token.cancel()
        self.assertTrue(any("safe-stop" in error for error in session.token.callback_errors))

    # ------------------------------------------------------------------
    # rpm_stall_watchdog: PC-side inference, NOT firmware data
    # ------------------------------------------------------------------

    def watchdog_pass(self, runtime, session, now, **overrides):
        inputs = {"run": True, "rpm": 0.0, "current_target_rpm": 1000.0}
        inputs.update(overrides)
        node = Node("node", "rpm_stall_watchdog", 0, 0, "watchdog", {"stall_seconds": 5.0})
        runtime.clock = lambda: now[0]
        return runtime._evaluate(node, inputs, {}, [], session=session)

    def test_stall_watchdog_triggers_only_after_threshold(self):
        session = RunSession(resources=ResourceManager())
        runtime = DataflowRuntime()
        now = [0.0]
        for step in range(3):  # t = 0, 2, 4 — all below the 5s threshold
            result = self.watchdog_pass(runtime, session, now)
            self.assertFalse(result, f"no stall before threshold at t={now[0]}")
            now[0] += 2.0
        result = self.watchdog_pass(runtime, session, now)  # t = 6
        self.assertTrue(result, "5s of rpm==0 at target>0 must trip the watchdog")

    def test_stall_watchdog_resets_on_recovery_or_idle(self):
        session = RunSession(resources=ResourceManager())
        runtime = DataflowRuntime()
        now = [0.0]
        self.watchdog_pass(runtime, session, now)
        recovered = self.watchdog_pass(runtime, session, now, rpm=990.0)
        self.assertFalse(recovered)
        now[0] += 100.0  # would trip if the timer had not been reset
        still_ok = self.watchdog_pass(runtime, session, now, rpm=990.0)
        self.assertFalse(still_ok)
        idle = self.watchdog_pass(runtime, session, now, current_target_rpm=0.0, rpm=0.0)
        self.assertFalse(idle, "target 0 means motor intentionally stopped")
        off = self.watchdog_pass(runtime, session, now, run=False)
        self.assertFalse(off)

    # ------------------------------------------------------------------
    # spinning_drop_stage_watcher: event-driven, never PC-timed
    # ------------------------------------------------------------------

    def watch_pass(self, session, **overrides):
        node = Node("watcher", "spinning_drop_stage_watcher", 0, 0, "watcher", {})
        return DataflowRuntime()._evaluate(node, watcher_inputs(**overrides), {}, [], session=session)

    def test_watcher_full_cycle_yields_exactly_six_rows(self):
        session = RunSession(resources=ResourceManager())
        # Real firmware: START is answered with ACK:START and an implicit
        # hardcoded ramp to 1000 RPM — no TARGET_RPM:1000 event ever exists.
        first = self.watch_pass(session)
        self.assertEqual(first["state"], "RUNNING")
        self.assertEqual(len(first["table_data"]), 1, "START announces nothing; header only")
        # First serial stage event of a real cycle is the increment to 2000.
        for index, target in enumerate((2000, 3000, 4000, 5000, 6000), start=1):
            result = self.watch_pass(session, stage_changed=True, current_target_rpm=float(target),
                                     rpm=float(target), elapsed_time_s=180.0 * index)
            self.assertEqual(len(result["table_data"]) - 1, index,
                             f"row for completed stage {target - 1000} missing")
            self.assertEqual(result["table_data"][-1][0], float(target - 1000),
                             "row must record the PREVIOUS stage's RPM")
        final = self.watch_pass(session, autostop=True)
        self.assertEqual(final["state"], "AWAITING_STOP")
        self.assertEqual(len(final["table_data"]) - 1, 6, "autostop completes the 6th row")
        self.assertEqual([row[0] for row in final["table_data"][1:]],
                         [1000.0, 2000.0, 3000.0, 4000.0, 5000.0, 6000.0])
        self.assertEqual(final["table_data"][0],
                         ["RPM", "Dia (px)", "Dia (mm)", "kg/m3", "w²", "r³", "IFT N/m", "IFT mN/m"])

    def test_watcher_does_not_lose_first_stage_row_matching_real_firmware(self):
        """Regression: firmware never sends TARGET_RPM:1000. The exact real
        event order is run=True -> TARGET_RPM:2000 .. TARGET_RPM:6000 ->
        ACK:AUTOSTOP_6000, and the final table must still hold all six rows
        starting with the implicit 1000 RPM stage."""
        session = RunSession(resources=ResourceManager())
        self.watch_pass(session)  # run=True alone: firmware announces nothing
        for target in (2000, 3000, 4000, 5000, 6000):
            self.watch_pass(session, stage_changed=True, current_target_rpm=float(target))
        final = self.watch_pass(session, autostop=True)
        rows = final["table_data"][1:]
        self.assertEqual(len(rows), 6,
                         "silent loss of the implicit 1000 RPM row is forbidden")
        self.assertEqual([row[0] for row in rows],
                         [1000.0, 2000.0, 3000.0, 4000.0, 5000.0, 6000.0])

    def test_watcher_never_appends_without_firmware_events(self):
        session = RunSession(resources=ResourceManager())
        self.watch_pass(session)  # RUNNING entry, no events announced
        for _ in range(25):
            result = self.watch_pass(session)  # telemetry flowing, no events
        self.assertEqual(len(result["table_data"]), 1,
                         "no internal timer may ever produce a row")

    def test_watcher_resets_on_stop(self):
        session = RunSession(resources=ResourceManager())
        self.watch_pass(session)
        stopped = self.watch_pass(session, autostop=True)
        self.assertEqual(len(stopped["table_data"]) - 1, 1, "implicit 1000 stage completed by autostop")
        reset = self.watch_pass(session, run=False)
        self.assertEqual(reset["state"], "IDLE")
        self.assertEqual(reset["table_data"],
                         [["RPM", "Dia (px)", "Dia (mm)", "kg/m3", "w²", "r³", "IFT N/m", "IFT mN/m"]])

    def test_watcher_error_states_halt_until_manual_stop(self):
        session = RunSession(resources=ResourceManager())
        faulted = self.watch_pass(session, error=ErrorCluster(True, 60, "port gone"))
        self.assertEqual(faulted["state"], "ERROR")
        self.assertTrue(faulted["error"].status)
        stuck = self.watch_pass(session)
        self.assertEqual(stuck["state"], "ERROR", "ERROR persists while run stays true")
        session2 = RunSession(resources=ResourceManager())
        stalled = self.watch_pass(session2, stalled=True)
        self.assertEqual(stalled["state"], "ERROR")
        self.assertIn("stall", stalled["error"].source.lower())

    # ------------------------------------------------------------------
    # measurement math (unchanged platform nodes)
    # ------------------------------------------------------------------

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
            "rpm": rpm, "diameter_mm": diameter_mm, "delta_rho": delta_rho})
        omega_squared = (2 * math.pi * rpm / 60) ** 2
        diameter_m = diameter_mm / 1000
        diameter_formula = delta_rho * omega_squared * diameter_m ** 3 / 32
        self.assertFalse(result["error"].status)
        self.assertAlmostEqual(result["ift_N_m"], diameter_formula, places=15)
        self.assertAlmostEqual(result["radius_cubed"], (diameter_m / 2) ** 3, places=20)
        self.assertAlmostEqual(result["ift_mN_m"], result["ift_N_m"] * 1000)

    def test_vonnegut_rejects_nonpositive_inputs_via_error_cluster(self):
        result = self.evaluate("vonnegut_ift", {"rpm": 0, "diameter_mm": 2, "delta_rho": 50})
        self.assertTrue(result["error"].status)
        self.assertEqual(result["ift_N_m"], 0)

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

    def test_spinning_drop_panel_gauge_and_table_helpers(self):
        self.assertEqual(gauge_fraction(3000, 0, 6000), 0.5)
        self.assertEqual(gauge_fraction(300, 0, 255), 1.0)
        self.assertEqual(table_rows([["RPM", "IFT"], [3000, 0.01]]),
                         [["RPM", "IFT"], [3000, 0.01]])
        self.assertEqual(next_dropdown_value("COM1", ["COM1", "COM2"]), "COM2")
        ppm = image_to_ppm(ImageFrame(Matrix([[0, 255]]), 2, 1, 1))
        self.assertTrue(ppm.startswith(b"P5\n2 1\n255\n"))

    # ------------------------------------------------------------------
    # example project
    # ------------------------------------------------------------------

    def test_spinning_drop_example_loads_and_wires_full_use_case(self):
        path = Path(__file__).parents[1] / "examples" / "spinning_drop_ift.json"
        project = load_project(path)
        graph = project.main.graph
        required = {"arduino_telemetry_reader", "camera_capture_dual_mode", "edge_intensity_profile",
                    "wire_calibration", "pixel_to_mm", "vonnegut_ift",
                    "spinning_drop_stage_watcher", "rpm_stall_watchdog", "report_generate"}
        self.assertTrue(required <= {node.type for node in graph.nodes.values()})
        self.assertEqual(DataflowRuntime().validate(graph, project, project.main_vi), [])
        labels = {item["properties"].get("label", "") for item in project.main.front_panel["items"]}
        for label in ("Motor", "RPM ACT", "PWM ACT", "COM Arduino", "WIFI IP", "TIME(s)",
                      "Picture Oil", "Picture Comparison", "Grafik Oil", "Grafik Kawat",
                      "Selisih Densitas (Kg/m3)", "w²", "r³", "IFT N/m", "IFT mN/m", "STOP"):
            self.assertIn(label, labels)
        table = next(item for item in project.main.front_panel["items"]
                     if item["properties"].get("display_type") == "table")
        self.assertEqual(table["properties"]["label"],
                         "RPM | Dia (px) | Dia (mm) | kg/m3 | w² | r³ | IFT N/m | IFT mN/m")
        self.assertEqual(project.main.front_panel["extensions"]["physical_validation"], "not performed")

    def test_example_single_pass_with_fake_telemetry(self):
        path = Path(__file__).parents[1] / "examples" / "spinning_drop_ift.json"
        project = load_project(path)
        # Real firmware traffic after START: ACK, then telemetry only. The
        # initial 1000 RPM target is implicit — no TARGET_RPM:1000 line exists.
        stream = TelemetryStream([b"ACK:START\n",
                                  b"RPM:1000;PWM:42;TIME:0.500;TARGET:1000\n"])
        with TemporaryDirectory() as directory:
            runtime = DataflowRuntime(serial=SerialAdapter(ArduinoBackend(stream)),
                                      vision=VisionAdapter(CaptureCv2(), object()),
                                      data_root=directory)
            result = runtime.run(project.main.graph, {}, project, project.main_vi)
            self.assertFalse(any("Cycle detected" in error for error in result.errors))
            self.assertFalse(any("missing input" in error for error in result.errors))
            csv_path = Path(directory, "spinning-drop-ift.csv")
            self.assertTrue(csv_path.exists())
            # No firmware stage-completion event arrived, so the report must
            # contain the header only — never fabricated measurement rows.
            self.assertEqual(len(csv_path.read_text().strip().splitlines()), 1)


if __name__ == "__main__":
    unittest.main()
