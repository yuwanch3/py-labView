from __future__ import annotations

import sys
import unittest
from types import ModuleType, SimpleNamespace


def _ensure_headless_tkinter() -> None:
    try:
        import tkinter as tkinter_module
    except ImportError:
        sys.modules.pop("tkinter", None)
        tkinter_module = ModuleType("tkinter")
        sys.modules["tkinter"] = tkinter_module

    for name in ("Canvas", "Tk", "Misc", "Event", "PhotoImage"):
        if not hasattr(tkinter_module, name):
            setattr(tkinter_module, name, object)
    if not hasattr(tkinter_module, "TclError"):
        tkinter_module.TclError = RuntimeError

    for name in ("filedialog", "messagebox", "simpledialog", "ttk"):
        qualified = f"tkinter.{name}"
        module = sys.modules.get(qualified, ModuleType(qualified))
        if name == "messagebox" and not hasattr(module, "showerror"):
            module.showerror = lambda *_args, **_kwargs: None
        if name == "simpledialog" and not hasattr(module, "askstring"):
            module.askstring = lambda *_args, **_kwargs: None
        setattr(tkinter_module, name, module)
        sys.modules[qualified] = module


_ensure_headless_tkinter()

from pylabview.app import StudioApp
from pylabview.execution import RunController
from pylabview.front_panel import PanelDesigner
from pylabview.model import Project, _normalized_panel
from pylabview.runtime import DataflowRuntime


class _Variable:
    def __init__(self, value: str) -> None:
        self.value = value

    def get(self) -> str:
        return self.value


class _HeadlessPanel:
    def __init__(self, graph, panel) -> None:
        self.graph = graph
        self.panel = _normalized_panel(panel, graph)
        self.values: dict[str, object] = {}
        PanelDesigner._initialize_values(self)

    def set_document(self, graph, panel) -> None:
        if graph is not self.graph:
            self.values.clear()
        self.graph = graph
        self.panel = _normalized_panel(panel, graph)
        PanelDesigner._initialize_values(self)

    def control_values(self) -> dict[str, object]:
        return PanelDesigner.control_values(self)

    def sync_control_value_from_model(self, node_id: str, value: object) -> bool:
        return PanelDesigner.sync_control_value_from_model(self, node_id, value)


class PropertyApplyRuntimeTests(unittest.TestCase):
    def test_properties_apply_value_reaches_run_once_without_save(self) -> None:
        project = Project()
        node = project.main.graph.add_node("string_constant")
        node.label = "Camera Mode"
        node.properties.update(value="usb", display_type="string")
        project.main.front_panel = _normalized_panel(project.main.front_panel, project.main.graph)
        panel = _HeadlessPanel(project.main.graph, project.main.front_panel)
        self.assertEqual(panel.values[node.id], "usb", "precondition: Front Panel cached the disk value")

        canvas = SimpleNamespace(statuses={}, redraw=lambda: None)
        status = SimpleNamespace(set=lambda _message: None)
        app = SimpleNamespace(
            project=project,
            graph=project.main.graph,
            current_vi_id=project.main_vi,
            current_diagram_id=None,
            front_panel=panel,
            canvas=canvas,
            controller=RunController(DataflowRuntime()),
            property_vars={
                "label": _Variable("Camera Mode"),
                "value": _Variable("network"),
                "display_type": _Variable("string"),
            },
            breakpoints=set(),
            probes=set(),
            dirty=False,
            status_var=status,
            checkpoint=lambda: None,
            _update_title=lambda: None,
        )
        app.changed = lambda: StudioApp.changed(app)

        StudioApp.apply_properties(app, node.id)
        self.assertEqual(node.properties["value"], "network",
                         "Apply must mutate the live graph model before execution")

        StudioApp.run_once(app)
        self.assertTrue(app.controller.join(2.0), "Run Once did not finish")
        self.assertIsNotNone(app.controller.last_result)
        self.assertEqual(app.controller.last_result.values[node.id], "network",
                         "Run Once used a stale Front Panel override instead of the applied property")


if __name__ == "__main__":
    unittest.main()
