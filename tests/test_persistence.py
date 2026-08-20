import tempfile
import unittest
from pathlib import Path

from pylabview.model import Graph
from pylabview.persistence import load_graph, load_project, save_graph, save_project
from pylabview.model import Project
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

    def test_v1_is_migrated_to_project_v2(self):
        legacy = {"format": "pylabview-project", "version": 1, "name": "Old", "nodes": [], "wires": []}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "old.json"
            import json
            path.write_text(json.dumps(legacy), encoding="utf-8")
            project = load_project(path)
        self.assertEqual(project.main.graph.name, "Old")
        self.assertEqual(project.to_dict()["version"], 2)

    def test_invalid_v2_schema_is_rejected(self):
        data = Project().to_dict()
        data["unexpected"] = True
        with self.assertRaises(ValueError):
            Project.from_dict(data)

    def test_malformed_nested_schemas_are_normalized_to_value_error(self):
        cases = []
        invalid_graph = Project().to_dict()
        invalid_graph["vis"][0]["graph"] = None
        cases.append(invalid_graph)
        invalid_connectors = Project().to_dict()
        invalid_connectors["vis"][0]["connector_pane"]["inputs"] = "invalid"
        cases.append(invalid_connectors)
        invalid_terminal = Project().to_dict()
        invalid_terminal["vis"][0]["connector_pane"]["inputs"] = [{"name": "x"}]
        cases.append(invalid_terminal)
        invalid_vi_id = Project().to_dict()
        invalid_vi_id["vis"][0]["id"] = []
        cases.append(invalid_vi_id)
        for data in cases:
            with self.subTest(data=data), self.assertRaises(ValueError):
                Project.from_dict(data)

    def test_atomic_save_leaves_no_temporary_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "project.json"
            save_project(Project(), path)
            self.assertEqual([item.name for item in Path(directory).iterdir()], ["project.json"])

    def test_invalid_numeric_value_does_not_leave_partial_save(self):
        project = Project()
        node = project.main.graph.add_node("numeric_constant")
        node.properties["value"] = float("nan")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "project.json"
            with self.assertRaises(ValueError):
                save_project(project, path)
            self.assertEqual(list(Path(directory).iterdir()), [])


if __name__ == "__main__":
    unittest.main()
