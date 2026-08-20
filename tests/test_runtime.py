import math
import random
import unittest

from pylabview.model import Graph
from pylabview.runtime import DataflowRuntime, DataflowError


class RuntimeTests(unittest.TestCase):
    def test_arithmetic_dataflow(self):
        graph = Graph()
        a = graph.add_node("numeric_constant")
        b = graph.add_node("numeric_constant")
        add = graph.add_node("add")
        sine = graph.add_node("sine")
        a.properties["value"] = 2
        b.properties["value"] = 3
        graph.connect(a.id, "out", add.id, "a")
        graph.connect(b.id, "out", add.id, "b")
        graph.connect(add.id, "out", sine.id, "x")
        result = DataflowRuntime().run(graph)
        self.assertFalse(result.errors)
        self.assertAlmostEqual(result.values[sine.id], math.sin(5))

    def test_missing_input(self):
        graph = Graph()
        graph.add_node("add")
        result = DataflowRuntime().run(graph)
        self.assertEqual(len(result.errors), 2)
        self.assertIn("missing input", result.errors[0])

    def test_cycle_detection(self):
        graph = Graph()
        one = graph.add_node("add")
        two = graph.add_node("add")
        graph.connect(one.id, "out", two.id, "a")
        graph.connect(two.id, "out", one.id, "a")
        with self.assertRaises(DataflowError):
            DataflowRuntime().topological_order(graph)

    def test_divide_by_zero_marks_error(self):
        graph = Graph()
        a = graph.add_node("numeric_constant")
        b = graph.add_node("numeric_constant")
        divide = graph.add_node("divide")
        graph.connect(a.id, "out", divide.id, "a")
        graph.connect(b.id, "out", divide.id, "b")
        result = DataflowRuntime().run(graph)
        self.assertEqual(result.statuses[divide.id], "error")
        self.assertIn("division by zero", result.errors[0])

    def test_deterministic_analog_range(self):
        graph = Graph()
        analog = graph.add_node("analog_input")
        analog.properties.update(minimum=2, maximum=3)
        result = DataflowRuntime(rng=random.Random(1)).run(graph)
        self.assertGreaterEqual(result.values[analog.id], 2)
        self.assertLessEqual(result.values[analog.id], 3)

    def test_daq_reconfigures_when_channel_config_changes(self):
        graph = Graph()
        analog = graph.add_node("analog_input")
        runtime = DataflowRuntime(rng=random.Random(1))
        analog.properties.update(minimum=2, maximum=3)
        self.assertTrue(2 <= runtime.run(graph).values[analog.id] <= 3)
        analog.properties.update(minimum=100, maximum=101)
        self.assertTrue(100 <= runtime.run(graph).values[analog.id] <= 101)

    def test_sink_values_are_retained_for_front_panel(self):
        graph = Graph()
        source = graph.add_node("numeric_constant")
        display = graph.add_node("display")
        chart = graph.add_node("chart")
        source.properties["value"] = 42
        graph.connect(source.id, "out", display.id, "value")
        graph.connect(source.id, "out", chart.id, "value")
        result = DataflowRuntime().run(graph)
        self.assertEqual(result.values[display.id], 42)
        self.assertEqual(result.values[chart.id], 42)

    def test_result_values_use_normalized_port_values(self):
        graph = Graph()
        source = graph.add_node("numeric_constant")
        source.properties["value"] = "3"
        result = DataflowRuntime().run(graph)
        self.assertEqual(result.values[source.id], 3.0)
        self.assertEqual(result.values[source.id], result.port_values[(source.id, "out")])

    def test_failed_node_blocks_all_transitive_dependents(self):
        graph = Graph()
        numerator = graph.add_node("numeric_constant")
        denominator = graph.add_node("numeric_constant")
        divide = graph.add_node("divide")
        absolute = graph.add_node("absolute")
        display = graph.add_node("display")
        numerator.properties["value"] = 1
        denominator.properties["value"] = 0
        graph.connect(numerator.id, "out", divide.id, "a")
        graph.connect(denominator.id, "out", divide.id, "b")
        graph.connect(divide.id, "out", absolute.id, "x")
        graph.connect(absolute.id, "out", display.id, "value")
        result = DataflowRuntime().run(graph)
        self.assertEqual(result.statuses[divide.id], "error")
        self.assertEqual(result.statuses[absolute.id], "blocked")
        self.assertEqual(result.statuses[display.id], "blocked")


if __name__ == "__main__":
    unittest.main()
