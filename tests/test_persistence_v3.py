import copy
import json
import tempfile
import unittest
from pathlib import Path

from pylabview.model import Graph, Project
from pylabview.persistence import load_project, save_project


class PersistenceV3Tests(unittest.TestCase):
    def test_new_project_serializes_as_v3(self):
        data = Project().to_dict()
        self.assertEqual(data["version"], 3); self.assertIn("extensions", data)

    def test_v3_round_trip_preserves_extensions(self):
        project = Project(); project.extensions["vendor.example"] = {"enabled": True}
        self.assertEqual(Project.from_dict(project.to_dict()).extensions, project.extensions)

    def test_unknown_core_root_field_is_rejected(self):
        data = Project().to_dict(); data["typo"] = 1
        with self.assertRaises(ValueError): Project.from_dict(data)

    def test_unknown_vi_field_is_rejected(self):
        data = Project().to_dict(); data["vis"][0]["typo"] = 1
        with self.assertRaises(ValueError): Project.from_dict(data)

    def test_panel_bounds_are_persisted(self):
        project = Project(); node = project.main.graph.add_node("numeric_constant")
        panel = project.to_dict()["vis"][0]["front_panel"]; panel["items"][0]["bounds"]["x"] = 330
        data = project.to_dict(); data["vis"][0]["front_panel"] = panel
        self.assertEqual(Project.from_dict(data).main.front_panel["items"][0]["bounds"]["x"], 330)

    def test_subdiagram_round_trip(self):
        project = Project(); child = Graph("Body"); child.add_node("iteration_terminal")
        project.main.subdiagrams["body"] = child
        restored = Project.from_dict(project.to_dict())
        self.assertIn("body", restored.main.subdiagrams); self.assertEqual(restored.main.subdiagrams["body"].name, "Body")

    def test_v2_load_has_migration_report_and_v3_save(self):
        current = Project().to_dict(); vi = current["vis"][0]
        legacy = {key: current[key] for key in ("format", "name", "main_vi", "vis")}; legacy["version"] = 2
        legacy["vis"] = [{key: vi[key] for key in ("id", "name", "graph", "connector_pane") } | {"front_panel": {"title": "Old", "layout": {}}}]
        with tempfile.TemporaryDirectory() as directory:
            source, destination = Path(directory) / "v2.json", Path(directory) / "v3.json"
            source.write_text(json.dumps(legacy), encoding="utf-8"); project = load_project(source); save_project(project, destination)
            saved = json.loads(destination.read_text(encoding="utf-8"))
        self.assertTrue(project.migration_report); self.assertEqual(saved["version"], 3)

    def test_invalid_panel_reference_is_rejected(self):
        project = Project(); project.main.graph.add_node("numeric_constant"); data = project.to_dict()
        data["vis"][0]["front_panel"]["items"][0]["terminal_node_id"] = "missing"
        with self.assertRaises(ValueError): Project.from_dict(data)


if __name__ == "__main__": unittest.main()
