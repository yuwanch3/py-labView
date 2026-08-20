from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from threading import Lock, Thread
import time
import unittest

from pylabview.drivers import ChannelConfig
from pylabview.integrations.nidaqmx_adapter import NIDAQmxDriver
from pylabview.integrations.opcua_adapter import OpcUaAdapter
from pylabview.integrations.reports_adapter import ReportsAdapter
from pylabview.integrations.serial_adapter import SerialAdapter
from pylabview.integrations.visa_adapter import VisaAdapter
from pylabview.integrations.vision_adapter import ImageFrame, VisionAdapter


class FakeChannels:
    def __init__(self, calls): self.calls = calls
    def add_ai_voltage_chan(self, *args, **kwargs): self.calls.append(("ai", args, kwargs))
    def add_ao_voltage_chan(self, *args, **kwargs): self.calls.append(("ao", args, kwargs))
    def add_di_chan(self, *args): self.calls.append(("di", args))
    def add_do_chan(self, *args): self.calls.append(("do", args))


class FakeTask:
    def __init__(self, backend):
        self.backend = backend; self.calls = []; self.closed = False
        self.ai_channels = self.ao_channels = self.di_channels = self.do_channels = FakeChannels(self.calls)
        self.timing = SimpleNamespace(cfg_samp_clk_timing=lambda *a, **k: self.calls.append(("timing", a, k)))
    def read(self, **kwargs):
        self.calls.append(("read", kwargs))
        if self.backend.read_error: raise RuntimeError("read failed")
        return self.backend.read_value
    def write(self, value, **kwargs): self.calls.append(("write", value, kwargs))
    def close(self): self.closed = True; self.calls.append(("close",))


class FakeNidaq:
    def __init__(self, value=1.5):
        self.read_value = value; self.read_error = False; self.tasks = []
        self.constants = SimpleNamespace(AcquisitionType=SimpleNamespace(FINITE="finite"))
    def Task(self): task = FakeTask(self); self.tasks.append(task); return task


class NidaqAdapterTests(unittest.TestCase):
    def test_scalar_ai_call_sequence_and_close(self):
        backend = FakeNidaq(); driver = NIDAQmxDriver(backend); driver.configure(ChannelConfig("Dev1/ai0", "analog_input"))
        self.assertEqual(driver.read("Dev1/ai0"), 1.5); self.assertEqual(backend.tasks[0].calls[0][0], "ai"); self.assertTrue(backend.tasks[0].closed)

    def test_finite_ai_configures_timing(self):
        backend = FakeNidaq([1, 2, 3]); driver = NIDAQmxDriver(backend)
        driver.configure(ChannelConfig("Dev1/ai0", "analog_input", samples=3, rate=500))
        self.assertEqual(driver.read("Dev1/ai0"), [1.0, 2.0, 3.0]); self.assertTrue(any(call[0] == "timing" for call in backend.tasks[0].calls))

    def test_read_error_closes_task(self):
        backend = FakeNidaq(); backend.read_error = True; driver = NIDAQmxDriver(backend); driver.configure(ChannelConfig("Dev1/ai0", "analog_input"))
        with self.assertRaises(RuntimeError): driver.read("Dev1/ai0")
        self.assertTrue(backend.tasks[0].closed)

    def test_analog_output_bounds_before_task(self):
        backend = FakeNidaq(); driver = NIDAQmxDriver(backend); driver.configure(ChannelConfig("Dev1/ao0", "analog_output", -1, 1))
        with self.assertRaises(ValueError): driver.write("Dev1/ao0", 2)
        self.assertEqual(backend.tasks, [])

    def test_digital_output_requires_boolean(self):
        driver = NIDAQmxDriver(FakeNidaq()); driver.configure(ChannelConfig("Dev1/port0/line0", "digital_output"))
        with self.assertRaises(TypeError): driver.write("Dev1/port0/line0", 1)

    def test_samples_are_bounded(self):
        driver = NIDAQmxDriver(FakeNidaq())
        with self.assertRaises(ValueError): driver.configure(ChannelConfig("x", "analog_input", samples=1_000_001))

    def test_rate_is_bounded(self):
        driver = NIDAQmxDriver(FakeNidaq())
        with self.assertRaises(ValueError): driver.configure(ChannelConfig("x", "analog_input", rate=0))

    def test_finite_read_requires_exact_sample_count(self):
        backend = FakeNidaq([1]); driver = NIDAQmxDriver(backend)
        driver.configure(ChannelConfig("x", "analog_input", samples=2))
        with self.assertRaisesRegex(RuntimeError, "finite sample"): driver.read("x")

    def test_finite_read_rejects_nested_multi_channel_payload(self):
        backend = FakeNidaq([[1, 2], [3, 4]]); driver = NIDAQmxDriver(backend)
        driver.configure(ChannelConfig("x", "analog_input", samples=2))
        with self.assertRaisesRegex(RuntimeError, "finite sample"): driver.read("x")

    def test_non_analog_finite_configuration_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "only for analog"):
            NIDAQmxDriver(FakeNidaq()).configure(ChannelConfig("x", "digital_input", samples=2))

    def test_scalar_multi_channel_payload_is_rejected(self):
        backend = FakeNidaq([1, 2]); driver = NIDAQmxDriver(backend)
        driver.configure(ChannelConfig("x", "analog_input"))
        with self.assertRaisesRegex(RuntimeError, "multi-channel"): driver.read("x")

    def test_digital_scalar_requires_boolean(self):
        backend = FakeNidaq(1); driver = NIDAQmxDriver(backend)
        driver.configure(ChannelConfig("x", "digital_input"))
        with self.assertRaisesRegex(RuntimeError, "boolean"): driver.read("x")


class FakeInstrument:
    def __init__(self): self.timeout = None; self.closed = False; self.raw = b"abc"
    def write(self, text): self.last = text; return len(text)
    def query(self, text): self.last = text; return "answer"
    def read_raw(self): return self.raw
    def write_raw(self, data): self.last = data; return len(data)
    def close(self): self.closed = True


class FakeResourceManager:
    def __init__(self): self.instrument = FakeInstrument(); self.closed = False
    def open_resource(self, resource): self.resource = resource; return self.instrument
    def list_resources(self): return ("USB::1", "TCPIP::2")
    def close(self): self.closed = True


class VisaAdapterTests(unittest.TestCase):
    def setUp(self): self.managers = []; self.adapter = VisaAdapter(lambda: self._manager())
    def _manager(self): manager = FakeResourceManager(); self.managers.append(manager); return manager
    def test_open_sets_millisecond_timeout(self): self.adapter.open("USB::1", .25).close(); self.assertEqual(self.managers[0].instrument.timeout, 250)
    def test_text_write_and_query(self):
        instrument = self.adapter.open("USB::1"); self.assertEqual(instrument.write("*IDN?"), 5); self.assertEqual(instrument.query("Q"), "answer"); instrument.close()
    def test_raw_read_and_write(self):
        instrument = self.adapter.open("USB::1"); self.assertEqual(instrument.read_raw(), b"abc"); self.assertEqual(instrument.write_raw(b"x"), 1); instrument.close()
    def test_response_bound(self):
        instrument = self.adapter.open("USB::1", max_bytes=2)
        with self.assertRaises(ValueError): instrument.read_raw()
        instrument.close()
    def test_close_closes_instrument_and_manager(self):
        instrument = self.adapter.open("USB::1"); instrument.close(); self.assertTrue(self.managers[0].closed); self.assertTrue(self.managers[0].instrument.closed)
    def test_list_resources_closes_manager(self): self.assertEqual(self.adapter.list_resources(), ["USB::1", "TCPIP::2"]); self.assertTrue(self.managers[0].closed)
    def test_invalid_timeout_closes_opened_handles(self):
        with self.assertRaises(ValueError): self.adapter.open("USB::1", 0)
        self.assertTrue(self.managers[0].closed); self.assertTrue(self.managers[0].instrument.closed)

    def test_query_requires_text(self):
        instrument = self.adapter.open("USB::1")
        with self.assertRaises(TypeError): instrument.query(1)
        instrument.close()

    def test_operations_after_close_are_rejected(self):
        instrument = self.adapter.open("USB::1"); instrument.close()
        with self.assertRaisesRegex(RuntimeError, "closed"): instrument.read_raw()

    def test_operations_on_one_instrument_are_serialized(self):
        manager = FakeResourceManager(); active = 0; maximum = 0; guard = Lock()
        def query(_text):
            nonlocal active, maximum
            with guard: active += 1; maximum = max(maximum, active)
            time.sleep(.03)
            with guard: active -= 1
            return "ok"
        manager.instrument.query = query
        instrument = VisaAdapter(lambda: manager).open("USB::1")
        threads = [Thread(target=instrument.query, args=("Q",)) for _ in range(2)]
        for thread in threads: thread.start()
        for thread in threads: thread.join()
        instrument.close(); self.assertEqual(maximum, 1)


class FakeOpcClient:
    def __init__(self, endpoint, timeout): self.endpoint = endpoint; self.timeout = timeout; self.values = {}; self.connected = False
    def connect(self): self.connected = True
    def disconnect(self): self.connected = False
    def get_node(self, node_id):
        return SimpleNamespace(read_value=lambda: self.values.get(node_id, 7), write_value=lambda value: self.values.__setitem__(node_id, value))


class OpcUaAdapterTests(unittest.TestCase):
    def test_connect_read_write_disconnect(self):
        connection = OpcUaAdapter(FakeOpcClient).connect("opc.tcp://localhost:4840", 1)
        self.assertEqual(connection.read("ns=2;s=x"), 7); connection.write("ns=2;s=x", 9); self.assertEqual(connection.read("ns=2;s=x"), 9)
        client = connection.client; connection.close(); self.assertFalse(client.connected)
    def test_endpoint_scheme_is_validated(self):
        with self.assertRaises(ValueError): OpcUaAdapter(FakeOpcClient).connect("http://localhost", 1)
    def test_timeout_is_bounded(self):
        with self.assertRaises(ValueError): OpcUaAdapter(FakeOpcClient).connect("opc.tcp://localhost", 301)
    def test_empty_node_id_is_rejected(self):
        connection = OpcUaAdapter(FakeOpcClient).connect("opc.tcp://localhost", 1)
        with self.assertRaises(ValueError): connection.read("")
        connection.close()

    def test_operation_after_disconnect_is_rejected(self):
        connection = OpcUaAdapter(FakeOpcClient).connect("opc.tcp://localhost:4840", 1); connection.close()
        with self.assertRaisesRegex(RuntimeError, "closed"): connection.read("ns=2;s=x")


class ReportsTests(unittest.TestCase):
    def test_html_is_escaped_and_atomic(self):
        with TemporaryDirectory() as directory:
            path = ReportsAdapter().generate([["<x>"]], Path(directory) / "report.html", "html")
            self.assertIn("&lt;x&gt;", path.read_text(encoding="utf-8")); self.assertEqual(list(Path(directory).glob(".*")), [])
    def test_csv_writes_rows(self):
        with TemporaryDirectory() as directory:
            path = ReportsAdapter().generate([["a", 1], ["b", 2]], Path(directory) / "report.csv", "csv")
            self.assertEqual(path.read_text(encoding="utf-8").splitlines(), ["a,1", "b,2"])
    def test_cluster_becomes_key_value_rows(self):
        with TemporaryDirectory() as directory:
            path = ReportsAdapter().generate({"a": 1}, Path(directory) / "report.csv", "csv")
            self.assertEqual(path.read_text(encoding="utf-8").strip(), "a,1")
    def test_unknown_format_rejected(self):
        with TemporaryDirectory() as directory:
            with self.assertRaises(ValueError): ReportsAdapter().generate([], Path(directory) / "x.bin", "bin")
    def test_optional_xlsx_uses_injected_library(self):
        saved = []
        class Sheet:
            def append(self, row): saved.append(tuple(row))
        class Book:
            def __init__(self): self.active = Sheet()
            def save(self, path): Path(path).write_bytes(b"xlsx")
        adapter = ReportsAdapter(lambda name: SimpleNamespace(Workbook=Book))
        with TemporaryDirectory() as directory:
            path = adapter.generate([[1, 2]], Path(directory) / "x.xlsx", "xlsx")
            self.assertEqual(path.read_bytes(), b"xlsx"); self.assertEqual(saved, [(1, 2)])


class FakeSerialBackend:
    def __init__(self): self.stream = SimpleNamespace(closed=False, close=lambda: setattr(self.stream, "closed", True))
    def serial_for_url(self, port, **kwargs): self.port = port; self.kwargs = kwargs; return self.stream


class SerialAdapterTests(unittest.TestCase):
    def test_backend_injection_and_timeout(self):
        backend = FakeSerialBackend(); stream = SerialAdapter(backend).open("loop://", 115200, .5)
        self.assertIs(stream.stream, backend.stream); self.assertEqual(backend.kwargs["write_timeout"], .5)
    def test_port_is_required(self):
        with self.assertRaises(ValueError): SerialAdapter(FakeSerialBackend()).open("")
    def test_baudrate_is_bounded(self):
        with self.assertRaises(ValueError): SerialAdapter(FakeSerialBackend()).open("loop://", 0)

    def test_operation_after_close_is_rejected(self):
        connection = SerialAdapter(FakeSerialBackend()).open("loop://"); connection.close()
        with self.assertRaisesRegex(RuntimeError, "closed"): connection.read(1)


class ShapePayload:
    def __init__(self, shape, dtype="uint8", itemsize=1, nbytes=None):
        self.shape = shape; self.dtype = SimpleNamespace(name=dtype, itemsize=itemsize)
        elements = 1
        for value in shape: elements *= value
        self.nbytes = elements * itemsize if nbytes is None else nbytes


class FakeCapture:
    def __init__(self): self.released = False
    def isOpened(self): return True
    def read(self): return True, ShapePayload((10, 20, 3))
    def release(self): self.released = True


class FakeCv2:
    IMREAD_UNCHANGED = -1; COLOR_BGR2GRAY = 1; THRESH_BINARY = 2; TM_CCOEFF_NORMED = 3
    def __init__(self): self.capture = FakeCapture()
    def imread(self, path, flag): return ShapePayload((10, 20, 3))
    def VideoCapture(self, index): return self.capture
    def cvtColor(self, payload, mode): return ShapePayload((payload.shape[0], payload.shape[1]))
    def GaussianBlur(self, payload, kernel, sigma): return payload
    def threshold(self, payload, low, maximum, mode): return low, payload
    def Canny(self, payload, low, high): return payload
    def resize(self, payload, dimensions): return ShapePayload((dimensions[1], dimensions[0], 3))
    def matchTemplate(self, image, template, mode): return object()
    def minMaxLoc(self, result): return 0, .8, (0, 0), (4, 5)
    def imwrite(self, path, payload): return True


class VisionTests(unittest.TestCase):
    def setUp(self): self.cv2 = FakeCv2(); self.vision = VisionAdapter(self.cv2, object()); self.frame = ImageFrame(ShapePayload((10, 20, 3)), 20, 10, 3)
    def test_read_wraps_metadata(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "x.png"; path.write_bytes(b"fake")
            self.assertEqual(self.vision.read(path).width, 20)
    def test_capture_releases_camera(self): self.vision.capture(0); self.assertTrue(self.cv2.capture.released)
    def test_grayscale_metadata(self): self.assertEqual(self.vision.grayscale(self.frame).channels, 1)
    def test_blur_kernel_validation(self):
        with self.assertRaises(ValueError): self.vision.blur(self.frame, 4)
    def test_resize_validation_and_metadata(self): self.assertEqual(self.vision.resize(self.frame, 5, 6).height, 6)
    def test_canny_threshold_validation(self):
        with self.assertRaises(ValueError): self.vision.canny(self.frame, 100, 50)
    def test_template_match_result(self): self.assertEqual(self.vision.template_match(self.frame, self.frame), {"score": .8, "x": 4, "y": 5})
    def test_image_pixel_bound(self):
        with self.assertRaises(ValueError): ImageFrame(None, 10001, 10000, 3)

    def test_image_metadata_must_match_payload(self):
        with self.assertRaisesRegex(ValueError, "metadata"):
            ImageFrame(ShapePayload((10, 20, 3)), 99, 10, 3)

    def test_image_dtype_is_validated(self):
        with self.assertRaisesRegex(ValueError, "dtype"):
            ImageFrame(ShapePayload((10, 20, 3), "object", 8), 20, 10, 3)

    def test_image_nbytes_is_validated(self):
        with self.assertRaisesRegex(ValueError, "memory"):
            ImageFrame(ShapePayload((10, 20, 3), nbytes=1), 20, 10, 3)

    def test_operator_requires_image_frame(self):
        with self.assertRaises(TypeError): self.vision.blur(object(), 3)

    def test_template_channels_must_match(self):
        gray = ImageFrame(ShapePayload((10, 20)), 20, 10, 1)
        with self.assertRaisesRegex(ValueError, "channels"): self.vision.template_match(self.frame, gray)


if __name__ == "__main__": unittest.main()
