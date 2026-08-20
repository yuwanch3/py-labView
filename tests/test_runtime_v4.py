from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from pylabview.integrations.serial_adapter import SerialAdapter
from pylabview.model import Graph, NODE_DEFINITIONS
from pylabview.runtime import DataflowRuntime


class Stream:
    def __init__(self): self.closed = False; self.writes = []
    def read(self, size): return b"hello"[:size]
    def write(self, data): self.writes.append(data); return len(data)
    def close(self): self.closed = True


class RuntimeV4Tests(unittest.TestCase):
    def test_instrumentation_nodes_are_visible(self):
        required = {"visa_open", "opcua_connect", "image_read", "report_generate", "modbus_read_coils", "serial_read"}
        self.assertTrue(required <= set(NODE_DEFINITIONS))

    def test_report_node_generates_actual_html(self):
        with TemporaryDirectory() as directory:
            graph = Graph(); data = graph.add_node("array_constant"); data.properties["value"] = [["a", 1]]
            report = graph.add_node("report_generate"); report.properties.update(path="report.html", format="html")
            graph.connect(data.id, "out", report.id, "data"); result = DataflowRuntime(data_root=directory).run(graph)
            self.assertFalse(result.errors); self.assertTrue((Path(directory) / "report.html").is_file()); self.assertFalse(result.values[report.id]["error"].status)

    def test_report_path_escape_returns_error_cluster(self):
        with TemporaryDirectory() as directory:
            graph = Graph(); data = graph.add_node("array_constant"); report = graph.add_node("report_generate"); report.properties["path"] = "../escape.html"
            graph.connect(data.id, "out", report.id, "data"); result = DataflowRuntime(data_root=directory).run(graph)
            self.assertFalse(result.errors); self.assertTrue(result.values[report.id]["error"].status)

    def test_serial_read_node_uses_injected_backend_and_closes(self):
        stream = Stream(); backend = SimpleNamespace(serial_for_url=lambda *a, **k: stream)
        graph = Graph(); opened = graph.add_node("serial_open"); opened.properties["port"] = "loop://"; read = graph.add_node("serial_read"); read.properties["size"] = 5
        graph.connect(opened.id, "out", read.id, "connection"); result = DataflowRuntime(serial=SerialAdapter(backend)).run(graph)
        self.assertEqual(result.values[read.id], b"hello"); self.assertTrue(stream.closed)

    def test_serial_text_write_encodes_and_closes(self):
        stream = Stream(); backend = SimpleNamespace(serial_for_url=lambda *a, **k: stream)
        graph = Graph(); opened = graph.add_node("serial_open"); text = graph.add_node("string_constant"); text.properties["value"] = "hi"
        write = graph.add_node("serial_write"); write.properties["mode"] = "text"; graph.connect(opened.id, "out", write.id, "connection"); graph.connect(text.id, "out", write.id, "data")
        result = DataflowRuntime(serial=SerialAdapter(backend)).run(graph)
        self.assertFalse(result.errors); self.assertEqual(stream.writes, [b"hi"]); self.assertTrue(stream.closed)

    def test_scalar_daq_node_forces_one_sample(self):
        configured = []
        class Driver:
            def configure(self, config): configured.append(config)
            def read(self, channel): return 1.0
            def write(self, channel, value): pass
        from pylabview.drivers import DriverRegistry
        registry = DriverRegistry(); registry.register("test", Driver())
        graph = Graph(); node = graph.add_node("analog_input")
        node.properties.update(driver="test", channel="x", samples=50)
        result = DataflowRuntime(drivers=registry).run(graph)
        self.assertFalse(result.errors); self.assertEqual(configured[0].samples, 1)

    def test_numeric_cannot_wire_to_image_operator(self):
        graph = Graph(); number = graph.add_node("numeric_constant"); blur = graph.add_node("image_blur")
        with self.assertRaisesRegex(ValueError, "Incompatible"):
            graph.connect(number.id, "out", blur.id, "image")


if __name__ == "__main__": unittest.main()
