import copy
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from pylabview.execution import CancellationToken, CancelledError, RunController, RunSession
from pylabview.model import (Graph, NODE_DEFINITIONS, NodeDefinition, Project,
                             clone_structure_properties, delete_owned_structure_diagrams,
                             update_chart_history)
from pylabview.persistence import load_project
from pylabview.plugins import DEFAULT_PLUGIN_REGISTRY, PluginManifest
from pylabview.protocols import ModbusTcpClient, TcpConnection, UdpEndpoint
from pylabview.resources import ResourceError, ResourceManager
from pylabview.runtime import DataflowRuntime


def constant(graph, kind="numeric_constant", value=0):
    node = graph.add_node(kind)
    node.properties["value"] = value
    return node


def wait_for_events(controller, predicate, timeout=2):
    deadline = time.monotonic() + timeout
    seen = []
    while time.monotonic() < deadline:
        seen.extend(controller.drain_events())
        if predicate(seen):
            return seen
        time.sleep(0.005)
    return seen


class AuditRuntimeTests(unittest.TestCase):
    def test_subdiagram_subvi_recursion_is_detected_and_blocks_delete(self):
        project = Project(); other = project.add_vi("Other")
        selector = constant(project.main.graph, "boolean_constant", True)
        value = constant(project.main.graph, value=1)
        case = project.main.graph.add_node("visual_case")
        project.main.graph.connect(selector.id, "out", case.id, "selector")
        project.main.graph.connect(value.id, "out", case.id, "value")
        body = Graph("body"); call = body.add_node("subvi"); call.properties["vi_id"] = other.id
        project.main.subdiagrams["body"] = body
        case.properties.update(true_diagram="body", false_diagram="body")
        back = other.graph.add_node("subvi"); back.properties["vi_id"] = project.main_vi
        project._bind_graphs()
        errors = DataflowRuntime().validate(project.main.graph, project, project.main_vi)
        self.assertTrue(any("recursion" in error for error in errors))
        with self.assertRaises(ValueError):
            project.delete_vi(other.id)

    def test_get_before_put_completes_in_debug_mode(self):
        graph = Graph(); create = graph.add_node("queue_create"); get = graph.add_node("queue_get")
        value = constant(graph, value=7); put = graph.add_node("queue_put")
        graph.connect(create.id, "out", get.id, "queue")
        graph.connect(create.id, "out", put.id, "queue"); graph.connect(value.id, "out", put.id, "value")
        result = DataflowRuntime(max_workers=1).run(graph, debug=True)
        self.assertFalse(result.errors); self.assertEqual(result.values[get.id], 7)

    def test_breakpoint_steps_can_dispatch_get_then_put_without_deadlock(self):
        graph = Graph(); create = graph.add_node("queue_create"); value = constant(graph, value=8)
        get = graph.add_node("queue_get"); put = graph.add_node("queue_put")
        graph.connect(create.id, "out", get.id, "queue")
        graph.connect(create.id, "out", put.id, "queue"); graph.connect(value.id, "out", put.id, "value")
        controller = RunController(DataflowRuntime(max_workers=1))
        controller.start(graph, debug=True, breakpoints={get.id})
        first = wait_for_events(controller, lambda items: any(
            event.kind == "breakpoint" and event.node_id == get.id for event in items))
        self.assertTrue(any(event.node_id == get.id for event in first if event.kind == "breakpoint"))
        controller.step()
        second = wait_for_events(controller, lambda items: any(
            event.kind == "breakpoint" and event.node_id == put.id for event in items))
        self.assertTrue(any(event.node_id == put.id for event in second if event.kind == "breakpoint"))
        controller.step()
        wait_for_events(controller, lambda _items: not controller.running)
        self.assertFalse(controller.running); self.assertEqual(controller.last_result.values[get.id], 8)

    def test_waiters_do_not_starve_producers_in_normal_mode(self):
        graph = Graph(); create = graph.add_node("queue_create")
        gets = [graph.add_node("queue_get") for _ in range(6)]
        values = [constant(graph, value=index) for index in range(6)]
        puts = [graph.add_node("queue_put") for _ in range(6)]
        for get in gets:
            graph.connect(create.id, "out", get.id, "queue")
        for value, put in zip(values, puts):
            graph.connect(create.id, "out", put.id, "queue"); graph.connect(value.id, "out", put.id, "value")
        result = DataflowRuntime(max_workers=2).run(graph)
        self.assertFalse(result.errors); self.assertEqual(sorted(result.values[node.id] for node in gets), list(range(6)))

    def test_sync_worker_bound_is_rejected_instead_of_starving(self):
        graph = Graph(); create = graph.add_node("queue_create")
        for _ in range(3):
            get = graph.add_node("queue_get"); graph.connect(create.id, "out", get.id, "queue")
        result = DataflowRuntime(max_sync_workers=2).run(graph)
        self.assertTrue(any("max_sync_workers" in error for error in result.errors))

    def test_result_events_carry_their_own_tick_payload(self):
        graph = Graph(); source = constant(graph, value=1)
        controller = RunController(DataflowRuntime()); controller.start(graph, continuous=True, interval=0.002)
        events = wait_for_events(controller, lambda items: len([e for e in items if e.kind == "result"]) >= 3)
        controller.stop()
        results = [event.payload for event in events if event.kind == "result"]
        self.assertGreaterEqual(len(results), 3)
        self.assertTrue(all(result.values[source.id] == 1 for result in results))
        self.assertEqual(len({id(result) for result in results}), len(results))

    def test_continuous_controls_update_at_tick_boundary(self):
        graph = Graph(); source = constant(graph, value=1)
        controller = RunController(DataflowRuntime())
        controller.start(graph, {source.id: 2}, continuous=True, interval=0.005)
        first = wait_for_events(controller, lambda items: any(e.kind == "result" for e in items))
        self.assertEqual(next(e.payload for e in first if e.kind == "result").values[source.id], 2)
        controller.update_controls({source.id: 9})
        later = wait_for_events(controller, lambda items: any(
            e.kind == "result" and e.payload.values[source.id] == 9 for e in items))
        controller.stop()
        self.assertTrue(any(e.kind == "result" and e.payload.values[source.id] == 9 for e in later))

    def test_feedback_state_is_scoped_by_subdiagram(self):
        def feedback_graph(initial, incoming):
            graph = Graph(); feedback = graph.add_node("feedback"); feedback.id = "same"
            graph.nodes = {feedback.id: feedback}; feedback.properties["initial"] = initial
            source = constant(graph, value=incoming); graph.connect(source.id, "out", feedback.id, "value")
            return graph, feedback
        session = RunSession(resources=ResourceManager()); runtime = DataflowRuntime()
        first, first_feedback = feedback_graph(0, 10); second, second_feedback = feedback_graph(99, 20)
        runtime.run(first, session=session, vi_id="vi", graph_scope="first")
        result = runtime.run(second, session=session, vi_id="vi", graph_scope="second")
        self.assertEqual(result.values[second_feedback.id], 99)
        session.close()

    def test_resource_cache_is_scoped_by_subdiagram(self):
        def resource_graph():
            graph = Graph(); node = graph.add_node("queue_create"); node.id = "same"
            graph.nodes = {node.id: node}; return graph, node
        session = RunSession(resources=ResourceManager()); runtime = DataflowRuntime()
        first, first_node = resource_graph(); second, second_node = resource_graph()
        first_ref = runtime.run(first, session=session, vi_id="vi", graph_scope="first").values[first_node.id]
        second_ref = runtime.run(second, session=session, vi_id="vi", graph_scope="second").values[second_node.id]
        self.assertNotEqual(first_ref, second_ref)
        session.close()

    def test_standalone_controller_uses_graph_snapshot(self):
        graph = Graph(); source = constant(graph, value=3)
        controller = RunController(DataflowRuntime()); controller.start(graph)
        source.properties["value"] = 99
        wait_for_events(controller, lambda items: any(e.kind == "result" for e in items))
        self.assertEqual(controller.last_result.values[source.id], 3)


class AuditResourceAndProtocolTests(unittest.TestCase):
    def test_cross_manager_ref_cannot_alias_same_local_id(self):
        first, second = ResourceManager(), ResourceManager()
        foreign = first.create_queue(1); second.create_queue(1)
        with self.assertRaises(ResourceError):
            second.get(foreign)
        first.close_all(); second.close_all()

    def test_cancelled_tcp_connect_closes_created_socket(self):
        class Socket:
            closed = False
            def setblocking(self, _blocking): pass
            def connect_ex(self, _address): token.cancel(); return 0
            def close(self): self.closed = True
        sock = Socket(); token = CancellationToken()
        address = [(2, 1, 6, "", ("127.0.0.1", 1234))]
        with patch("pylabview.protocols.socket.getaddrinfo", return_value=address), \
                patch("pylabview.protocols.socket.socket", return_value=sock):
            with self.assertRaises(CancelledError):
                TcpConnection.connect("host", 1234, 1, token)
        self.assertTrue(sock.closed)

    def test_tcp_read_polls_cancellation(self):
        import socket
        left, right = socket.socketpair(); token = CancellationToken(); connection = TcpConnection(left)
        threading.Timer(0.03, token.cancel).start(); started = time.monotonic()
        try:
            with self.assertRaises(CancelledError):
                connection.read(1, 10, token, "exactly")
            self.assertLess(time.monotonic() - started, 0.3)
        finally:
            connection.close(); right.close()

    def test_udp_empty_host_is_rejected(self):
        with self.assertRaises(ValueError):
            UdpEndpoint.open("", 0, 1)

    def test_modbus_rejects_register_range_overflow_and_fraction(self):
        client = ModbusTcpClient(object.__new__(TcpConnection))
        with self.assertRaises(ValueError):
            client.read_holding_registers(65535, 2, 1, CancellationToken())
        with self.assertRaises(ValueError):
            client.write_single_register(1.5, 2, 1, CancellationToken())

    def test_modbus_protocol_mismatch_invalidates_connection(self):
        import struct
        class Connection:
            closed = False
            def write(self, *_args): pass
            def read(self, size, *_args):
                if size == 7:
                    return struct.pack(">HHHB", 99, 0, 3, 1)
                return b"\x03\x00"
            def close(self): self.closed = True
        connection = Connection(); client = ModbusTcpClient(connection)
        with self.assertRaisesRegex(Exception, "transaction"):
            client.read_holding_registers(0, 1, 1, CancellationToken())
        self.assertTrue(connection.closed)


class AuditModelPanelPluginTests(unittest.TestCase):
    def test_panel_rejects_duplicate_mismatched_and_nonfinite_items(self):
        project = Project(); project.main.graph.add_node("numeric_constant"); base = project.to_dict()
        duplicate = copy.deepcopy(base); item = duplicate["vis"][0]["front_panel"]["items"][0]
        duplicate["vis"][0]["front_panel"]["items"].append({**copy.deepcopy(item), "id": "duplicate"})
        mismatched = copy.deepcopy(base); mismatched["vis"][0]["front_panel"]["items"][0]["kind"] = "chart"
        nonfinite = copy.deepcopy(base); nonfinite["vis"][0]["front_panel"]["canvas"]["width"] = float("inf")
        for data in (duplicate, mismatched, nonfinite):
            with self.subTest(data=data), self.assertRaises(ValueError):
                Project.from_dict(data)

    def test_scalar_chart_history_accumulates_and_trims_headless(self):
        history = update_chart_history([], 1, 3)
        history = update_chart_history(history, 2, 3)
        history = update_chart_history(history, 3, 3)
        history = update_chart_history(history, 4, 3)
        self.assertEqual(history, [2.0, 3.0, 4.0])

    def test_plugin_multi_output_is_mapped_generically(self):
        kind = "audit.multi"
        DEFAULT_PLUGIN_REGISTRY.register_node(
            kind, NodeDefinition("Multi", "Plugin", outputs=("left", "right")),
            lambda _node, _inputs, _session: {"left": 1, "right": 2})
        try:
            graph = Graph(); node = graph.add_node(kind); result = DataflowRuntime().run(graph)
            self.assertFalse(result.errors)
            self.assertEqual(result.values[node.id], {"left": 1, "right": 2})
        finally:
            DEFAULT_PLUGIN_REGISTRY.node_definitions.pop(kind, None)
            DEFAULT_PLUGIN_REGISTRY.evaluators.pop(kind, None)
            NODE_DEFINITIONS.pop(kind, None)

    def test_load_project_bootstraps_plugin_before_node_deserialization(self):
        kind = "audit.headless"
        class Plugin:
            manifest = PluginManifest("audit.headless", "1")
            def activate(self, registry):
                registry.register_node(kind, NodeDefinition("Headless", "Plugin"), lambda *_args: 5)
        class Entry:
            name = "audit-headless"
            def load(self): return Plugin
        class Points:
            def select(self, **_kwargs): return [Entry()]
        previous_discovered = DEFAULT_PLUGIN_REGISTRY._discovered
        previous_statuses = list(DEFAULT_PLUGIN_REGISTRY.statuses)
        DEFAULT_PLUGIN_REGISTRY._discovered = False
        data = Project().to_dict()
        data["vis"][0]["graph"]["nodes"] = [{"id": "plugin", "type": kind, "x": 0, "y": 0,
                                                     "label": "Plugin", "properties": {}}]
        try:
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "plugin.json"; path.write_text(json.dumps(data), encoding="utf-8")
                with patch("pylabview.plugins.metadata.entry_points", return_value=Points()):
                    project = load_project(path)
            self.assertFalse(DataflowRuntime().run_project(project).errors)
        finally:
            DEFAULT_PLUGIN_REGISTRY._discovered = previous_discovered
            DEFAULT_PLUGIN_REGISTRY.statuses[:] = previous_statuses
            DEFAULT_PLUGIN_REGISTRY.node_definitions.pop(kind, None)
            DEFAULT_PLUGIN_REGISTRY.evaluators.pop(kind, None)
            NODE_DEFINITIONS.pop(kind, None)

    def test_visual_structure_copy_has_owned_diagrams_and_delete_cleans_only_copy(self):
        project = Project(); node = project.main.graph.add_node("visual_case")
        for key in ("true_diagram", "false_diagram"):
            graph = Graph(key); source = graph.add_node("structure_input"); output = graph.add_node("structure_output")
            graph.connect(source.id, "out", output.id, "value")
            project.main.subdiagrams[key] = graph; node.properties[key] = key
        project._bind_graphs()
        copied = project.main.graph.add_node("visual_case")
        copied.properties = clone_structure_properties(project, project.main_vi, copied.type, node.properties)
        self.assertNotEqual(copied.properties["true_diagram"], node.properties["true_diagram"])
        copied_ids = set(copied.properties.values()); original_ids = set(node.properties.values())
        delete_owned_structure_diagrams(project, project.main_vi, copied)
        self.assertTrue(original_ids <= set(project.main.subdiagrams))
        self.assertTrue(copied_ids.isdisjoint(project.main.subdiagrams))


if __name__ == "__main__":
    unittest.main()
