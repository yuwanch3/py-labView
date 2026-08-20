import unittest

from pylabview.model import ConnectorTerminal, Project, project_snapshot, restore_project_snapshot
from pylabview.runtime import DataflowRuntime


def subvi_project():
    project = Project("SubVI Test")
    main = project.main
    child = project.add_vi("Adder")
    incoming = child.graph.add_node("numeric_constant")
    fixed = child.graph.add_node("numeric_constant")
    fixed.properties["value"] = 3
    add = child.graph.add_node("add")
    child.graph.connect(incoming.id, "out", add.id, "a")
    child.graph.connect(fixed.id, "out", add.id, "b")
    child.connector_inputs = [ConnectorTerminal("value", incoming.id, "out", "numeric")]
    child.connector_outputs = [ConnectorTerminal("result", add.id, "out", "numeric")]
    source = main.graph.add_node("numeric_constant")
    source.properties["value"] = 4
    call = main.graph.add_node("subvi")
    call.properties["vi_id"] = child.id
    main.graph.connect(source.id, "out", call.id, "value")
    return project, child, call


class ProjectTests(unittest.TestCase):
    def test_add_rename_and_set_main(self):
        project = Project()
        vi = project.add_vi("Worker")
        project.rename_vi(vi.id, "Worker 2")
        project.set_main(vi.id)
        self.assertEqual(project.main.name, "Worker 2")

    def test_duplicate_vi_name_rejected(self):
        project = Project()
        project.add_vi("Worker")
        with self.assertRaises(ValueError):
            project.add_vi("Worker")

    def test_main_vi_cannot_be_deleted(self):
        project = Project()
        with self.assertRaises(ValueError):
            project.delete_vi(project.main_vi)

    def test_referenced_vi_cannot_be_deleted(self):
        project, child, _call = subvi_project()
        with self.assertRaises(ValueError):
            project.delete_vi(child.id)

    def test_subvi_executes_dynamic_connectors(self):
        project, _child, call = subvi_project()
        result = DataflowRuntime().run_project(project)
        self.assertFalse(result.errors)
        self.assertEqual(result.values[call.id], 7)
        self.assertEqual(result.port_values[(call.id, "result")], 7)

    def test_project_round_trip_with_subvi_wires(self):
        project, _child, _call = subvi_project()
        restored = Project.from_dict(project.to_dict())
        self.assertEqual(restored.to_dict(), project.to_dict())
        self.assertFalse(DataflowRuntime().run_project(restored).errors)

    def test_recursive_subvi_is_rejected(self):
        project = Project()
        other = project.add_vi("Other")
        first = project.main.graph.add_node("subvi")
        second = other.graph.add_node("subvi")
        first.properties["vi_id"] = other.id
        second.properties["vi_id"] = project.main_vi
        errors = DataflowRuntime().validate(project.main.graph, project, project.main_vi)
        self.assertTrue(any("recursion" in error for error in errors))

    def test_stale_dynamic_subvi_wire_is_reported(self):
        project, child, _call = subvi_project()
        child.connector_inputs = []
        errors = DataflowRuntime().validate(project.main.graph, project, project.main_vi)
        self.assertTrue(any("Invalid wire" in error for error in errors))

    def test_connector_input_must_reference_control_output(self):
        project = Project()
        add = project.main.graph.add_node("add")
        project.main.connector_inputs = [ConnectorTerminal("value", add.id, "out", "numeric")]
        with self.assertRaises(ValueError):
            project.validate_connectors()

    def test_connector_inputs_must_reference_unique_endpoints(self):
        project = Project()
        control = project.main.graph.add_node("numeric_constant")
        project.main.connector_inputs = [
            ConnectorTerminal("first", control.id, "out", "numeric"),
            ConnectorTerminal("second", control.id, "out", "numeric"),
        ]
        with self.assertRaises(ValueError):
            project.validate_connectors()

    def test_project_snapshot_restores_cross_vi_state_and_selection(self):
        project, child, _call = subvi_project()
        snapshot = project_snapshot(project, child.id)
        project.rename_vi(child.id, "Changed")
        project.set_main(child.id)
        project.main.connector_outputs.clear()
        for vi in project.vis.values():
            vi.graph.wires.clear()
        restored, current_vi_id = restore_project_snapshot(snapshot)
        self.assertEqual(current_vi_id, child.id)
        self.assertEqual(restored.to_dict(), snapshot["project"])
        self.assertNotEqual(restored.main_vi, child.id)


if __name__ == "__main__":
    unittest.main()
