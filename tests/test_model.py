import unittest

from pylabview.model import Graph


class GraphTests(unittest.TestCase):
    def test_connect_replaces_existing_input_and_round_trips(self):
        graph = Graph("Test")
        first = graph.add_node("numeric_constant")
        second = graph.add_node("numeric_constant")
        add = graph.add_node("add")
        graph.connect(first.id, "out", add.id, "a")
        graph.connect(second.id, "out", add.id, "a")
        self.assertEqual(len(graph.wires), 1)
        restored = Graph.from_dict(graph.to_dict())
        self.assertEqual(restored.to_dict(), graph.to_dict())

    def test_remove_node_removes_wires(self):
        graph = Graph()
        source = graph.add_node("numeric_constant")
        display = graph.add_node("display")
        graph.connect(source.id, "out", display.id, "value")
        graph.remove_node(source.id)
        self.assertEqual(graph.wires, [])

    def test_invalid_port_is_rejected(self):
        graph = Graph()
        source = graph.add_node("numeric_constant")
        display = graph.add_node("display")
        with self.assertRaises(ValueError):
            graph.connect(source.id, "bad", display.id, "value")


if __name__ == "__main__":
    unittest.main()
