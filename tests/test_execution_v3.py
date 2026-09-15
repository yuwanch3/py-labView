import time
import unittest

from pylabview.execution import CancellationToken, CancelledError, Debugger, RunController, RunSession
from pylabview.model import Graph, Project
from pylabview.resources import ResourceManager
from pylabview.runtime import DataflowError, DataflowRuntime


def constant(graph, kind, value):
    node = graph.add_node(kind); node.properties["value"] = value; return node


class ExecutionV3Tests(unittest.TestCase):
    def test_cancellation_token_check(self):
        token = CancellationToken(); token.cancel()
        with self.assertRaises(CancelledError): token.check()

    def test_cancellation_wait_wakes_early(self):
        token = CancellationToken(); token.cancel()
        started = time.monotonic()
        self.assertTrue(token.wait(1))
        self.assertLess(time.monotonic() - started, 0.1)

    def test_debugger_trace_is_bounded_and_sequenced(self):
        debugger = Debugger(trace_limit=2)
        debugger.emit("one"); debugger.emit("two"); debugger.emit("three")
        self.assertEqual([event.sequence for event in debugger.trace], [2, 3])

    def test_debugger_probe_records_selected_wire_only(self):
        debugger = Debugger(); debugger.probes.add("selected")
        debugger.probe("other", "n", 1); debugger.probe("selected", "n", [1, 2])
        self.assertEqual(len(debugger.trace), 1)
        self.assertEqual(debugger.trace[0].kind, "probe")

    def test_delay_is_cooperatively_cancelled(self):
        graph = Graph(); source = constant(graph, "numeric_constant", 1); delay = graph.add_node("delay")
        delay.properties["seconds"] = 1; graph.connect(source.id, "out", delay.id, "value")
        controller = RunController(DataflowRuntime()); controller.start(graph)
        time.sleep(0.04); controller.stop()
        deadline = time.monotonic() + 1
        while controller.running and time.monotonic() < deadline: time.sleep(0.01)
        self.assertFalse(controller.running)
        self.assertIsNone(controller.last_result)
        kinds = [event.kind for event in controller.drain_events()]
        self.assertIn("run_cancelled", kinds)
        self.assertNotIn("result", kinds)

    def test_controller_returns_result_asynchronously(self):
        graph = Graph(); source = constant(graph, "numeric_constant", 8)
        controller = RunController(DataflowRuntime()); controller.start(graph)
        deadline = time.monotonic() + 1
        while controller.running and time.monotonic() < deadline: time.sleep(0.01)
        self.assertEqual(controller.last_result.values[source.id], 8)
        self.assertTrue(any(event.kind == "run_completed" for event in controller.drain_events()))

    def test_feedback_state_persists_in_session(self):
        graph = Graph(); feedback = graph.add_node("feedback"); one = constant(graph, "numeric_constant", 1); add = graph.add_node("add")
        graph.connect(feedback.id, "out", add.id, "a"); graph.connect(one.id, "out", add.id, "b")
        graph.connect(add.id, "out", feedback.id, "value")
        session = RunSession(resources=ResourceManager()); runtime = DataflowRuntime()
        first = runtime.run(graph, session=session); second = runtime.run(graph, session=session)
        self.assertFalse(first.errors + second.errors)
        self.assertEqual(first.values[feedback.id], 0)
        self.assertEqual(second.values[feedback.id], 1)
        session.close()

    def test_new_session_resets_feedback(self):
        graph = Graph(); feedback = graph.add_node("feedback"); feedback.properties["initial"] = 9
        source = constant(graph, "numeric_constant", 2); graph.connect(source.id, "out", feedback.id, "value")
        self.assertEqual(DataflowRuntime().run(graph).values[feedback.id], 9)
        self.assertEqual(DataflowRuntime().run(graph).values[feedback.id], 9)

    def test_arbitrary_cycle_still_rejected(self):
        graph = Graph(); a = graph.add_node("add"); b = graph.add_node("add")
        graph.connect(a.id, "out", b.id, "a"); graph.connect(b.id, "out", a.id, "a")
        with self.assertRaises(DataflowError): DataflowRuntime().topological_order(graph)

    def test_visual_case_executes_selected_subdiagram(self):
        project = Project(); graph = project.main.graph
        selector = constant(graph, "boolean_constant", True); value = constant(graph, "numeric_constant", 7)
        case = graph.add_node("visual_case")
        for name, scale in (("true", 2), ("false", 3)):
            child = Graph(name); incoming = child.add_node("structure_input"); factor = constant(child, "numeric_constant", scale)
            multiply = child.add_node("multiply"); output = child.add_node("structure_output")
            child.connect(incoming.id, "out", multiply.id, "a"); child.connect(factor.id, "out", multiply.id, "b")
            child.connect(multiply.id, "out", output.id, "value"); child.project = project
            project.main.subdiagrams[name] = child; case.properties[f"{name}_diagram"] = name
        graph.connect(selector.id, "out", case.id, "selector"); graph.connect(value.id, "out", case.id, "value")
        result = DataflowRuntime().run_project(project)
        self.assertFalse(result.errors); self.assertEqual(result.values[case.id], 14)

    def test_visual_for_exposes_value_and_iteration(self):
        project = Project(); graph = project.main.graph
        values = constant(graph, "array_constant", [10, 10, 10]); loop = graph.add_node("visual_for")
        body = Graph("body"); incoming = body.add_node("structure_input"); iteration = body.add_node("iteration_terminal")
        add = body.add_node("add"); output = body.add_node("structure_output")
        body.connect(incoming.id, "out", add.id, "a"); body.connect(iteration.id, "out", add.id, "b")
        body.connect(add.id, "out", output.id, "value"); body.project = project
        project.main.subdiagrams["body"] = body; loop.properties["body_diagram"] = "body"
        graph.connect(values.id, "out", loop.id, "array")
        result = DataflowRuntime().run_project(project)
        self.assertFalse(result.errors); self.assertEqual(result.values[loop.id], [10, 11, 12])

    def test_visual_for_bound_is_enforced(self):
        project = Project(); values = constant(project.main.graph, "array_constant", [1, 2]); loop = project.main.graph.add_node("visual_for")
        body = Graph("body"); incoming = body.add_node("structure_input"); output = body.add_node("structure_output")
        body.connect(incoming.id, "out", output.id, "value"); project.main.subdiagrams["body"] = body; project._bind_graphs()
        loop.properties.update(body_diagram="body", max_iterations=1); project.main.graph.connect(values.id, "out", loop.id, "array")
        self.assertIn("bound", DataflowRuntime().run_project(project).errors[0])


if __name__ == "__main__": unittest.main()
