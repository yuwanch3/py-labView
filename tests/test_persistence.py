import tempfile
import unittest
from pathlib import Path

from pylabview.model import Graph
from pylabview.persistence import load_graph, save_graph
from pylabview.runtime import DataflowRuntime


class PersistenceTests(unittest.TestCase):
    def test_save_and_load(self):
        graph = Graph("Round Trip")
        graph.add_node("random", 10, 20)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "project.json"
            save_graph(graph, path)
            loaded = load_graph(path)
        self.assertEqual(graph.to_dict(), loaded.to_dict())

    def test_example_project_is_valid_and_executable(self):
        path = Path(__file__).parents[1] / "examples" / "simulated_monitor.json"
        graph = load_graph(path)
        self.assertEqual(len(graph.nodes), 4)
        self.assertEqual(len(graph.wires), 3)
        result = DataflowRuntime().run(graph)
        self.assertFalse(result.errors)
        self.assertEqual(len(result.logs), 1)


if __name__ == "__main__":
    unittest.main()
