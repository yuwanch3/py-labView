from __future__ import annotations

import tkinter as tk
from typing import Callable

from .model import Graph, NODE_DEFINITIONS, Wire
from .typesystem import WIRE_COLORS


NODE_WIDTH = 130
HEADER_HEIGHT = 28
PORT_SPACING = 22


class DiagramCanvas(tk.Canvas):
    def __init__(
        self,
        master: tk.Misc,
        graph: Graph,
        on_select: Callable[[str | None], None],
        before_change: Callable[[], None],
        on_change: Callable[[], None],
        on_error: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__(master, background="#151a22", highlightthickness=0, takefocus=True)
        self.graph = graph
        self.on_select = on_select
        self.before_change = before_change
        self.on_change = on_change
        self.on_error = on_error or (lambda _message: None)
        self.zoom = 1.0
        self.selected_node: str | None = None
        self.selected_wire: Wire | None = None
        self.pending_output: tuple[str, str] | None = None
        self.drag_origin: tuple[float, float] | None = None
        self.drag_node_origin: tuple[float, float] | None = None
        self.drag_snapshot_taken = False
        self.statuses: dict[str, str] = {}
        self.bind("<Button-1>", self._press)
        self.bind("<B1-Motion>", self._drag)
        self.bind("<ButtonRelease-1>", self._release)
        self.bind("<Delete>", lambda _event: self.delete_selection())
        self.bind("<BackSpace>", lambda _event: self.delete_selection())
        self.bind("<Control-MouseWheel>", self._zoom_wheel)
        self.bind("<Control-Button-4>", lambda event: self._set_zoom(1.1, event.x, event.y))
        self.bind("<Control-Button-5>", lambda event: self._set_zoom(0.9, event.x, event.y))
        self.bind("<Configure>", lambda _event: self.redraw())
        self.redraw()

    def set_graph(self, graph: Graph) -> None:
        self.graph = graph
        self.selected_node = None
        self.selected_wire = None
        self.pending_output = None
        self.statuses = {}
        self.redraw()

    def set_statuses(self, statuses: dict[str, str]) -> None:
        self.statuses = statuses
        self.redraw()

    def _node_height(self, node_id: str) -> int:
        node = self.graph.nodes[node_id]
        return max(66, HEADER_HEIGHT + max(len(self.graph.ports(node, "in")), len(self.graph.ports(node, "out")), 1) * PORT_SPACING + 8)

    def _port_position(self, node_id: str, direction: str, index: int) -> tuple[float, float]:
        node = self.graph.nodes[node_id]
        x = node.x if direction == "in" else node.x + NODE_WIDTH
        y = node.y + HEADER_HEIGHT + 14 + index * PORT_SPACING
        return x * self.zoom, y * self.zoom

    def redraw(self) -> None:
        self.delete("all")
        width = max(self.winfo_width(), 800)
        height = max(self.winfo_height(), 600)
        spacing = max(12, int(24 * self.zoom))
        for x in range(0, width, spacing):
            self.create_line(x, 0, x, height, fill="#202734", tags="grid")
        for y in range(0, height, spacing):
            self.create_line(0, y, width, y, fill="#202734", tags="grid")
        for wire in self.graph.wires:
            source_node = self.graph.nodes[wire.source_node]
            target_node = self.graph.nodes[wire.target_node]
            sx, sy = self._port_position(wire.source_node, "out", self.graph.ports(source_node, "out").index(wire.source_port))
            tx, ty = self._port_position(wire.target_node, "in", self.graph.ports(target_node, "in").index(wire.target_port))
            bend = max(30, abs(tx - sx) * 0.45)
            color = "#ffffff" if wire is self.selected_wire else WIRE_COLORS.get(wire.data_type, WIRE_COLORS["variant"])
            tag = f"wire:{id(wire)}"
            self.create_line(sx, sy, sx + bend, sy, tx - bend, ty, tx, ty, smooth=True, width=3, fill=color, tags=("wire", tag))
        for node_id, node in self.graph.nodes.items():
            self._draw_node(node_id)
        if self.pending_output:
            node_id, port = self.pending_output
            node = self.graph.nodes[node_id]
            x, y = self._port_position(node_id, "out", self.graph.ports(node, "out").index(port))
            self.create_oval(x - 8, y - 8, x + 8, y + 8, outline="#ffd166", width=3, tags="pending")

    def _draw_node(self, node_id: str) -> None:
        node = self.graph.nodes[node_id]
        definition = NODE_DEFINITIONS[node.type]
        x, y = node.x * self.zoom, node.y * self.zoom
        w, h = NODE_WIDTH * self.zoom, self._node_height(node_id) * self.zoom
        status_colors = {"success": "#2b9348", "running": "#f4a261", "error": "#d1495b"}
        outline = status_colors.get(self.statuses.get(node_id), "#73849b")
        if node_id == self.selected_node:
            outline = "#ffd166"
        common = ("node", f"node:{node_id}")
        self.create_rectangle(x, y, x + w, y + h, fill="#252d3a", outline=outline, width=3, tags=common)
        self.create_rectangle(x, y, x + w, y + HEADER_HEIGHT * self.zoom, fill="#344154", outline="", tags=common)
        self.create_text(x + w / 2, y + HEADER_HEIGHT * self.zoom / 2, text=node.label, fill="#f4f7fb", font=("TkDefaultFont", max(8, int(10 * self.zoom)), "bold"), width=w - 8, tags=common)
        radius = max(4, 6 * self.zoom)
        font = ("TkDefaultFont", max(7, int(8 * self.zoom)))
        for index, port in enumerate(self.graph.ports(node, "in")):
            px, py = self._port_position(node_id, "in", index)
            tag = f"port:in:{node_id}:{port}"
            color = WIRE_COLORS[self.graph.port_type(node, "in", port)]
            self.create_oval(px - radius, py - radius, px + radius, py + radius, fill=color, outline="#111", tags=("port", tag))
            self.create_text(px + 10 * self.zoom, py, text=port, fill="#d8e2ef", anchor="w", font=font, tags=common)
        for index, port in enumerate(self.graph.ports(node, "out")):
            px, py = self._port_position(node_id, "out", index)
            tag = f"port:out:{node_id}:{port}"
            color = WIRE_COLORS[self.graph.port_type(node, "out", port)]
            self.create_oval(px - radius, py - radius, px + radius, py + radius, fill=color, outline="#111", tags=("port", tag))
            self.create_text(px - 10 * self.zoom, py, text=port, fill="#d8e2ef", anchor="e", font=font, tags=common)

    def _tags_at(self, x: int, y: int) -> tuple[str, ...]:
        items = self.find_overlapping(x - 3, y - 3, x + 3, y + 3)
        for item in reversed(items):
            tags = self.gettags(item)
            if "grid" not in tags:
                return tags
        return ()

    def _press(self, event: tk.Event) -> None:
        self.focus_set()
        tags = self._tags_at(event.x, event.y)
        port_tag = next((tag for tag in tags if tag.startswith("port:")), None)
        if port_tag:
            _, direction, node_id, port = port_tag.split(":", 3)
            if direction == "out":
                self.pending_output = (node_id, port)
            elif self.pending_output:
                try:
                    self.before_change()
                    self.graph.connect(*self.pending_output, node_id, port)
                    self.on_change()
                except ValueError as exc:
                    self.on_error(str(exc))
                self.pending_output = None
            self.redraw()
            return
        node_tag = next((tag for tag in tags if tag.startswith("node:")), None)
        if node_tag:
            self.selected_node = node_tag.split(":", 1)[1]
            self.selected_wire = None
            node = self.graph.nodes[self.selected_node]
            self.drag_origin = (event.x, event.y)
            self.drag_node_origin = (node.x, node.y)
            self.drag_snapshot_taken = False
            self.on_select(self.selected_node)
        else:
            wire_tag = next((tag for tag in tags if tag.startswith("wire:")), None)
            self.selected_wire = next((w for w in self.graph.wires if wire_tag == f"wire:{id(w)}"), None)
            self.selected_node = None
            self.pending_output = None
            self.on_select(None)
        self.redraw()

    def _drag(self, event: tk.Event) -> None:
        if not self.selected_node or not self.drag_origin or not self.drag_node_origin:
            return
        if not self.drag_snapshot_taken:
            self.before_change()
            self.drag_snapshot_taken = True
        dx = (event.x - self.drag_origin[0]) / self.zoom
        dy = (event.y - self.drag_origin[1]) / self.zoom
        node = self.graph.nodes[self.selected_node]
        node.x = max(0, self.drag_node_origin[0] + dx)
        node.y = max(0, self.drag_node_origin[1] + dy)
        self.redraw()

    def _release(self, _event: tk.Event) -> None:
        if self.drag_snapshot_taken:
            self.on_change()
        self.drag_origin = None
        self.drag_node_origin = None

    def delete_selection(self) -> None:
        if not self.selected_node and not self.selected_wire:
            return
        self.before_change()
        if self.selected_node:
            self.graph.remove_node(self.selected_node)
            self.selected_node = None
            self.on_select(None)
        elif self.selected_wire:
            self.graph.disconnect(self.selected_wire)
            self.selected_wire = None
        self.on_change()
        self.redraw()

    def _zoom_wheel(self, event: tk.Event) -> str:
        self._set_zoom(1.1 if event.delta > 0 else 0.9, event.x, event.y)
        return "break"

    def _set_zoom(self, factor: float, _x: int, _y: int) -> str:
        self.zoom = min(2.0, max(0.55, self.zoom * factor))
        self.redraw()
        return "break"
