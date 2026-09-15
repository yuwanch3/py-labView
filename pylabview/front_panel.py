from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any
import json

from .model import Graph, NODE_DEFINITIONS
from .typesystem import editor_value_text


class FrontPanel(tk.Toplevel):
    def __init__(self, master: tk.Misc, graph: Graph) -> None:
        super().__init__(master)
        self.title("Front Panel - PyLabView Studio")
        self.geometry("720x480")
        self.graph = graph
        self.controls: dict[str, tk.Variable] = {}
        self.indicators: dict[str, ttk.Label] = {}
        self.charts: dict[str, tk.Canvas] = {}
        self.visuals: dict[str, tuple[str, tk.Canvas]] = {}
        self.history: dict[str, list[float]] = {}
        self.protocol("WM_DELETE_WINDOW", self.withdraw)
        self.container = ttk.Frame(self, padding=14)
        self.container.pack(fill="both", expand=True)
        self.rebuild(graph)

    def rebuild(self, graph: Graph) -> None:
        previous_controls = {node_id: variable.get() for node_id, variable in self.controls.items()}
        self.graph = graph
        for child in self.container.winfo_children():
            child.destroy()
        self.controls.clear()
        self.indicators.clear()
        self.charts.clear()
        self.visuals.clear()
        title = ttk.Label(self.container, text=graph.name + " - Front Panel", font=("TkDefaultFont", 16, "bold"))
        title.pack(anchor="w", pady=(0, 12))
        items = [node for node in graph.nodes.values() if NODE_DEFINITIONS[node.type].front_panel]
        if not items:
            ttk.Label(self.container, text="Add constants, Display, or Waveform Chart nodes to populate this panel.").pack(anchor="w")
        for node in items:
            mode = NODE_DEFINITIONS[node.type].front_panel
            frame = ttk.LabelFrame(self.container, text=node.label, padding=8)
            frame.pack(fill="x", pady=4)
            if mode == "control":
                value = previous_controls.get(node.id, node.properties.get("value"))
                self._add_control(frame, node.id, node.type, value)
            elif mode == "indicator":
                display_type = str(node.properties.get("display_type", "auto"))
                if display_type in ("led", "gauge", "progress", "thermometer"):
                    canvas = tk.Canvas(frame, height=90, background="#10151d", highlightthickness=0)
                    canvas.pack(fill="x")
                    self.visuals[node.id] = (display_type, canvas)
                else:
                    label = ttk.Label(frame, text="--", font=("TkFixedFont", 14, "bold"))
                    label.pack(anchor="w")
                    self.indicators[node.id] = label
            elif mode == "chart":
                canvas = tk.Canvas(frame, height=120, background="#10151d", highlightthickness=0)
                canvas.pack(fill="x", expand=True)
                self.charts[node.id] = canvas
                self.history.setdefault(node.id, [])

    def _add_control(self, parent: ttk.Frame, node_id: str, node_type: str, value: Any) -> None:
        if node_type == "boolean_constant":
            variable: tk.Variable = tk.BooleanVar(value=bool(value))
            ttk.Checkbutton(parent, text="Enabled", variable=variable).pack(anchor="w")
        else:
            variable = tk.StringVar(value=editor_value_text(value))
            ttk.Entry(parent, textvariable=variable).pack(fill="x")
        self.controls[node_id] = variable

    def control_values(self) -> dict[str, Any]:
        values: dict[str, Any] = {}
        for node_id, variable in self.controls.items():
            node = self.graph.nodes.get(node_id)
            if not node:
                continue
            raw = variable.get()
            if node.type == "numeric_constant":
                try:
                    values[node_id] = float(raw)
                except (TypeError, ValueError):
                    values[node_id] = raw
            elif node.type == "boolean_constant":
                values[node_id] = bool(raw)
            elif node.type == "array_constant":
                try:
                    parsed = json.loads(str(raw))
                    values[node_id] = parsed if isinstance(parsed, list) else raw
                except json.JSONDecodeError:
                    values[node_id] = raw
            else:
                values[node_id] = str(raw)
        return values

    def update_values(self, values: dict[str, Any]) -> None:
        for node_id, label in self.indicators.items():
            if node_id in values:
                label.configure(text=self._format(values[node_id]))
        for node_id, canvas in self.charts.items():
            if node_id not in values:
                continue
            raw = values[node_id]
            samples = raw.y if hasattr(raw, "y") else [raw]
            try: numeric = [float(value) for value in samples]
            except (TypeError, ValueError): continue
            limit = int(self.graph.nodes[node_id].properties.get("history", 100))
            history = self.history.setdefault(node_id, [])
            history.extend(numeric)
            del history[:-max(2, limit)]
            self._draw_chart(canvas, history)
        for node_id, (kind, canvas) in self.visuals.items():
            if node_id in values:
                self._draw_visual(canvas, kind, values[node_id])

    @staticmethod
    def _format(value: Any) -> str:
        return f"{value:.6g}" if isinstance(value, float) else str(value)

    @staticmethod
    def _draw_chart(canvas: tk.Canvas, values: list[float]) -> None:
        canvas.delete("all")
        width = max(canvas.winfo_width(), 50)
        height = max(canvas.winfo_height(), 50)
        canvas.create_line(0, height / 2, width, height / 2, fill="#273244")
        if len(values) < 2:
            return
        low, high = min(values), max(values)
        span = high - low or 1.0
        points: list[float] = []
        for index, value in enumerate(values):
            points.extend((index * width / (len(values) - 1), height - 8 - (value - low) / span * (height - 16)))
        canvas.create_line(*points, fill="#45d6a7", width=2)

    @staticmethod
    def _draw_visual(canvas: tk.Canvas, kind: str, value: Any) -> None:
        canvas.delete("all")
        width, height = max(canvas.winfo_width(), 100), max(canvas.winfo_height(), 60)
        if kind == "led":
            active = bool(value)
            canvas.create_oval(15, 15, 65, 65, fill="#45d66b" if active else "#39424e", outline="#d8e2ef")
            return
        try: numeric = max(0.0, min(100.0, float(value)))
        except (TypeError, ValueError): return
        if kind in ("progress", "thermometer"):
            canvas.create_rectangle(10, 25, width - 10, 60, outline="#73849b")
            canvas.create_rectangle(12, 27, 12 + (width - 24) * numeric / 100, 58, fill="#00c2a8", outline="")
        else:
            canvas.create_arc(15, 10, width - 15, height * 1.7, start=0, extent=180, style="arc", outline="#8ecae6", width=5)
            canvas.create_text(width / 2, height / 2, text=f"{numeric:.1f}", fill="white", font=("TkFixedFont", 15, "bold"))
