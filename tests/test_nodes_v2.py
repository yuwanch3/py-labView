import json
import tempfile
import time
import unittest
from pathlib import Path

from pylabview.model import Graph
from pylabview.runtime import DataflowRuntime
from pylabview.typesystem import ErrorCluster, Waveform, editor_value_text


def constant(graph, node_type, value):
    node = graph.add_node(node_type)
    node.properties["value"] = value
    return node


class V2NodeTests(unittest.TestCase):
    def test_array_editor_text_is_valid_json(self):
        self.assertEqual(json.loads(editor_value_text(["a", 2])), ["a", 2])

    def test_array_build_index_and_size(self):
        graph = Graph()
        a, b = constant(graph, "numeric_constant", 5), constant(graph, "array_constant", [6, 7])
        build, size = graph.add_node("array_build"), graph.add_node("array_size")
        graph.connect(a.id, "out", build.id, "a"); graph.connect(b.id, "out", build.id, "b")
        graph.connect(build.id, "out", size.id, "array")
        result = DataflowRuntime().run(graph)
        self.assertEqual(result.values[build.id], [5, 6, 7])
        self.assertEqual(result.values[size.id], 3)

    def test_cluster_bundle_unbundle(self):
        graph = Graph()
        a, b = constant(graph, "string_constant", "x"), constant(graph, "numeric_constant", 2)
        bundle, unbundle = graph.add_node("cluster_bundle"), graph.add_node("cluster_unbundle")
        graph.connect(a.id, "out", bundle.id, "a"); graph.connect(b.id, "out", bundle.id, "b")
        graph.connect(bundle.id, "out", unbundle.id, "cluster")
        result = DataflowRuntime().run(graph)
        self.assertEqual(result.values[unbundle.id], {"a": "x", "b": 2})

    def test_waveform_create_and_stats(self):
        graph = Graph()
        t0, dt, samples = constant(graph, "numeric_constant", 0), constant(graph, "numeric_constant", 0.5), constant(graph, "array_constant", [1, 4, 2])
        wave, stats = graph.add_node("waveform_create"), graph.add_node("waveform_stats")
        for source, port in ((t0, "t0"), (dt, "dt"), (samples, "y")): graph.connect(source.id, "out", wave.id, port)
        graph.connect(wave.id, "out", stats.id, "waveform")
        result = DataflowRuntime().run(graph)
        self.assertIsInstance(result.values[wave.id], Waveform)
        self.assertEqual(result.values[stats.id]["mean"], 7 / 3)

    def test_boolean_and_string_nodes(self):
        graph = Graph()
        a, b = constant(graph, "boolean_constant", True), constant(graph, "boolean_constant", False)
        operation = graph.add_node("boolean_or")
        graph.connect(a.id, "out", operation.id, "a"); graph.connect(b.id, "out", operation.id, "b")
        self.assertTrue(DataflowRuntime().run(graph).values[operation.id])

    def test_case_and_sequence_have_executable_semantics(self):
        graph = Graph()
        selector = constant(graph, "boolean_constant", False)
        first, second = constant(graph, "string_constant", "first"), constant(graph, "string_constant", "second")
        case, sequence = graph.add_node("case"), graph.add_node("sequence")
        graph.connect(selector.id, "out", case.id, "selector")
        graph.connect(first.id, "out", case.id, "true"); graph.connect(second.id, "out", case.id, "false")
        graph.connect(first.id, "out", sequence.id, "first"); graph.connect(case.id, "out", sequence.id, "second")
        result = DataflowRuntime().run(graph)
        self.assertEqual(result.values[case.id], "second")
        self.assertEqual(result.values[sequence.id], "second")

    def test_bounded_loops_execute(self):
        graph = Graph()
        values = constant(graph, "array_constant", [-2, 3])
        loop = graph.add_node("for_loop"); loop.properties["operation"] = "abs"
        graph.connect(values.id, "out", loop.id, "array")
        result = DataflowRuntime().run(graph)
        self.assertEqual(result.values[loop.id], [2, 3])

    def test_while_loop_bound_reports_error(self):
        graph = Graph()
        initial = constant(graph, "numeric_constant", 0)
        loop = graph.add_node("while_loop"); loop.properties.update(max_iterations=2, limit=10, step=1)
        graph.connect(initial.id, "out", loop.id, "initial")
        self.assertTrue(DataflowRuntime().run(graph).errors)

    def test_independent_delays_run_in_parallel(self):
        graph = Graph()
        sources = [constant(graph, "numeric_constant", value) for value in (1, 2)]
        delays = [graph.add_node("delay") for _ in range(2)]
        for source, delay in zip(sources, delays):
            delay.properties["seconds"] = 0.08
            graph.connect(source.id, "out", delay.id, "value")
        started = time.monotonic(); result = DataflowRuntime(max_workers=2).run(graph); elapsed = time.monotonic() - started
        self.assertFalse(result.errors)
        self.assertLess(elapsed, 0.14)
        self.assertEqual(set(result.durations), set(graph.nodes))

    def test_file_io_is_confined_and_returns_error_cluster(self):
        with tempfile.TemporaryDirectory() as directory:
            graph = Graph(); text = constant(graph, "string_constant", "hello")
            write = graph.add_node("file_write"); write.properties["path"] = "out.txt"
            graph.connect(text.id, "out", write.id, "text")
            result = DataflowRuntime(data_root=directory).run(graph)
            self.assertFalse(result.values[write.id].status)
            self.assertEqual((Path(directory) / "out.txt").read_text(), "hello")
            write.properties["path"] = "../escape.txt"
            error = DataflowRuntime(data_root=directory).run(graph).values[write.id]
            self.assertIsInstance(error, ErrorCluster)
            self.assertTrue(error.status)

    def test_csv_logger_appends_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            graph = Graph(); value = constant(graph, "numeric_constant", 12)
            logger = graph.add_node("csv_logger"); logger.properties["path"] = "data.csv"
            graph.connect(value.id, "out", logger.id, "value")
            result = DataflowRuntime(data_root=directory).run(graph)
            self.assertFalse(result.values[logger.id].status)
            self.assertEqual((Path(directory) / "data.csv").read_text().strip(), "12")

    def test_error_handler_logs_explicit_cluster(self):
        graph = Graph(); error = graph.add_node("error_constant"); handler = graph.add_node("error_handler")
        error.properties.update(status=True, code=7, source="failed")
        graph.connect(error.id, "error", handler.id, "error")
        result = DataflowRuntime().run(graph)
        self.assertTrue(result.values[handler.id]["handled"])
        self.assertIn("ERROR 7", result.logs[0])


if __name__ == "__main__":
    unittest.main()
