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

        # Operate-mode live Picture Oil optimization.
        #
        # The live oil image gets its own persistent Canvas image item so a
        # full Front Panel redraw does not have to destroy/recreate that image
        # object on every runtime refresh. Other image indicators keep their
        # existing behaviour for now.
        self._persistent_image_refs: dict[str, tk.PhotoImage] = {}
        self._persistent_image_items: dict[str, int] = {}
        self._persistent_image_sources: dict[str, ImageFrame] = {}

        # Operate-mode table cache. Measurement rows usually change only
        # when a stage is completed, not on every live camera refresh.
        self._persistent_table_signatures: dict[str, tuple[tuple[str, ...], ...]] = {}
        self._persistent_table_scaled = False

        # Operate-mode persistent rendering for five explicitly selected,
        # non-safety Front Panel widgets only:
        # RPM ACT, PWM ACT, WIFI IP / Camera URL, TIME(s) #1, TIME(s) #2.
        #
        # These Canvas items survive normal runtime redraws. Their displayed
        # text is updated only when its formatted value changes.
        self._fast_display_node_ids = {
            "rpm_display",
            "pwm_display",
            "time_display_1",
            "time_display_2",
            "wifi",
            "wifi_ip",
        }
        self._persistent_fast_display_tags: dict[str, str] = {}
        self._persistent_fast_display_text_items: dict[str, int] = {}
        self._persistent_fast_display_values: dict[str, str] = {}
        self._persistent_fast_display_scaled = False

        self._drag: tuple[str, float, float, dict[str, float], bool] | None = None
        self._open_dropdown_id: str | None = None
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
        self.bind("<MouseWheel>", self._vertical_wheel)
        self.bind("<Button-4>", lambda _event: self._scroll_vertical(-1))
        self.bind("<Button-5>", lambda _event: self._scroll_vertical(1))
        self.bind("<Configure>", lambda _event: self.redraw())
        self._initialize_values()
        self.redraw()

    def set_document(self, graph: Graph, panel: dict[str, Any]) -> None:
        if graph is not self.graph:
            self.values.clear()
            self.chart_history.clear()

        self.delete("persistent_image")
        self._persistent_image_refs.clear()
        self._persistent_image_items.clear()
        self._persistent_image_sources.clear()

        self.delete("persistent_table")
        self._persistent_table_signatures.clear()
        self._persistent_table_scaled = False

        self.delete("persistent_fast_display")
        self._persistent_fast_display_tags.clear()
        self._persistent_fast_display_text_items.clear()
        self._persistent_fast_display_values.clear()
        self._persistent_fast_display_scaled = False

        self.graph = graph
        self.panel = _normalized_panel(panel, graph)
        self.selected_id = None
        self._open_dropdown_id = None
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
        self._open_dropdown_id = None

        if mode == "edit":
            self.delete("persistent_image")
            self._persistent_image_refs.clear()
            self._persistent_image_items.clear()
            self._persistent_image_sources.clear()

            self.delete("persistent_table")
            self._persistent_table_signatures.clear()
            self._persistent_table_scaled = False

            self.delete("persistent_fast_display")
            self._persistent_fast_display_tags.clear()
            self._persistent_fast_display_text_items.clear()
            self._persistent_fast_display_values.clear()
            self._persistent_fast_display_scaled = False

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

    def sync_control_value_from_model(self, node_id: str, value: Any) -> bool:
        """Replace a cached control override after an explicit model edit.

        Ordinary redraws preserve values entered in Operate mode. Properties
        Apply is different: it deliberately establishes a new model value, so
        the cache passed to Run Once must follow that value rather than silently
        overriding it with the pre-edit state.
        """
        if any(item["terminal_node_id"] == node_id and item["kind"].endswith("control")
               for item in self.panel["items"]):
            self.values[node_id] = value
            return True
        return False

    def update_values(self, values: dict[str, Any]) -> None:
        self.values.update(values)

        for item in self.panel["items"]:
            node_id = item["terminal_node_id"]
            if item["kind"] == "chart" and node_id in values:
                limit = int(self.graph.nodes[node_id].properties.get("history", 100))
                self.chart_history[node_id] = update_chart_history(
                    self.chart_history.get(node_id, []), values[node_id], limit)

        # Picture Oil is the high-frequency live camera indicator.
        oil_picture = values.get("oil_picture")

        if (
            self.mode == "operate"
            and isinstance(oil_picture, ImageFrame)
        ):
            self._update_persistent_picture(
                "oil_picture",
                oil_picture,
            )

        # Picture Comparison is normally frozen. Keep it persistent too,
        # but rebuild its PhotoImage only when the ImageFrame object changes.
        wire_picture = values.get("wire_picture")

        if (
            self.mode == "operate"
            and isinstance(wire_picture, ImageFrame)
        ):
            wire_item = self._image_item_for_node(
                "wire_picture"
            )

            if wire_item is not None:
                previous_source = self._persistent_image_sources.get(
                    wire_item["id"]
                )

                if previous_source is not wire_picture:
                    self._update_persistent_picture(
                        "wire_picture",
                        wire_picture,
                    )

        if (
            self.mode == "operate"
            and "table_display" in values
        ):
            self._update_persistent_table(
                "table_display",
                self.values.get("table_display"),
            )

        self.redraw()

    def _is_fast_display_item(
        self,
        item: dict[str, Any],
    ) -> bool:
        return (
            self.mode == "operate"
            and item["terminal_node_id"] in self._fast_display_node_ids
        )

    def _update_persistent_fast_display(
        self,
        item: dict[str, Any],
    ) -> bool:
        """Create/update one of the five requested persistent display widgets."""

        if not self._is_fast_display_item(
            item
        ):
            return False

        item_id = item["id"]
        node_id = item["terminal_node_id"]
        bounds = item["bounds"]
        x = bounds["x"]
        y = bounds["y"]
        w = bounds["width"]
        h = bounds["height"]
        label = item["properties"].get(
            "label",
            item["kind"].replace("_", " ").title(),
        )

        value = self.values.get(
            node_id,
            "--",
        )
        value = self._display_value(
            node_id,
            value,
        )
        displayed = self._format(
            value
        )

        persistent_tag = f"persistent_fast_display:{item_id}"
        panel_tag = f"panel:{item_id}"

        if item_id not in self._persistent_fast_display_tags:
            self.create_rectangle(
                x,
                y,
                x + w,
                y + h,
                fill="#f7f7f7",
                outline="#777",
                width=1,
                tags=(
                    "persistent_fast_display",
                    persistent_tag,
                    panel_tag,
                ),
            )

            self.create_text(
                x + 8,
                y + 10,
                text=label,
                anchor="w",
                font=self._font(
                    9,
                    bold=True,
                ),
                tags=(
                    "persistent_fast_display",
                    persistent_tag,
                    panel_tag,
                ),
            )

            if node_id in {"wifi", "wifi_ip"}:
                text_item = self.create_text(
                    x + 10,
                    y + h / 2 + 10,
                    text=displayed,
                    anchor="w",
                    justify="left",
                    width=max(
                        w - 20,
                        20,
                    ),
                    font=self._font(
                        10,
                        family="TkFixedFont",
                        bold=True,
                    ),
                    tags=(
                        "persistent_fast_display",
                        persistent_tag,
                        panel_tag,
                    ),
                )
            else:
                text_item = self.create_text(
                    x + w / 2,
                    y + h / 2 + 10,
                    text=displayed,
                    fill="#000000",
                    font=self._font(
                        13,
                        family="TkFixedFont",
                        bold=True,
                    ),
                    tags=(
                        "persistent_fast_display",
                        persistent_tag,
                        panel_tag,
                    ),
                )

            self._persistent_fast_display_tags[item_id] = persistent_tag
            self._persistent_fast_display_text_items[item_id] = text_item
            self._persistent_fast_display_values[item_id] = displayed

            return True

        if (
            self._persistent_fast_display_values.get(
                item_id
            )
            != displayed
        ):
            text_item = self._persistent_fast_display_text_items.get(
                item_id
            )

            if text_item is not None:
                self.itemconfigure(
                    text_item,
                    text=displayed,
                )

            self._persistent_fast_display_values[item_id] = displayed

        return True

    def _image_item_for_node(
        self,
        node_id: str,
    ) -> dict[str, Any] | None:
        return next(
            (
                entry
                for entry in self.panel["items"]
                if (
                    entry["kind"] == "image_indicator"
                    and entry["terminal_node_id"] == node_id
                )
            ),
            None,
        )

    def _update_persistent_picture(
        self,
        node_id: str,
        value: ImageFrame,
    ) -> bool:
        """Update a persistent image indicator without rebuilding its Canvas item."""

        item = self._image_item_for_node(
            node_id
        )

        if item is None:
            return False

        bounds = item["bounds"]
        x = bounds["x"]
        y = bounds["y"]
        w = bounds["width"]
        h = bounds["height"]
        tag = f"panel:{item['id']}"

        try:
            image = tk.PhotoImage(
                data=image_to_ppm(value),
                format="PPM",
            )

            scale = max(
                1,
                math.ceil(
                    max(
                        image.width()
                        / max((w - 12) * self.zoom, 1),
                        image.height()
                        / max((h - 30) * self.zoom, 1),
                    )
                ),
            )

            if scale > 1:
                image = image.subsample(
                    scale,
                    scale,
                )

            self._persistent_image_refs[item["id"]] = image
            self._persistent_image_sources[item["id"]] = value

            canvas_image_id = self._persistent_image_items.get(
                item["id"]
            )

            if canvas_image_id is None:
                canvas_image_id = self.create_image(
                    x + w / 2,
                    y + h / 2 + 10,
                    image=image,
                    tags=("persistent_image", tag),
                )
                self._persistent_image_items[item["id"]] = canvas_image_id
            else:
                self.coords(
                    canvas_image_id,
                    x + w / 2,
                    y + h / 2 + 10,
                )
                self.itemconfigure(
                    canvas_image_id,
                    image=image,
                )

            self.tag_raise(
                canvas_image_id
            )

            return True

        except (TypeError, ValueError, tk.TclError):
            return False

    def _table_item_for_node(
        self,
        node_id: str,
    ) -> dict[str, Any] | None:
        return next(
            (
                entry
                for entry in self.panel["items"]
                if (
                    entry["properties"].get("display_type") == "table"
                    and entry["terminal_node_id"] == node_id
                )
            ),
            None,
        )

    def _table_signature(
        self,
        value: Any,
    ) -> tuple[tuple[str, ...], ...]:
        rows = table_rows(
            value
        )
        return tuple(
            tuple(
                self._format(cell)
                for cell in row
            )
            for row in rows
        )

    def _update_persistent_table(
        self,
        node_id: str,
        value: Any,
    ) -> bool:
        """Rebuild a persistent table only when its displayed content changes."""

        item = self._table_item_for_node(
            node_id
        )

        if item is None:
            return False

        signature = self._table_signature(
            value
        )

        item_id = item["id"]

        if (
            self._persistent_table_signatures.get(item_id)
            == signature
        ):
            return True

        table_tag = f"persistent_table:{item_id}"

        self.delete(
            table_tag
        )

        rows = table_rows(
            value
        )

        if rows:
            bounds = item["bounds"]
            x = bounds["x"]
            y = bounds["y"]
            w = bounds["width"]
            h = bounds["height"]

            columns = max(
                len(row)
                for row in rows
            )
            cell_w = (w - 12) / max(columns, 1)
            cell_h = min(
                28,
                (h - 28) / max(len(rows), 1),
            )

            for row_index, row in enumerate(
                rows[:10]
            ):
                for column_index, cell in enumerate(
                    row
                ):
                    x0 = x + 6 + column_index * cell_w
                    y0 = y + 24 + row_index * cell_h

                    self.create_rectangle(
                        x0,
                        y0,
                        x0 + cell_w,
                        y0 + cell_h,
                        outline="#aaa",
                        tags=(
                            "persistent_table",
                            table_tag,
                        ),
                    )

                    self.create_text(
                        x0 + cell_w / 2,
                        y0 + cell_h / 2,
                        text=self._format(cell)[:16],
                        font=self._font(
                            8,
                            family="TkFixedFont",
                        ),
                        tags=(
                            "persistent_table",
                            table_tag,
                        ),
                    )

        self._persistent_table_signatures[item_id] = signature
        self._persistent_table_scaled = False

        self.tag_raise(
            "persistent_table"
        )

        return True

    def redraw(self) -> None:
        # Persistent table items survive redraw(). If the canvas is zoomed,
        # they were already scaled by the previous redraw. Restore them to
        # document coordinates first so the global zoom below is applied
        # exactly once instead of compounding on every refresh.
        if (
            self.zoom != 1.0
            and self._persistent_table_scaled
        ):
            self.scale(
                "persistent_table",
                0,
                0,
                1.0 / self.zoom,
                1.0 / self.zoom,
            )
            self._persistent_table_scaled = False

        # Persistent fast-display items also survive redraw(). If the canvas
        # is zoomed, they were already scaled by the previous redraw. Restore
        # them to document coordinates first so zoom is applied exactly once
        # instead of compounding on every click/runtime refresh.
        if (
            self.zoom != 1.0
            and self._persistent_fast_display_scaled
        ):
            self.scale(
                "persistent_fast_display",
                0,
                0,
                1.0 / self.zoom,
                1.0 / self.zoom,
            )
            self._persistent_fast_display_scaled = False

        # Keep persistent live image Canvas items alive. The five explicitly
        # selected fast-display widgets also survive normal Operate-mode
        # redraws. Everything else keeps the existing redraw behaviour.
        self.delete("panel_item")
        self.delete("grid")
        self.delete("dropdown_menu")
        self.delete("resize")
        self._image_refs.clear()

        width, height = int(self.panel["canvas"]["width"]), int(self.panel["canvas"]["height"])

        if self.mode == "edit":
            for x in range(0, width + 1, self.grid_size):
                self.create_line(x, 0, x, height, fill="#d3d3d3", tags="grid")
            for y in range(0, height + 1, self.grid_size):
                self.create_line(0, y, width, y, fill="#d3d3d3", tags="grid")

        for item in sorted(self.panel["items"], key=lambda entry: entry["z_index"]):
            if self._is_fast_display_item(
                item
            ):
                self._update_persistent_fast_display(
                    item
                )
            else:
                self._draw_item(
                    item
                )

        if self.zoom != 1.0:
            self.scale("all", 0, 0, self.zoom, self.zoom)

            if self.find_withtag("persistent_table"):
                self._persistent_table_scaled = True

            if self.find_withtag("persistent_fast_display"):
                self._persistent_fast_display_scaled = True

        self.configure(
            scrollregion=(
                0,
                0,
                width * self.zoom,
                height * self.zoom,
            )
        )

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
        value = self._display_value(node_id, value)
        kind = item["kind"]
        display_type = item["properties"].get("display_type", "")
        enabled, read_only = self._control_state(node_id)

        if kind.endswith("control") and not enabled:
            self.create_rectangle(
                x + 1,
                y + 1,
                x + w - 1,
                y + h - 1,
                fill="#d9d9d9",
                outline="",
                tags=("panel_item", tag),
            )
            self.create_text(
                x + 8,
                y + 10,
                text=label,
                anchor="w",
                fill="#777777",
                font=self._font(9, bold=True),
                tags=("panel_item", tag),
            )
        if kind == "image_indicator" and isinstance(value, ImageFrame):
            try:
                if (
                    self.mode == "operate"
                    and node_id in {"oil_picture", "wire_picture"}
                ):
                    canvas_image_id = self._persistent_image_items.get(
                        item["id"]
                    )

                    # Runtime update_values() refreshes Picture Oil every
                    # incoming frame and Picture Comparison only when its
                    # frozen ImageFrame changes. redraw() just reuses it.
                    if canvas_image_id is None:
                        if not self._update_persistent_picture(
                            node_id,
                            value,
                        ):
                            raise ValueError(
                                f"unable to update {node_id}"
                            )

                        canvas_image_id = (
                            self._persistent_image_items.get(
                                item["id"]
                            )
                        )

                    if canvas_image_id is not None:
                        self.coords(
                            canvas_image_id,
                            x + w / 2,
                            y + h / 2 + 10,
                        )
                        self.tag_raise(
                            canvas_image_id
                        )

                else:
                    image = tk.PhotoImage(
                        data=image_to_ppm(value),
                        format="PPM",
                    )

                    scale = max(
                        1,
                        math.ceil(
                            max(
                                image.width()
                                / max((w - 12) * self.zoom, 1),
                                image.height()
                                / max((h - 30) * self.zoom, 1),
                            )
                        ),
                    )

                    if scale > 1:
                        image = image.subsample(
                            scale,
                            scale,
                        )

                    self._image_refs[item["id"]] = image

                    self.create_image(
                        x + w / 2,
                        y + h / 2 + 10,
                        image=image,
                        tags=("panel_item", tag),
                    )

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
            if (
                self.mode == "operate"
                and node_id == "table_display"
            ):
                self._update_persistent_table(
                    node_id,
                    value,
                )
                self.tag_raise(
                    "persistent_table"
                )
            else:
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
            field_left = x + 8
            field_top = y + h / 2 - 8
            field_right = x + w - 8
            field_bottom = y + h / 2 + 20
            field_fill = "white" if enabled else "#d9d9d9"
            text_fill = "#000000" if enabled else "#777777"
            self.create_rectangle(field_left, field_top, field_right, field_bottom,
                                  fill=field_fill, outline="#555", tags=("panel_item", tag))
            self.create_text(x + 14, y + h / 2 + 6, text=self._format(value), anchor="w",
                             width=max(w - 52, 20), fill=text_fill,
                             font=self._font(10), tags=("panel_item", tag))
            self.create_text(x + w - 20, y + h / 2 + 6,
                             text="▲" if enabled and self._open_dropdown_id == item["id"] else "▼",
                             fill=text_fill, font=self._font(10), tags=("panel_item", tag))
            if self.mode == "operate" and enabled and self._open_dropdown_id == item["id"]:
                options = self._dropdown_options(item)
                row_height = 28
                if options:
                    list_top = field_bottom
                    list_bottom = list_top + row_height * len(options)
                    self.create_rectangle(field_left, list_top, field_right, list_bottom,
                                          fill="white", outline="#555", tags=("dropdown_menu", tag))
                    for index, option in enumerate(options):
                        y0 = list_top + index * row_height
                        y1 = y0 + row_height
                        if index:
                            self.create_line(field_left, y0, field_right, y0,
                                             fill="#dddddd", tags=("dropdown_menu", tag))
                        self.create_text(field_left + 8, (y0 + y1) / 2,
                                         text=option, anchor="w", width=max(w - 32, 20),
                                         font=self._font(10), tags=("dropdown_menu", tag))
                elif node_id == "com":
                    list_top = field_bottom
                    self.create_rectangle(field_left, list_top, field_right, list_top + row_height,
                                          fill="white", outline="#555", tags=("dropdown_menu", tag))
                    self.create_text(field_left + 8, list_top + row_height / 2,
                                     text="No COM device detected", anchor="w",
                                     width=max(w - 32, 20), font=self._font(9), fill="#777777",
                                     tags=("dropdown_menu", tag))
        elif kind == "boolean_control" or (kind == "indicator" and isinstance(value, bool)):
            active = bool(value)

            # Global STOP uses a red active indicator. Other boolean controls
            # keep their existing green active / dark inactive appearance.
            active_fill = (
                "#d93025"
                if node_id == "global_stop"
                else "#35b85a"
            )

            self.create_oval(x + w / 2 - 18, y + h / 2 - 10, x + w / 2 + 18, y + h / 2 + 26,
                             fill=active_fill if active else "#555", outline="#222", tags=("panel_item", tag))
        elif kind == "chart":
            numbers = self.chart_history.get(node_id, [])

            # Plot area margins leave room for LabVIEW-style
            # numeric X/Y ticks and axis labels.
            plot_left = x + 38
            plot_right = x + w - 10
            plot_top = y + 28
            plot_bottom = y + h - 34

            x_min = float(item["properties"].get("x_min", 0))
            x_max = float(item["properties"].get("x_max", 500))
            y_min = float(item["properties"].get("y_min", 0))
            y_max = float(item["properties"].get("y_max", 300))

            if x_max <= x_min:
                x_max = x_min + 1.0
            if y_max <= y_min:
                y_max = y_min + 1.0

            # Draw five equal intervals on both axes, matching the
            # original LabVIEW chart appearance without changing data.
            tick_count = 5

            for index in range(tick_count + 1):
                fraction = index / tick_count

                grid_x = (
                    plot_left
                    + fraction
                    * (plot_right - plot_left)
                )
                x_value = (
                    x_min
                    + fraction
                    * (x_max - x_min)
                )

                self.create_line(
                    grid_x,
                    plot_top,
                    grid_x,
                    plot_bottom,
                    fill="#d0d0d0",
                    width=1,
                    tags=("panel_item", tag),
                )
                self.create_text(
                    grid_x,
                    plot_bottom + 10,
                    text=self._format(x_value),
                    anchor="n",
                    font=self._font(7),
                    tags=("panel_item", tag),
                )

            for index in range(tick_count + 1):
                fraction = index / tick_count

                grid_y = (
                    plot_bottom
                    - fraction
                    * (plot_bottom - plot_top)
                )
                y_value = (
                    y_min
                    + fraction
                    * (y_max - y_min)
                )

                self.create_line(
                    plot_left,
                    grid_y,
                    plot_right,
                    grid_y,
                    fill="#d0d0d0",
                    width=1,
                    tags=("panel_item", tag),
                )
                self.create_text(
                    plot_left - 5,
                    grid_y,
                    text=self._format(y_value),
                    anchor="e",
                    font=self._font(7),
                    tags=("panel_item", tag),
                )

            # Plot border / axes.
            self.create_rectangle(
                plot_left,
                plot_top,
                plot_right,
                plot_bottom,
                outline="#777777",
                width=1,
                tags=("panel_item", tag),
            )

            # Preserve the existing chart-data behavior:
            # values are still normalized to their current low/high
            # range, only the surrounding LabVIEW-style axes/grid are new.
            if len(numbers) > 1:
                low = min(numbers)
                high = max(numbers)
                span = high - low or 1

                points: list[float] = []

                for index, number in enumerate(numbers):
                    points.extend(
                        (
                            plot_left
                            + index
                            * (plot_right - plot_left)
                            / (len(numbers) - 1),
                            plot_bottom
                            - (number - low)
                            / span
                            * (plot_bottom - plot_top),
                        )
                    )

                self.create_line(
                    *points,
                    fill="#00866a",
                    width=2,
                    tags=("panel_item", tag),
                )

            self.create_text(
                (plot_left + plot_right) / 2,
                y + h - 4,
                text=item["properties"].get(
                    "x_label",
                    "Baris Pixel",
                ),
                anchor="s",
                font=self._font(7),
                tags=("panel_item", tag),
            )
            self.create_text(
                x + 8,
                (plot_top + plot_bottom) / 2,
                text=item["properties"].get(
                    "y_label",
                    "Intensitas (Threshold)",
                ),
                anchor="w",
                angle=90,
                font=self._font(7),
                tags=("panel_item", tag),
            )
        elif kind == "string_control" and node_id == "wifi_ip":
            self.create_text(
                x + 10,
                y + h / 2 + 10,
                text=self._format(value),
                anchor="w",
                justify="left",
                width=max(w - 20, 20),
                font=self._font(10, family="TkFixedFont", bold=True),
                tags=("panel_item", tag),
            )
        else:
            text_fill = "#000000" if enabled else "#777777"
            self.create_text(x + w / 2, y + h / 2 + 10, text=self._format(value),
                             fill=text_fill,
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

    def _density_mode(self) -> str:
        return str(self.values.get("density_mode", "Manual Δρ")).strip()

    def _control_state(self, node_id: str) -> tuple[bool, bool]:
        """Return (enabled, read_only) for Front Panel controls."""
        density_detail_nodes = {
            "fluid_1",
            "density_1",
            "fluid_2",
            "density_2",
        }

        mode = self._density_mode()

        if node_id in density_detail_nodes and mode == "Manual Δρ":
            return False, False

        if mode == "Template":
            if node_id == "density_input":
                return True, True

            if node_id == "density_1":
                fluid_1 = str(self.values.get("fluid_1", "")).strip()
                return True, fluid_1 in {"Water", "Oil"}

            if node_id == "density_2":
                fluid_2 = str(self.values.get("fluid_2", "")).strip()
                return True, fluid_2 in {"Water", "Oil"}

        return True, False

    def _effective_density_delta(self) -> float | None:
        """Mirror the active Template Δρ for Front Panel display only."""
        templates = {
            "Water": 1000.0,
            "Oil": 850.0,
        }

        def resolve(fluid_id: str, density_id: str) -> float | None:
            fluid = str(self.values.get(fluid_id, "")).strip()

            if fluid in templates:
                return templates[fluid]

            if fluid != "Custom":
                return None

            try:
                value = float(self.values.get(density_id, 0.0))
            except (TypeError, ValueError):
                return None

            if not math.isfinite(value) or value <= 0.0:
                return None

            return value

        first = resolve("fluid_1", "density_1")
        second = resolve("fluid_2", "density_2")

        if first is None or second is None:
            return None

        return abs(first - second)

    def _display_value(self, node_id: str, value: Any) -> Any:
        if self._density_mode() == "Template":
            templates = {
                "Water": 1000.0,
                "Oil": 850.0,
            }

            if node_id == "density_input":
                effective = self._effective_density_delta()
                return "--" if effective is None else effective

            if node_id == "density_1":
                fluid_1 = str(self.values.get("fluid_1", "")).strip()
                if fluid_1 in templates:
                    return templates[fluid_1]

            if node_id == "density_2":
                fluid_2 = str(self.values.get("fluid_2", "")).strip()
                if fluid_2 in templates:
                    return templates[fluid_2]

        return value

    @staticmethod
    def _serial_ports() -> list[str]:
        """Return currently detected serial COM ports."""
        try:
            from serial.tools import list_ports
        except ImportError:
            return []
        return [port.device for port in list_ports.comports() if getattr(port, "device", None)]

    def _dropdown_options(self, item: dict[str, Any]) -> list[str]:
        node_id = item["terminal_node_id"]
        if node_id == "com":
            return self._serial_ports()
        raw_options = item["properties"].get("options") or []
        options: list[str] = []
        for option in raw_options:
            if isinstance(option, dict):
                options.append(str(option.get("label", option.get("value", ""))))
            else:
                options.append(str(option))
        return options

    def _select_dropdown_value(self, node_id: str, value: str) -> None:
        self.values[node_id] = value
        self._open_dropdown_id = None
        self.redraw()
        self.on_value_change(self.control_values())

    def _dropdown_choice_at(self, item: dict[str, Any], x: float, y: float) -> str | None:
        b = item["bounds"]
        left = b["x"] + 8
        right = b["x"] + b["width"] - 8
        top = b["y"] + b["height"] / 2 + 20
        row_height = 28
        options = self._dropdown_options(item)
        if not (left <= x <= right and top <= y <= top + row_height * len(options)):
            return None
        index = int((y - top) // row_height)
        return options[index] if 0 <= index < len(options) else None

    def _item_at(self, x: float, y: float) -> tuple[dict[str, Any] | None, bool]:
        for item in reversed(sorted(self.panel["items"], key=lambda entry: entry["z_index"])):
            b = item["bounds"]
            if b["x"] <= x <= b["x"] + b["width"] and b["y"] <= y <= b["y"] + b["height"]:
                resize = x >= b["x"] + b["width"] - 12 and y >= b["y"] + b["height"] - 12
                return item, resize
        return None, False

    def _press(self, event: tk.Event) -> None:
        x, y = self._document_point(event)
        if self.mode == "operate" and self._open_dropdown_id is not None:
            open_item = next((entry for entry in self.panel["items"] if entry["id"] == self._open_dropdown_id), None)
            if open_item is not None:
                choice = self._dropdown_choice_at(open_item, x, y)
                if choice is not None:
                    self._select_dropdown_value(open_item["terminal_node_id"], choice)
                    return
        item, resize = self._item_at(x, y)
        if not item:
            self.selected_id = None
            self._open_dropdown_id = None
            self.redraw()
            return
        node_id = item["terminal_node_id"]
        if self.mode == "operate":
            enabled, read_only = self._control_state(node_id)

            if not enabled or read_only:
                self._open_dropdown_id = None
                self.redraw()
                return

            if item["kind"] == "boolean_control":
                if item["properties"].get("display_type") == "radio_start_stop":
                    midpoint = item["bounds"]["x"] + item["bounds"]["width"] / 2
                    self.values[node_id] = x >= midpoint
                else:
                    self.values[node_id] = not bool(self.values.get(node_id, False))
                self.redraw()
                self.on_value_change(self.control_values())
            elif item["kind"] == "string_control" and item["properties"].get("display_type") == "dropdown":
                self._open_dropdown_id = None if self._open_dropdown_id == item["id"] else item["id"]
                self.redraw()
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
        enabled, read_only = self._control_state(node_id)

        if not enabled or read_only:
            self._open_dropdown_id = None
            self.redraw()
            return

        self._open_dropdown_id = None
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

        # Persistent Picture Oil / Picture Comparison / Table are optimized
        # for normal runtime refreshes and intentionally survive redraw().
        # A zoom change is different: their image subsampling, font sizes,
        # and geometry depend on the current zoom. Rebuild those persistent
        # items once at the new zoom instead of reusing objects created at
        # the previous scale.
        #
        # This happens only when the operator changes zoom, so it does not
        # affect the live runtime performance optimization.
        if hasattr(self, "delete"):
            self.delete("persistent_image")
            self._persistent_image_refs.clear()
            self._persistent_image_items.clear()
            self._persistent_image_sources.clear()

            self.delete("persistent_table")
            self._persistent_table_signatures.clear()
            self._persistent_table_scaled = False

            self.delete("persistent_fast_display")
            self._persistent_fast_display_tags.clear()
            self._persistent_fast_display_text_items.clear()
            self._persistent_fast_display_values.clear()
            self._persistent_fast_display_scaled = False

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

    def _vertical_wheel(self, event: tk.Event) -> str:
        return self._scroll_vertical(-1 if event.delta > 0 else 1)

    def _scroll_vertical(self, direction: int) -> str:
        self.yview_scroll(direction, "units")
        return "break"


FrontPanel = PanelDesigner
