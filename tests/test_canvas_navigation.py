from __future__ import annotations

import unittest
import sys
from types import SimpleNamespace
from types import ModuleType

try:
    import tkinter  # noqa: F401
except ImportError:
    sys.modules.pop("tkinter", None)
    tkinter_stub = ModuleType("tkinter")
    tkinter_stub.Canvas = object
    tkinter_stub.Misc = object
    tkinter_stub.Event = object
    tkinter_stub.PhotoImage = object
    tkinter_stub.TclError = RuntimeError
    simpledialog_stub = ModuleType("tkinter.simpledialog")
    simpledialog_stub.askstring = lambda *_args, **_kwargs: None
    tkinter_stub.simpledialog = simpledialog_stub
    sys.modules["tkinter"] = tkinter_stub
    sys.modules["tkinter.simpledialog"] = simpledialog_stub

from pylabview.canvas_editor import DiagramCanvas
from pylabview.front_panel import PanelDesigner


class _ViewportFake:
    def __init__(self) -> None:
        self.zoom = 1.0
        self.x_offset = 300.0
        self.y_offset = 180.0
        self.x_moves: list[float] = []
        self.y_moves: list[float] = []
        self.scrolls: list[tuple[int, str]] = []
        self.vertical_scrolls: list[tuple[int, str]] = []
        self.redraw_count = 0
        self.panel = {"canvas": {"width": 2400, "height": 1600}}

    def canvasx(self, value: float) -> float:
        return value + self.x_offset

    def canvasy(self, value: float) -> float:
        return value + self.y_offset

    def redraw(self) -> None:
        self.redraw_count += 1

    def bbox(self, _tag: str) -> tuple[int, int, int, int]:
        return (0, 0, 2400, 1600)

    def winfo_width(self) -> int:
        return 800

    def winfo_height(self) -> int:
        return 600

    def xview_moveto(self, fraction: float) -> None:
        self.x_moves.append(fraction)

    def yview_moveto(self, fraction: float) -> None:
        self.y_moves.append(fraction)

    def xview_scroll(self, direction: int, units: str) -> None:
        self.scrolls.append((direction, units))

    def yview_scroll(self, direction: int, units: str) -> None:
        self.vertical_scrolls.append((direction, units))


class CanvasNavigationTests(unittest.TestCase):
    def test_diagram_zoom_is_cursor_anchored_and_clamped(self) -> None:
        canvas = _ViewportFake()
        result = DiagramCanvas._set_zoom(canvas, 1.1, 200, 120)
        self.assertEqual(result, "break")
        self.assertAlmostEqual(canvas.zoom, 1.1)
        self.assertEqual(canvas.redraw_count, 1)
        self.assertAlmostEqual(canvas.x_moves[-1], ((500.0 * 1.1) - 200) / 2400)
        self.assertAlmostEqual(canvas.y_moves[-1], ((300.0 * 1.1) - 120) / 1600)

        canvas.zoom = 2.0
        canvas.redraw_count = 0
        DiagramCanvas._set_zoom(canvas, 1.1, 200, 120)
        self.assertEqual(canvas.zoom, 2.0)
        self.assertEqual(canvas.redraw_count, 0)
        canvas.zoom = 0.55
        DiagramCanvas._set_zoom(canvas, 0.9, 200, 120)
        self.assertEqual(canvas.zoom, 0.55)

    def test_front_panel_zoom_and_document_coordinates(self) -> None:
        panel = _ViewportFake()
        event = SimpleNamespace(x=200, y=120)
        self.assertEqual(PanelDesigner._document_point(panel, event), (500.0, 300.0))

        result = PanelDesigner._set_zoom(panel, 0.9, event.x, event.y)
        self.assertEqual(result, "break")
        self.assertAlmostEqual(panel.zoom, 0.9)
        self.assertEqual(panel.redraw_count, 1)
        self.assertAlmostEqual(panel.x_moves[-1], ((500.0 * 0.9) - 200) / (2400 * 0.9))
        self.assertAlmostEqual(panel.y_moves[-1], ((300.0 * 0.9) - 120) / (1600 * 0.9))
        self.assertAlmostEqual(PanelDesigner._document_point(panel, event)[0], 500.0 / 0.9)
        self.assertEqual(PanelDesigner._font(panel, 10), ("TkDefaultFont", 9))
        self.assertEqual(PanelDesigner._font(panel, 10, family="TkFixedFont", bold=True),
                         ("TkFixedFont", 9, "bold"))

    def test_shift_wheel_scrolls_horizontally_on_both_canvases(self) -> None:
        for canvas_type in (DiagramCanvas, PanelDesigner):
            with self.subTest(canvas=canvas_type.__name__):
                canvas = _ViewportFake()
                self.assertEqual(canvas_type._scroll_horizontal(canvas, -1), "break")
                self.assertEqual(canvas_type._scroll_horizontal(canvas, 1), "break")
                self.assertEqual(canvas.scrolls, [(-1, "units"), (1, "units")])

    def test_plain_wheel_scrolls_vertically_on_both_canvases(self) -> None:
        for canvas_type in (DiagramCanvas, PanelDesigner):
            with self.subTest(canvas=canvas_type.__name__):
                canvas = _ViewportFake()
                self.assertEqual(canvas_type._scroll_vertical(canvas, -1), "break")
                self.assertEqual(canvas_type._scroll_vertical(canvas, 1), "break")
                self.assertEqual(canvas.vertical_scrolls, [(-1, "units"), (1, "units")])

    def test_wheel_direction_matches_common_desktop_convention(self) -> None:
        class WheelFake(_ViewportFake):
            def _set_zoom(self, factor: float, x: int, y: int) -> str:
                self.zoom_request = (factor, x, y)
                return "break"

            def _scroll_horizontal(self, direction: int) -> str:
                self.horizontal_request = direction
                return "break"

            def _scroll_vertical(self, direction: int) -> str:
                self.vertical_request = direction
                return "break"

        event_up = SimpleNamespace(delta=120, x=40, y=50)
        event_down = SimpleNamespace(delta=-120, x=40, y=50)
        for canvas_type in (DiagramCanvas, PanelDesigner):
            with self.subTest(canvas=canvas_type.__name__):
                canvas = WheelFake()
                self.assertEqual(canvas_type._zoom_wheel(canvas, event_up), "break")
                self.assertEqual(canvas.zoom_request, (1.1, 40, 50))
                canvas_type._zoom_wheel(canvas, event_down)
                self.assertEqual(canvas.zoom_request, (0.9, 40, 50))
                canvas_type._horizontal_wheel(canvas, event_up)
                self.assertEqual(canvas.horizontal_request, -1)
                canvas_type._horizontal_wheel(canvas, event_down)
                self.assertEqual(canvas.horizontal_request, 1)
                canvas_type._vertical_wheel(canvas, event_up)
                self.assertEqual(canvas.vertical_request, -1)
                canvas_type._vertical_wheel(canvas, event_down)
                self.assertEqual(canvas.vertical_request, 1)


if __name__ == "__main__":
    unittest.main()
