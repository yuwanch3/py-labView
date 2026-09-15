from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from pylabview.hdl import HdlExportError, export_verilog, yosys_syntax_check
from pylabview.integrations.capabilities import collect_diagnostics, collect_hardware_diagnostics_bounded, diagnostics_text
from pylabview.integrations.isolation import IsolatedEvaluatorError, IsolatedEvaluatorHost
from pylabview.model import Graph
from pylabview.targets import probe_target


def slow_diagnostics_worker(connection, _manifest):
    import time
    time.sleep(2)
    connection.close()


class HdlTests(unittest.TestCase):
    def test_golden_add_export(self):
        graph = Graph("Adder"); a = graph.add_node("numeric_constant"); b = graph.add_node("numeric_constant"); out = graph.add_node("structure_output")
        a.properties["value"] = 2; b.properties["value"] = 3; add = graph.add_node("add"); graph.connect(a.id, "out", add.id, "a"); graph.connect(b.id, "out", add.id, "b"); graph.connect(add.id, "out", out.id, "value")
        source = export_verilog(graph, "golden"); self.assertIn("module m_golden", source); self.assertIn("assign w_", source); self.assertIn(" + ", source)
    def test_unsupported_node_rejected(self):
        graph = Graph(); graph.add_node("file_read")
        with self.assertRaises(HdlExportError): export_verilog(graph)
    def test_graph_requires_output(self):
        graph = Graph(); graph.add_node("numeric_constant")
        with self.assertRaises(HdlExportError): export_verilog(graph)
    def test_yosys_unavailable_is_honest(self):
        result = yosys_syntax_check("module x(); endmodule", executable="")
        if not result.available: self.assertFalse(result.succeeded)

    def test_sanitized_node_ids_cannot_collide(self):
        from pylabview.model import Node
        graph = Graph(); a = Node("a-b", "numeric_constant", 0, 0, "a", {"value": 1}); b = Node("a_b", "numeric_constant", 0, 0, "b", {"value": 2})
        graph.nodes[a.id] = a; graph.nodes[b.id] = b; add = graph.add_node("add"); out = graph.add_node("structure_output")
        graph.connect(a.id, "out", add.id, "a"); graph.connect(b.id, "out", add.id, "b"); graph.connect(add.id, "out", out.id, "value")
        source = export_verilog(graph)
        declarations = [line.strip() for line in source.splitlines() if line.strip().startswith("wire")]
        self.assertEqual(len(declarations), len(set(declarations)))

    def test_keywords_and_duplicate_labels_are_namespaced_and_unique(self):
        graph = Graph("module"); a = graph.add_node("numeric_constant"); b = graph.add_node("numeric_constant")
        a.properties["value"] = 1; b.properties["value"] = 2
        out_a = graph.add_node("display"); out_b = graph.add_node("display"); out_a.label = out_b.label = "output"
        graph.connect(a.id, "out", out_a.id, "value"); graph.connect(b.id, "out", out_b.id, "value")
        source = export_verilog(graph, "module")
        self.assertIn("module m_module", source); self.assertIn("p_out_output_2", source)

    def test_export_passes_yosys_when_available(self):
        graph = Graph(); value = graph.add_node("numeric_constant"); value.properties["value"] = 1
        out = graph.add_node("structure_output"); graph.connect(value.id, "out", out.id, "value")
        result = yosys_syntax_check(export_verilog(graph))
        if result.available: self.assertTrue(result.succeeded, result.output)


class DiagnosticsTests(unittest.TestCase):
    def test_hardware_is_not_enumerated_without_refresh(self):
        backend = SimpleNamespace(system=SimpleNamespace(System=SimpleNamespace(local=lambda: (_ for _ in ()).throw(AssertionError()))))
        result = collect_diagnostics(refresh_hardware=False, module_loader=lambda name: (_ for _ in ()).throw(ImportError(name)), nidaq_backend=backend, command_finder=lambda name: None)
        self.assertEqual(result.ni_devices, []); self.assertFalse(result.realtime.available)
    def test_explicit_refresh_enumerates_injected_devices(self):
        local = lambda: SimpleNamespace(devices=[SimpleNamespace(name="Dev1")])
        backend = SimpleNamespace(system=SimpleNamespace(System=SimpleNamespace(local=local)))
        result = collect_diagnostics(refresh_hardware=True, module_loader=lambda name: (_ for _ in ()).throw(ImportError(name)), nidaq_backend=backend, command_finder=lambda name: None)
        self.assertEqual(result.ni_devices, ["Dev1"])
    def test_text_says_realtime_unavailable(self):
        result = collect_diagnostics(module_loader=lambda name: (_ for _ in ()).throw(ImportError(name)), command_finder=lambda name: None)
        self.assertIn("Real-time target: unavailable", diagnostics_text(result))

    def test_bounded_hardware_diagnostics_validates_timeout(self):
        with self.assertRaises(ValueError): collect_hardware_diagnostics_bounded(timeout=0)

    def test_bounded_hardware_diagnostics_terminates_slow_process(self):
        result = collect_hardware_diagnostics_bounded(timeout=.05, _worker=slow_diagnostics_worker)
        self.assertIn("timed out", result.errors[0])


class FakeSocket:
    def __init__(self, response): self.response = response; self.closed = False
    def settimeout(self, timeout): self.timeout = timeout
    def sendall(self, data): self.sent = data
    def recv(self, size): return self.response
    def close(self): self.closed = True


class TargetTests(unittest.TestCase):
    def test_unconfigured_target_is_unavailable(self): self.assertFalse(probe_target(None).available)
    def test_valid_handshake(self):
        sock = FakeSocket(b'{"protocol":"pylabview-target","version":1,"status":"ready","name":"rt","capabilities":["run"]}\n')
        status = probe_target({"host": "127.0.0.1", "port": 1, "timeout": 1}, lambda *a, **k: sock)
        self.assertTrue(status.available); self.assertEqual(status.capabilities, ("run",)); self.assertTrue(sock.closed)
    def test_invalid_handshake_is_rejected_and_closed(self):
        sock = FakeSocket(b'{}\n')
        with self.assertRaises(ValueError): probe_target({"host": "x", "port": 1, "timeout": 1}, lambda *a, **k: sock)
        self.assertTrue(sock.closed)
    def test_manifest_is_strict(self):
        with self.assertRaises(ValueError): probe_target({"host": "x"})


def isolated_success(payload): return {"value": payload["value"] + 1}
def isolated_timeout(payload):
    import time; time.sleep(2); return payload
def isolated_crash(payload):
    import os; os._exit(3)


class IsolationTests(unittest.TestCase):
    def test_success_uses_json_request_response(self):
        with IsolatedEvaluatorHost(isolated_success) as host: self.assertEqual(host.call({"value": 2}, 2), {"value": 3})
    def test_timeout_terminates_child(self):
        with IsolatedEvaluatorHost(isolated_timeout) as host:
            with self.assertRaises(TimeoutError): host.call({}, .05)
            self.assertFalse(host._process.is_alive())
    def test_crash_is_detected(self):
        with IsolatedEvaluatorHost(isolated_crash) as host:
            with self.assertRaises(IsolatedEvaluatorError): host.call({}, 2)

    def test_importable_path_string_works(self):
        with IsolatedEvaluatorHost("tests.test_platform_v4:isolated_success") as host:
            self.assertEqual(host.call({"value": 4}, 2), {"value": 5})

    def test_lambda_is_rejected_before_spawn(self):
        with self.assertRaisesRegex(ValueError, "module-level"):
            IsolatedEvaluatorHost(lambda value: value)

    def test_closure_is_rejected_before_spawn(self):
        captured = 1
        def local(value): return value + captured
        with self.assertRaisesRegex(ValueError, "module-level"): IsolatedEvaluatorHost(local)


if __name__ == "__main__": unittest.main()
