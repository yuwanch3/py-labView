from __future__ import annotations

import copy
import json
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk
from typing import Any

from . import __version__
from .canvas_editor import DiagramCanvas
from .front_panel import FrontPanel
from .model import (ConnectorTerminal, Graph, NODE_DEFINITIONS, Node, Project,
                    project_snapshot, restore_project_snapshot)
from .persistence import load_project, save_project
from .typesystem import DATA_TYPES, compatible, editor_value_text
from .runtime import DataflowRuntime


class StudioApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("PyLabView Studio")
        self.geometry("1240x780")
        self.minsize(900, 600)
        self.project = Project()
        self.current_vi_id = self.project.main_vi
        self.graph = self.project.main.graph
        self.path: Path | None = None
        self.dirty = False
        self.undo_stack: list[dict[str, Any]] = []
        self.redo_stack: list[dict[str, Any]] = []
        self.clipboard_node: dict[str, Any] | None = None
        self.runtime = DataflowRuntime()
        self.continuous = False
        self.after_job: str | None = None
        self.front_panel: FrontPanel | None = None
        self.property_vars: dict[str, tk.StringVar] = {}
        self._build_style()
        self._build_menu()
        self._build_ui()
        self._bind_shortcuts()
        self.protocol("WM_DELETE_WINDOW", self.close_app)
        self._update_title()

    def _build_style(self) -> None:
        style = ttk.Style(self)
        if "clam" in style.theme_names():
            style.theme_use("clam")
        style.configure("Toolbar.TFrame", background="#273244")
        style.configure("Run.TButton", font=("TkDefaultFont", 10, "bold"))

    def _build_menu(self) -> None:
        menu = tk.Menu(self)
        file_menu = tk.Menu(menu, tearoff=False)
        file_menu.add_command(label="New", accelerator="Ctrl+N", command=self.new_project)
        file_menu.add_command(label="Open...", accelerator="Ctrl+O", command=self.open_project)
        file_menu.add_separator()
        file_menu.add_command(label="Save", accelerator="Ctrl+S", command=self.save_project)
        file_menu.add_command(label="Save As...", accelerator="Ctrl+Shift+S", command=self.save_project_as)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.close_app)
        menu.add_cascade(label="File", menu=file_menu)
        edit_menu = tk.Menu(menu, tearoff=False)
        edit_menu.add_command(label="Undo", accelerator="Ctrl+Z", command=self.undo)
        edit_menu.add_command(label="Redo", accelerator="Ctrl+Y", command=self.redo)
        edit_menu.add_separator()
        edit_menu.add_command(label="Copy Node", accelerator="Ctrl+C", command=self.copy_node)
        edit_menu.add_command(label="Paste Node", accelerator="Ctrl+V", command=self.paste_node)
        edit_menu.add_command(label="Delete", accelerator="Del", command=lambda: self.canvas.delete_selection())
        menu.add_cascade(label="Edit", menu=edit_menu)
        run_menu = tk.Menu(menu, tearoff=False)
        run_menu.add_command(label="Run Once", accelerator="F5", command=self.run_once)
        run_menu.add_command(label="Run Continuously", accelerator="F6", command=self.toggle_continuous)
        run_menu.add_command(label="Stop", accelerator="Shift+F6", command=self.stop)
        menu.add_cascade(label="Run", menu=run_menu)
        view_menu = tk.Menu(menu, tearoff=False)
        view_menu.add_command(label="Front Panel", accelerator="Ctrl+F", command=self.show_front_panel)
        menu.add_cascade(label="View", menu=view_menu)
        help_menu = tk.Menu(menu, tearoff=False)
        help_menu.add_command(label="Quick Help", command=self.show_help)
        help_menu.add_command(label="About", command=self.show_about)
        menu.add_cascade(label="Help", menu=help_menu)
        self.configure(menu=menu)

    def _build_ui(self) -> None:
        toolbar = ttk.Frame(self, style="Toolbar.TFrame", padding=6)
        toolbar.pack(fill="x")
        ttk.Button(toolbar, text="New", command=self.new_project).pack(side="left", padx=2)
        ttk.Button(toolbar, text="Open", command=self.open_project).pack(side="left", padx=2)
        ttk.Button(toolbar, text="Save", command=self.save_project).pack(side="left", padx=2)
        ttk.Separator(toolbar, orient="vertical").pack(side="left", fill="y", padx=8)
        ttk.Button(toolbar, text="Run Once", style="Run.TButton", command=self.run_once).pack(side="left", padx=2)
        self.run_button = ttk.Button(toolbar, text="Continuous", command=self.toggle_continuous)
        self.run_button.pack(side="left", padx=2)
        ttk.Button(toolbar, text="Stop", command=self.stop).pack(side="left", padx=2)
        ttk.Button(toolbar, text="Front Panel", command=self.show_front_panel).pack(side="left", padx=10)
        ttk.Button(toolbar, text="Validate", command=self.validate_current).pack(side="left", padx=2)
        ttk.Button(toolbar, text="Connector", command=self.configure_connector).pack(side="left", padx=2)
        ttk.Button(toolbar, text="Create SubVI", command=self.create_subvi).pack(side="left", padx=2)
        self.zoom_label = ttk.Label(toolbar, text="Ctrl+wheel: zoom")
        self.zoom_label.pack(side="right", padx=8)

        vertical = ttk.Panedwindow(self, orient="vertical")
        vertical.pack(fill="both", expand=True)
        work = ttk.Panedwindow(vertical, orient="horizontal")
        vertical.add(work, weight=5)
        console_frame = ttk.LabelFrame(vertical, text="Execution Log", padding=4)
        vertical.add(console_frame, weight=1)

        library = ttk.LabelFrame(work, text="Node Library", padding=6)
        center = ttk.Frame(work)
        inspector = ttk.LabelFrame(work, text="Properties", padding=8)
        work.add(library, weight=1)
        work.add(center, weight=5)
        work.add(inspector, weight=1)

        ttk.Label(library, text="VI Explorer", font=("TkDefaultFont", 10, "bold")).pack(anchor="w")
        self.vi_list = tk.Listbox(library, height=5, exportselection=False)
        self.vi_list.pack(fill="x", pady=(3, 2))
        self.vi_list.bind("<<ListboxSelect>>", self._switch_vi_event)
        vi_buttons = ttk.Frame(library)
        vi_buttons.pack(fill="x", pady=(0, 8))
        ttk.Button(vi_buttons, text="+", width=3, command=self.add_vi).pack(side="left")
        ttk.Button(vi_buttons, text="Rename", command=self.rename_vi).pack(side="left", padx=2)
        ttk.Button(vi_buttons, text="Delete", command=self.delete_vi).pack(side="left")
        ttk.Button(vi_buttons, text="Main", command=self.set_main_vi).pack(side="left", padx=2)
        ttk.Label(library, text="Node Search", font=("TkDefaultFont", 10, "bold")).pack(anchor="w")
        self.search_var = tk.StringVar()
        search = ttk.Entry(library, textvariable=self.search_var)
        search.pack(fill="x", pady=(3, 4))
        self.search_var.trace_add("write", lambda *_args: self._populate_library())
        self.library_tree = ttk.Treeview(library, show="tree", selectmode="browse")
        self.library_tree.pack(fill="both", expand=True)
        self._populate_library()
        self._refresh_vi_list()
        self.library_tree.bind("<Double-1>", self._library_add)
        ttk.Label(library, text="Double-click to add", foreground="#58677a").pack(pady=(5, 0))

        self.canvas = DiagramCanvas(center, self.graph, self.select_node, self.checkpoint, self.changed, self._connection_error)
        self.canvas.pack(fill="both", expand=True)

        self.inspector_body = ttk.Frame(inspector)
        self.inspector_body.pack(fill="both", expand=True)
        self.select_node(None)

        self.console = tk.Text(console_frame, height=7, background="#10151d", foreground="#d7e1ef", insertbackground="white", font=("TkFixedFont", 9), state="disabled")
        scroll = ttk.Scrollbar(console_frame, command=self.console.yview)
        self.console.configure(yscrollcommand=scroll.set)
        self.console.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.status_var = tk.StringVar(value="Ready")
        ttk.Label(self, textvariable=self.status_var, anchor="w", padding=(7, 3)).pack(fill="x")

    def _populate_library(self) -> None:
        if not hasattr(self, "library_tree"):
            return
        self.library_tree.delete(*self.library_tree.get_children())
        query = self.search_var.get().strip().lower() if hasattr(self, "search_var") else ""
        categories: dict[str, str] = {}
        for node_type, definition in NODE_DEFINITIONS.items():
            if node_type == "subvi" or (query and query not in f"{definition.title} {definition.category} {node_type}".lower()):
                continue
            parent = categories.setdefault(definition.category, self.library_tree.insert("", "end", text=definition.category, open=True))
            self.library_tree.insert(parent, "end", iid=f"type:{node_type}", text=definition.title)

    def _connection_error(self, message: str) -> None:
        self.status_var.set(message)
        self.log("WIRE ERROR " + message)

    def _bind_shortcuts(self) -> None:
        self.bind_all("<Control-n>", lambda _e: self.new_project())
        self.bind_all("<Control-o>", lambda _e: self.open_project())
        self.bind_all("<Control-s>", lambda _e: self.save_project())
        self.bind_all("<Control-Shift-S>", lambda _e: self.save_project_as())
        self.bind_all("<Control-z>", lambda _e: self.undo())
        self.bind_all("<Control-y>", lambda _e: self.redo())
        self.bind_all("<Control-c>", lambda _e: self.copy_node())
        self.bind_all("<Control-v>", lambda _e: self.paste_node())
        self.bind_all("<Control-f>", lambda _e: self.show_front_panel())
        self.bind_all("<F5>", lambda _e: self.run_once())
        self.bind_all("<F6>", lambda _e: self.toggle_continuous())
        self.bind_all("<Shift-F6>", lambda _e: self.stop())

    def _library_add(self, _event: tk.Event) -> None:
        item = self.library_tree.focus()
        if not item.startswith("type:"):
            return
        node_type = item.split(":", 1)[1]
        self.checkpoint()
        offset = len(self.graph.nodes) % 8
        node = self.graph.add_node(node_type, 80 + offset * 22, 70 + offset * 22)
        self.canvas.selected_node = node.id
        self.changed()
        self.select_node(node.id)
        self.canvas.redraw()

    def checkpoint(self) -> None:
        self.undo_stack.append(project_snapshot(self.project, self.current_vi_id))
        del self.undo_stack[:-100]
        self.redo_stack.clear()

    def changed(self) -> None:
        self.dirty = True
        self.canvas.statuses = {}
        self._update_title()
        if self.front_panel:
            self.front_panel.rebuild(self.graph)

    def undo(self) -> None:
        if not self.undo_stack:
            return
        self.redo_stack.append(project_snapshot(self.project, self.current_vi_id))
        self._restore_snapshot(self.undo_stack.pop())
        self.dirty = True
        self._update_title()

    def redo(self) -> None:
        if not self.redo_stack:
            return
        self.undo_stack.append(project_snapshot(self.project, self.current_vi_id))
        self._restore_snapshot(self.redo_stack.pop())
        self.dirty = True
        self._update_title()

    def _restore_snapshot(self, snapshot: dict[str, Any]) -> None:
        self.project, self.current_vi_id = restore_project_snapshot(snapshot)
        self._replace_graph(self.project.vis[self.current_vi_id].graph)
        self._refresh_vi_list()

    def copy_node(self) -> None:
        node_id = self.canvas.selected_node
        if not node_id:
            return
        node = self.graph.nodes[node_id]
        self.clipboard_node = {
            "type": node.type, "label": node.label, "properties": copy.deepcopy(node.properties), "x": node.x, "y": node.y
        }
        self.status_var.set(f"Copied node: {node.label}")

    def paste_node(self) -> None:
        if not self.clipboard_node:
            return
        self.checkpoint()
        data = self.clipboard_node
        node = self.graph.add_node(data["type"], data["x"] + 30, data["y"] + 30)
        node.label = data["label"] + " Copy"
        node.properties = copy.deepcopy(data["properties"])
        self.clipboard_node["x"], self.clipboard_node["y"] = node.x, node.y
        self.canvas.selected_node = node.id
        self.changed()
        self.select_node(node.id)
        self.canvas.redraw()

    def select_node(self, node_id: str | None) -> None:
        for child in self.inspector_body.winfo_children():
            child.destroy()
        self.property_vars.clear()
        if not node_id or node_id not in self.graph.nodes:
            ttk.Label(self.inspector_body, text="Select a node to edit its label and configuration.", wraplength=180).pack(anchor="w")
            return
        node = self.graph.nodes[node_id]
        ttk.Label(self.inspector_body, text=NODE_DEFINITIONS[node.type].title, font=("TkDefaultFont", 11, "bold")).pack(anchor="w", pady=(0, 8))
        fields = {"label": node.label, **node.properties}
        for key, value in fields.items():
            ttk.Label(self.inspector_body, text=key.replace("_", " ").title()).pack(anchor="w", pady=(5, 1))
            var = tk.StringVar(value=editor_value_text(value))
            entry = (ttk.Combobox(self.inspector_body, textvariable=var, state="readonly",
                                  values=("auto", "numeric", "string", "boolean", "array", "led", "gauge", "progress", "thermometer", "waveform_chart"))
                     if key == "display_type" else ttk.Entry(self.inspector_body, textvariable=var))
            entry.pack(fill="x")
            entry.bind("<Return>", lambda _e, nid=node_id: self.apply_properties(nid))
            self.property_vars[key] = var
        ttk.Button(self.inspector_body, text="Apply", command=lambda: self.apply_properties(node_id)).pack(fill="x", pady=12)

    def apply_properties(self, node_id: str) -> None:
        if node_id not in self.graph.nodes:
            return
        node = self.graph.nodes[node_id]
        new_label = self.property_vars["label"].get().strip()
        if not new_label:
            messagebox.showerror("Invalid property", "Label cannot be empty.", parent=self)
            return
        parsed: dict[str, Any] = {}
        try:
            for key, variable in self.property_vars.items():
                if key == "label":
                    continue
                old = node.properties.get(key)
                raw = variable.get()
                if isinstance(old, bool):
                    if raw.lower() not in ("true", "false"):
                        raise ValueError(f"{key} must be true or false")
                    parsed[key] = raw.lower() == "true"
                elif isinstance(old, int):
                    parsed[key] = int(raw)
                elif isinstance(old, float):
                    parsed[key] = float(raw)
                elif isinstance(old, (list, dict)):
                    value = json.loads(raw)
                    if not isinstance(value, type(old)):
                        raise ValueError(f"{key} must be a JSON {type(old).__name__}")
                    parsed[key] = value
                else:
                    parsed[key] = raw
        except ValueError as exc:
            messagebox.showerror("Invalid property", str(exc), parent=self)
            return
        self.checkpoint()
        node.label = new_label
        node.properties.update(parsed)
        self.changed()
        self.canvas.redraw()
        self.status_var.set(f"Updated {node.label}")

    def run_once(self, schedule_next: bool = False) -> None:
        controls = self.front_panel.control_values() if self.front_panel else {}
        result = self.runtime.run(self.graph, controls, self.project, self.current_vi_id)
        self.canvas.set_statuses(result.statuses)
        if self.front_panel:
            self.front_panel.update_values(result.values)
        for line in result.logs:
            self.log("LOG " + line)
        for error in result.errors:
            self.log("ERROR " + error)
        if result.errors:
            self.status_var.set(f"Execution failed: {len(result.errors)} error(s)")
        else:
            self.status_var.set(f"Executed {len(result.values)} node(s) successfully")
        if schedule_next and self.continuous:
            self.after_job = self.after(150, self._continuous_step)

    def _continuous_step(self) -> None:
        self.after_job = None
        if self.continuous:
            self.run_once(True)

    def toggle_continuous(self) -> None:
        if self.continuous:
            self.stop()
            return
        self.continuous = True
        self.runtime.reset()
        self.run_button.configure(text="Stop Continuous")
        self.status_var.set("Continuous execution started")
        self.run_once(True)

    def stop(self) -> None:
        self.continuous = False
        if self.after_job is not None:
            self.after_cancel(self.after_job)
            self.after_job = None
        self.run_button.configure(text="Continuous")
        self.status_var.set("Execution stopped")

    def show_front_panel(self) -> None:
        if not self.front_panel or not self.front_panel.winfo_exists():
            self.front_panel = FrontPanel(self, self.graph)
        else:
            self.front_panel.rebuild(self.graph)
            self.front_panel.deiconify()
            self.front_panel.lift()

    def new_project(self) -> None:
        if not self._confirm_discard():
            return
        self.stop()
        self.path = None
        self.undo_stack.clear()
        self.redo_stack.clear()
        self.project = Project()
        self.current_vi_id = self.project.main_vi
        self._replace_graph(self.project.main.graph)
        self._refresh_vi_list()
        self.dirty = False
        self._update_title()
        self.log("New project created")

    def open_project(self) -> None:
        if not self._confirm_discard():
            return
        path = filedialog.askopenfilename(parent=self, title="Open Project", filetypes=(("PyLabView Project", "*.json"), ("JSON", "*.json"), ("All Files", "*.*")))
        if not path:
            return
        try:
            project = load_project(path)
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            messagebox.showerror("Open failed", str(exc), parent=self)
            return
        self.stop()
        self.path = Path(path)
        self.undo_stack.clear()
        self.redo_stack.clear()
        self.project = project
        self.current_vi_id = project.main_vi
        self._replace_graph(project.main.graph)
        self._refresh_vi_list()
        self.dirty = False
        self._update_title()
        self.log(f"Opened {path}")

    def save_project(self) -> bool:
        if self.path is None:
            return self.save_project_as()
        try:
            save_project(self.project, self.path)
        except (OSError, ValueError, TypeError) as exc:
            messagebox.showerror("Save failed", str(exc), parent=self)
            return False
        self.dirty = False
        self._update_title()
        self.status_var.set(f"Saved {self.path}")
        return True

    def save_project_as(self) -> bool:
        path = filedialog.asksaveasfilename(parent=self, title="Save Project", defaultextension=".json", initialfile=(self.path.name if self.path else "project.json"), filetypes=(("PyLabView Project", "*.json"), ("All Files", "*.*")))
        if not path:
            return False
        destination = Path(path)
        try:
            candidate = Project.from_dict(self.project.to_dict())
            candidate.name = destination.stem
            save_project(candidate, destination)
        except (OSError, ValueError, TypeError) as exc:
            messagebox.showerror("Save failed", str(exc), parent=self)
            return False
        self.path = destination
        self.project.name = destination.stem
        self.dirty = False
        self._update_title()
        self.status_var.set(f"Saved {self.path}")
        return True

    def _replace_graph(self, graph: Graph) -> None:
        self.graph = graph
        if self.current_vi_id in self.project.vis:
            self.project.vis[self.current_vi_id].graph = graph
            graph.project = self.project
        self.canvas.set_graph(graph)
        self.select_node(None)
        if self.front_panel:
            self.front_panel.rebuild(graph)

    def _confirm_discard(self) -> bool:
        if not self.dirty:
            return True
        answer = messagebox.askyesnocancel("Unsaved changes", "Save changes before continuing?", parent=self)
        if answer is None:
            return False
        return self.save_project() if answer else True

    def close_app(self) -> None:
        if self._confirm_discard():
            self.destroy()

    def _update_title(self) -> None:
        name = self.path.name if self.path else self.project.name
        self.title(f"{'*' if self.dirty else ''}{name} [{self.project.vis[self.current_vi_id].name}] - PyLabView Studio")

    def _refresh_vi_list(self) -> None:
        if not hasattr(self, "vi_list"):
            return
        self.vi_list.delete(0, "end")
        self._vi_order = list(self.project.vis)
        for vi_id in self._vi_order:
            vi = self.project.vis[vi_id]
            self.vi_list.insert("end", ("* " if vi_id == self.project.main_vi else "  ") + vi.name)
        if self.current_vi_id in self._vi_order:
            index = self._vi_order.index(self.current_vi_id)
            self.vi_list.selection_set(index)

    def _switch_vi_event(self, _event: tk.Event) -> None:
        selection = self.vi_list.curselection()
        if selection:
            self.switch_vi(self._vi_order[selection[0]])

    def switch_vi(self, vi_id: str) -> None:
        if vi_id == self.current_vi_id or vi_id not in self.project.vis:
            return
        self.stop()
        self.current_vi_id = vi_id
        self._replace_graph(self.project.vis[vi_id].graph)
        self._update_title()

    def add_vi(self) -> None:
        name = simpledialog.askstring("Add VI", "VI name:", parent=self)
        if not name:
            return
        if not name.strip() or any(vi.name == name.strip() for vi in self.project.vis.values()):
            messagebox.showerror("Add VI", "VI name must be non-empty and unique", parent=self)
            return
        self.checkpoint()
        try: vi = self.project.add_vi(name)
        except ValueError as exc: messagebox.showerror("Add VI", str(exc), parent=self); return
        self.current_vi_id = vi.id
        self._replace_graph(vi.graph)
        self.changed()
        self._refresh_vi_list()

    def rename_vi(self) -> None:
        vi = self.project.vis[self.current_vi_id]
        name = simpledialog.askstring("Rename VI", "VI name:", initialvalue=vi.name, parent=self)
        if not name: return
        if name.strip() == vi.name:
            return
        if not name.strip() or any(item.name == name.strip() and item.id != vi.id for item in self.project.vis.values()):
            messagebox.showerror("Rename VI", "VI name must be non-empty and unique", parent=self)
            return
        self.checkpoint()
        try: self.project.rename_vi(vi.id, name)
        except ValueError as exc: messagebox.showerror("Rename VI", str(exc), parent=self); return
        self.changed(); self._refresh_vi_list()

    def delete_vi(self) -> None:
        vi_id = self.current_vi_id
        if vi_id == self.project.main_vi:
            messagebox.showerror("Delete VI", "cannot delete main VI", parent=self)
            return
        if any(n.type == "subvi" and n.properties.get("vi_id") == vi_id
               for vi in self.project.vis.values() for n in vi.graph.nodes.values()):
            messagebox.showerror("Delete VI", "VI is referenced by a SubVI node", parent=self)
            return
        if not messagebox.askyesno("Delete VI", f"Delete {self.project.vis[vi_id].name}?", parent=self):
            return
        self.checkpoint()
        try: self.project.delete_vi(vi_id)
        except ValueError as exc: messagebox.showerror("Delete VI", str(exc), parent=self); return
        self.current_vi_id = self.project.main_vi
        self._replace_graph(self.project.main.graph)
        self.changed(); self._refresh_vi_list()

    def set_main_vi(self) -> None:
        if self.current_vi_id == self.project.main_vi:
            return
        self.checkpoint()
        self.project.set_main(self.current_vi_id)
        self.changed(); self._refresh_vi_list()

    def create_subvi(self) -> None:
        choices = [vi for vi in self.project.vis.values() if vi.id != self.current_vi_id]
        if not choices:
            messagebox.showinfo("Create SubVI", "Add another VI first.", parent=self); return
        name = simpledialog.askstring("Create SubVI", "Target VI name:\n" + ", ".join(vi.name for vi in choices), parent=self)
        target = next((vi for vi in choices if vi.name == name), None)
        if not target:
            if name is not None: messagebox.showerror("Create SubVI", "Unknown VI name.", parent=self)
            return
        self.checkpoint()
        node = self.graph.add_node("subvi", 100, 100)
        node.label, node.properties["vi_id"] = target.name, target.id
        self.changed(); self.canvas.redraw()

    def configure_connector(self) -> None:
        vi = self.project.vis[self.current_vi_id]
        dialog = tk.Toplevel(self)
        dialog.title("Connector Pane - " + vi.name)
        dialog.transient(self); dialog.grab_set()
        ttk.Label(dialog, text="Satu terminal per baris: direction,name,node_id,port,type\nInput wajib menunjuk output control yang unik; output menunjuk output node.").pack(anchor="w", padx=10, pady=8)
        text = tk.Text(dialog, width=75, height=14)
        text.pack(fill="both", expand=True, padx=10)
        for direction, terminals in (("input", vi.connector_inputs), ("output", vi.connector_outputs)):
            for term in terminals: text.insert("end", f"{direction},{term.name},{term.node_id},{term.port},{term.data_type}\n")
        def apply() -> None:
            inputs: list[ConnectorTerminal] = []; outputs: list[ConnectorTerminal] = []
            try:
                for line in text.get("1.0", "end").splitlines():
                    if not line.strip(): continue
                    direction, name, node_id, port, data_type = [part.strip() for part in line.split(",")]
                    if direction not in ("input", "output") or data_type not in DATA_TYPES: raise ValueError("direction/type connector tidak valid")
                    (inputs if direction == "input" else outputs).append(ConnectorTerminal(name, node_id, port, data_type))
                old_in, old_out = vi.connector_inputs, vi.connector_outputs
                vi.connector_inputs, vi.connector_outputs = inputs, outputs
                try:
                    self.project.validate_connectors()
                finally:
                    vi.connector_inputs, vi.connector_outputs = old_in, old_out
                valid_inputs = {term.name for term in inputs}
                valid_outputs = {term.name for term in outputs}
                input_types = {term.name: term.data_type for term in inputs}
                output_types = {term.name: term.data_type for term in outputs}
                affected: list[tuple[str, Any]] = []
                for parent_vi in self.project.vis.values():
                    calls = {node.id for node in parent_vi.graph.nodes.values()
                             if node.type == "subvi" and node.properties.get("vi_id") == vi.id}
                    for wire in parent_vi.graph.wires:
                        invalid_source = wire.source_node in calls and (
                            wire.source_port not in valid_outputs
                            or not compatible(output_types[wire.source_port], parent_vi.graph.port_type(
                                parent_vi.graph.nodes[wire.target_node], "in", wire.target_port)))
                        invalid_target = wire.target_node in calls and (
                            wire.target_port not in valid_inputs
                            or not compatible(parent_vi.graph.port_type(
                                parent_vi.graph.nodes[wire.source_node], "out", wire.source_port),
                                input_types[wire.target_port]))
                        if invalid_source or invalid_target:
                            affected.append((parent_vi.id, wire))
            except (KeyError, StopIteration, ValueError, TypeError) as exc: messagebox.showerror("Connector Pane", str(exc), parent=dialog); return
            if affected and not messagebox.askyesno(
                    "Connector Pane", f"Perubahan ini akan menghapus {len(affected)} wire yang tidak lagi valid. Lanjutkan?",
                    parent=dialog):
                return
            if inputs == old_in and outputs == old_out:
                dialog.destroy()
                return
            self.checkpoint()
            vi.connector_inputs, vi.connector_outputs = inputs, outputs
            affected_by_vi: dict[str, set[int]] = {}
            for parent_id, wire in affected:
                affected_by_vi.setdefault(parent_id, set()).add(id(wire))
            for parent_id, wire_ids in affected_by_vi.items():
                parent_graph = self.project.vis[parent_id].graph
                parent_graph.wires = [wire for wire in parent_graph.wires if id(wire) not in wire_ids]
            self.changed(); self.canvas.redraw(); dialog.destroy()
        ttk.Button(dialog, text="Apply", command=apply).pack(pady=8)

    def validate_current(self) -> None:
        errors = self.runtime.validate(self.graph, self.project, self.current_vi_id)
        if errors:
            for error in errors: self.log("VALIDATION " + error)
            self.status_var.set(f"Validation failed: {len(errors)} error(s)")
        else:
            self.status_var.set("Validation successful")

    def log(self, text: str) -> None:
        self.console.configure(state="normal")
        self.console.insert("end", text + "\n")
        self.console.see("end")
        self.console.configure(state="disabled")

    def show_help(self) -> None:
        messagebox.showinfo(
            "PyLabView Studio Help",
            "Double-click a library item to add it. Drag a node by its body. Click a yellow output port, then a blue input port to wire them. Select a node or wire and press Delete.\n\nUse F5 for one run, F6 for continuous execution, and Ctrl+mouse-wheel to zoom. Constants and output nodes appear automatically in Front Panel.",
            parent=self,
        )

    def show_about(self) -> None:
        messagebox.showinfo(
            "About PyLabView Studio",
            f"PyLabView Studio {__version__}\n\nAn independent, educational Python dataflow environment. This project is not affiliated with, endorsed by, or a product of National Instruments. LabVIEW is a trademark of its respective owner.",
            parent=self,
        )


def main() -> None:
    app = StudioApp()
    app.mainloop()


if __name__ == "__main__":
    main()
