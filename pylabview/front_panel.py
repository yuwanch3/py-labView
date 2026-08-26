from __future__ import annotations

import json
import math
import tkinter as tk
from tkinter import simpledialog
from typing import Any, Callable

from .model import Graph, _normalized_panel, update_chart_history
from .integrations.vision_adapter import ImageFrame
from .panel_widgets import gauge_fraction, image_to_ppm, next_dropdown_value, table_rows


class PanelDesigner(tk.Canvas):
    """Free-layout Front Panel editor and lightweight operate surface."""

    def __init__(self, master: tk.Misc, graph: Graph, panel: dict[str, Any],
                 on_change: Callable[[], None] | None = None,
                 on_value_change: Callable[[dict[str, Any]], None] | None = None) -> None:
        self.panel = _normalized_panel(panel, graph)
        canvas = self.panel["canvas"]
        super().__init__(master, background=canvas["background"], highlightthickness=0,
                         scrollregion=(0, 0, canvas["width"], canvas["height"]), takefocus=True)
        self.graph = graph
        self.on_change = on_change or (lambda: None)
        self.on_value_change = on_value_change or (lambda _values: None)
        self.mode = "edit"
        self.zoom = 1.0
        self.grid_size = 10
        self.selected_id: str | None = None
        self.values: dict[str, Any] = {}
        self.chart_history: dict[str, list[float]] = {}
        self._image_refs: dict[str, tk.PhotoImage] = {}
        self._drag: tuple[str, float, float, dict[str, float], bool] | None = None
        self.bind("<Button-1>", self._press)
        self.bind("<Double-1>", self._double_press)
        self.bind("<B1-Motion>", self._motion)
        self.bind("<ButtonRelease-1>", self._release)
        self.bind("<Control-MouseWheel>", self._zoom_wheel)
        self.bind("<Control-Button-4>", lambda event: self._set_zoom(1.1, event.x, event.y))
        self.bind("<Control-Button-5>", lambda event: self._set_zoom(0.9, event.x, event.y))
        self.bind("<Shift-MouseWheel>", self._horizontal_wheel)
        self.bind("<Shift-Button-4>", lambda _event: self._scroll_horizontal(-1))
        self.bind("<Shift-Button-5>", lambda _event: self._scroll_horizontal(1))
        self.bind("<Configure>", lambda _event: self.redraw())
        self._initialize_values()
        self.redraw()

    def set_document(self, graph: Graph, panel: dict[str, Any]) -> None:
        if graph is not self.graph:
            self.values.clear()
            self.chart_history.clear()
        self.graph = graph
        self.panel = _normalized_panel(panel, graph)
        self.selected_id = None
        self._initialize_values()
        canvas = self.panel["canvas"]
        self.configure(background=canvas["background"],
                       scrollregion=(0, 0, canvas["width"] * self.zoom, canvas["height"] * self.zoom))
        self.redraw()

    def rebuild(self, graph: Graph) -> None:
        self.set_document(graph, self.panel)

    def set_mode(self, mode: str) -> None:
        if mode not in ("edit", "operate"):
            raise ValueError("panel mode must be edit or operate")
        self.mode = mode
        self.selected_id = None
        self.redraw()

    def _initialize_values(self) -> None:
        for item in self.panel["items"]:
            node = self.graph.nodes.get(item["terminal_node_id"])
            if node and item["kind"].endswith("control"):
                self.values.setdefault(node.id, node.properties.get("value"))

    def control_values(self) -> dict[str, Any]:
        control_ids = {item["terminal_node_id"] for item in self.panel["items"]
                       if item["kind"].endswith("control")}
        return {node_id: value for node_id, value in self.values.items() if node_id in control_ids}

    def update_values(self, values: dict[str, Any]) -> None:
        self.values.update(values)
        for item in self.panel["items"]:
            node_id = item["terminal_node_id"]
            if item["kind"] == "chart" and node_id in values:
                limit = int(self.graph.nodes[node_id].properties.get("history", 100))
                self.chart_history[node_id] = update_chart_history(
                    self.chart_history.get(node_id, []), values[node_id], limit)
        self.redraw()

    def redraw(self) -> None:
        self.delete("all")
        self._image_refs.clear()
        width, height = int(self.panel["canvas"]["width"]), int(self.panel["canvas"]["height"])
        if self.mode == "edit":
            for x in range(0, width + 1, self.grid_size):
                self.create_line(x, 0, x, height, fill="#d3d3d3", tags="grid")
            for y in range(0, height + 1, self.grid_size):
                self.create_line(0, y, width, y, fill="#d3d3d3", tags="grid")
        for item in sorted(self.panel["items"], key=lambda entry: entry["z_index"]):
            self._draw_item(item)
        if self.zoom != 1.0:
            self.scale("all", 0, 0, self.zoom, self.zoom)
        self.configure(scrollregion=(0, 0, width * self.zoom, height * self.zoom))

    def _draw_item(self, item: dict[str, Any]) -> None:
        bounds = item["bounds"]
        x, y, w, h = bounds["x"], bounds["y"], bounds["width"], bounds["height"]
        selected = item["id"] == self.selected_id
        tag = f"panel:{item['id']}"
        self.create_rectangle(x, y, x + w, y + h, fill="#f7f7f7", outline="#2070b4" if selected else "#777",
                              width=3 if selected else 1, tags=("panel_item", tag))
        label = item["properties"].get("label", item["kind"].replace("_", " ").title())
        self.create_text(x + 8, y + 10, text=label, anchor="w", font=self._font(9, bold=True), tags=("panel_item", tag))
        node_id = item["terminal_node_id"]
        value = self.values.get(node_id, "--")
        kind = item["kind"]
        display_type = item["properties"].get("display_type", "")
        if kind == "image_indicator" and isinstance(value, ImageFrame):
            try:
                image = tk.PhotoImage(data=image_to_ppm(value), format="PPM")
                scale = max(1, math.ceil(max(image.width() / max((w - 12) * self.zoom, 1),
                                             image.height() / max((h - 30) * self.zoom, 1))))
                if scale > 1:
                    image = image.subsample(scale, scale)
                self._image_refs[item["id"]] = image
                self.create_image(x + w / 2, y + h / 2 + 10, image=image, tags=("panel_item", tag))
            except (TypeError, ValueError, tk.TclError):
                self.create_text(x + w / 2, y + h / 2 + 10,
                                  text=f"Image {value.width} x {value.height} x {value.channels}",
                                  justify="center", font=self._font(10), tags=("panel_item", tag))
        elif kind == "boolean_control" and display_type == "radio_start_stop":
            active = bool(value)
            for index, (text, selected_value) in enumerate((("STOP (0)", False), ("START (1)", True))):
                center_x = x + w * (0.28 + index * 0.44)
                self.create_oval(center_x - 9, y + h / 2 - 3, center_x + 9, y + h / 2 + 15,
                                 fill="#35b85a" if active == selected_value else "#fff", outline="#222",
                                 tags=("panel_item", tag))
                self.create_text(center_x, y + h - 10, text=text, font=self._font(10), tags=("panel_item", tag))
        elif display_type == "gauge" and isinstance(value, (int, float)):
            fraction = gauge_fraction(value, item["properties"].get("minimum", 0),
                                      item["properties"].get("maximum", 100))
            left, right, top, bottom = x + 12, x + w - 12, y + h / 2, y + h / 2 + 18
            self.create_rectangle(left, top, right, bottom, fill="#ddd", outline="#333", tags=("panel_item", tag))
            self.create_rectangle(left, top, left + (right - left) * fraction, bottom,
                                  fill="#00866a", outline="", tags=("panel_item", tag))
            self.create_text(x + w / 2, bottom + 12, text=self._format(value),
                             font=self._font(10), tags=("panel_item", tag))
        elif display_type == "table":
            rows = table_rows(value)
            if rows:
                columns = max(len(row) for row in rows)
                cell_w = (w - 12) / max(columns, 1)
                cell_h = min(28, (h - 28) / max(len(rows), 1))
                for row_index, row in enumerate(rows[:10]):
                    for column_index, cell in enumerate(row):
                        x0, y0 = x + 6 + column_index * cell_w, y + 24 + row_index * cell_h
                        self.create_rectangle(x0, y0, x0 + cell_w, y0 + cell_h, outline="#aaa",
                                              tags=("panel_item", tag))
                        self.create_text(x0 + cell_w / 2, y0 + cell_h / 2, text=self._format(cell)[:16],
                                         font=self._font(8, family="TkFixedFont"), tags=("panel_item", tag))
        elif display_type == "dropdown" and kind == "string_control":
            self.create_rectangle(x + 8, y + h / 2 - 8, x + w - 8, y + h / 2 + 20,
                                  fill="white", outline="#555", tags=("panel_item", tag))
            self.create_text(x + 14, y + h / 2 + 6, text=self._format(value), anchor="w",
                             font=self._font(10), tags=("panel_item", tag))
            self.create_text(x + w - 20, y + h / 2 + 6, text="▼",
                             font=self._font(10), tags=("panel_item", tag))
        elif kind == "boolean_control" or (kind == "indicator" and isinstance(value, bool)):
            active = bool(value)
            self.create_oval(x + w / 2 - 18, y + h / 2 - 10, x + w / 2 + 18, y + h / 2 + 26,
                             fill="#35b85a" if active else "#555", outline="#222", tags=("panel_item", tag))
        elif kind == "chart":
            numbers = self.chart_history.get(node_id, [])
            if len(numbers) > 1:
                low, high = min(numbers), max(numbers); span = high - low or 1
                points: list[float] = []
                for index, number in enumerate(numbers):
                    points.extend((x + 8 + index * (w - 16) / (len(numbers) - 1), y + h - 8 - (number - low) / span * (h - 36)))
                self.create_line(*points, fill="#00866a", width=2, tags=("panel_item", tag))
            self.create_text(x + w / 2, y + h - 5,
                              text=item["properties"].get("x_label", "Baris Pixel"), anchor="s",
                              font=self._font(7), tags=("panel_item", tag))
            self.create_text(x + 4, y + h / 2,
                              text=item["properties"].get("y_label", "Intensitas (Threshold)"), anchor="w",
                              angle=90, font=self._font(7), tags=("panel_item", tag))
        else:
            self.create_text(x + w / 2, y + h / 2 + 10, text=self._format(value),
                             font=self._font(13, family="TkFixedFont", bold=True), tags=("panel_item", tag))
        if selected and self.mode == "edit":
            self.create_rectangle(x + w - 10, y + h - 10, x + w, y + h, fill="#2070b4", tags=("resize", tag))

    @staticmethod
    def _format(value: Any) -> str:
        if isinstance(value, float): return f"{value:.6g}"
        if isinstance(value, (list, dict)): return json.dumps(value, ensure_ascii=False)[:80]
        return str(value)

    def _font(self, size: int, family: str = "TkDefaultFont", bold: bool = False) -> tuple[object, ...]:
        scaled_size = max(5, round(size * self.zoom))
        return (family, scaled_size, "bold") if bold else (family, scaled_size)

    def _item_at(self, x: float, y: float) -> tuple[dict[str, Any] | None, bool]:
        for item in reversed(sorted(self.panel["items"], key=lambda entry: entry["z_index"])):
            b = item["bounds"]
            if b["x"] <= x <= b["x"] + b["width"] and b["y"] <= y <= b["y"] + b["height"]:
                resize = x >= b["x"] + b["width"] - 12 and y >= b["y"] + b["height"] - 12
                return item, resize
        return None, False

    def _press(self, event: tk.Event) -> None:
        x, y = self._document_point(event)
        item, resize = self._item_at(x, y)
        if not item:
            self.selected_id = None; self.redraw(); return
        node_id = item["terminal_node_id"]
        if self.mode == "operate":
            if item["kind"] == "boolean_control":
                if item["properties"].get("display_type") == "radio_start_stop":
                    midpoint = item["bounds"]["x"] + item["bounds"]["width"] / 2
                    self.values[node_id] = x >= midpoint
                else:
                    self.values[node_id] = not bool(self.values.get(node_id, False))
                self.redraw()
                self.on_value_change(self.control_values())
            elif item["kind"] == "string_control" and item["properties"].get("display_type") == "dropdown":
                try:
                    self.values[node_id] = next_dropdown_value(
                        self.values.get(node_id, ""), item["properties"].get("options"))
                except ValueError:
                    return
                self.redraw()
                self.on_value_change(self.control_values())
            return
        self.selected_id = item["id"]
        self._drag = (item["id"], x, y, dict(item["bounds"]), resize)
        self.redraw()

    def _motion(self, event: tk.Event) -> None:
        if not self._drag or self.mode != "edit": return
        item_id, start_x, start_y, original, resize = self._drag
        item = next(entry for entry in self.panel["items"] if entry["id"] == item_id)
        x, y = self._document_point(event)
        snap = lambda value: round(value / self.grid_size) * self.grid_size
        if resize:
            item["bounds"]["width"] = max(40, snap(original["width"] + x - start_x))
            item["bounds"]["height"] = max(30, snap(original["height"] + y - start_y))
        else:
            item["bounds"]["x"] = max(0, snap(original["x"] + x - start_x))
            item["bounds"]["y"] = max(0, snap(original["y"] + y - start_y))
        self.redraw()

    def _double_press(self, event: tk.Event) -> None:
        if self.mode != "operate": return
        item, _resize = self._item_at(*self._document_point(event))
        if not item or not item["kind"].endswith("control") or item["kind"] == "boolean_control": return
        node_id = item["terminal_node_id"]
        raw = simpledialog.askstring("Control Value", "Value:", initialvalue=self._format(self.values.get(node_id, "")), parent=self)
        if raw is None: return
        try:
            if item["kind"] == "numeric_control": value: Any = float(raw)
            elif item["kind"] == "array_control": value = json.loads(raw)
            else: value = raw
        except (ValueError, json.JSONDecodeError):
            return
        if item["kind"] == "array_control" and not isinstance(value, list):
            return
        self.values[node_id] = value
        self.redraw()
        self.on_value_change(self.control_values())

    def _release(self, _event: tk.Event) -> None:
        if self._drag:
            self._drag = None
            self.on_change()

    def _document_point(self, event: tk.Event) -> tuple[float, float]:
        return self.canvasx(event.x) / self.zoom, self.canvasy(event.y) / self.zoom

    def _zoom_wheel(self, event: tk.Event) -> str:
        self._set_zoom(1.1 if event.delta > 0 else 0.9, event.x, event.y)
        return "break"

    def _set_zoom(self, factor: float, x: int, y: int) -> str:
        old_zoom = self.zoom
        document_x = self.canvasx(x) / old_zoom
        document_y = self.canvasy(y) / old_zoom
        self.zoom = min(2.0, max(0.55, old_zoom * factor))
        if self.zoom == old_zoom:
            return "break"
        self.redraw()
        width = max(float(self.panel["canvas"]["width"]) * self.zoom, 1.0)
        height = max(float(self.panel["canvas"]["height"]) * self.zoom, 1.0)
        self.xview_moveto(max(0.0, (document_x * self.zoom - x) / width))
        self.yview_moveto(max(0.0, (document_y * self.zoom - y) / height))
        return "break"

    def _horizontal_wheel(self, event: tk.Event) -> str:
        return self._scroll_horizontal(-1 if event.delta > 0 else 1)

    def _scroll_horizontal(self, direction: int) -> str:
        self.xview_scroll(direction, "units")
        return "break"


FrontPanel = PanelDesigner
