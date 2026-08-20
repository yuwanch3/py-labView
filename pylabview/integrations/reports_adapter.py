from __future__ import annotations

from html import escape
from importlib import import_module
from pathlib import Path
from typing import Any, Callable
import csv
import os
import tempfile


MAX_REPORT_ROWS = 100_000
MAX_REPORT_CELLS = 1_000_000
MAX_REPORT_TEXT_BYTES = 16 * 1024 * 1024


def _rows(data: Any) -> list[list[Any]]:
    if isinstance(data, dict): rows = [[key, value] for key, value in data.items()]
    elif isinstance(data, (list, tuple)):
        rows = [list(item) if isinstance(item, (list, tuple)) else [item] for item in data]
    else: rows = [[data]]
    if len(rows) > MAX_REPORT_ROWS or sum(len(row) for row in rows) > MAX_REPORT_CELLS:
        raise ValueError("report data exceeds row/cell bounds")
    if sum(len(str(cell).encode("utf-8")) for row in rows for cell in row) > MAX_REPORT_TEXT_BYTES:
        raise ValueError("report text exceeds size bound")
    return rows


class ReportsAdapter:
    FORMATS = {"html", "csv", "xlsx", "docx", "pdf"}

    def __init__(self, module_loader: Callable[[str], Any] = import_module) -> None:
        self._load = module_loader

    def availability(self) -> dict[str, bool]:
        result = {"html": True, "csv": True}
        for format_name, module in (("xlsx", "openpyxl"), ("docx", "docx"), ("pdf", "reportlab")):
            try: self._load(module); result[format_name] = True
            except Exception: result[format_name] = False
        return result

    def generate(self, data: Any, destination: Path, format_name: str | None = None,
                 title: str = "PyLabView Report") -> Path:
        format_name = (format_name or destination.suffix.lstrip(".")).lower()
        if format_name not in self.FORMATS: raise ValueError(f"unsupported report format: {format_name}")
        rows = _rows(data)
        descriptor, temporary = tempfile.mkstemp(prefix=f".{destination.name}.", suffix=f".{format_name}", dir=destination.parent)
        os.close(descriptor)
        path = Path(temporary)
        try:
            if format_name == "csv":
                with path.open("w", newline="", encoding="utf-8") as stream: csv.writer(stream).writerows(rows)
            elif format_name == "html":
                body = "".join("<tr>" + "".join(f"<td>{escape(str(cell))}</td>" for cell in row) + "</tr>" for row in rows)
                path.write_text(f"<!doctype html><meta charset=\"utf-8\"><title>{escape(title)}</title><h1>{escape(title)}</h1><table>{body}</table>\n", encoding="utf-8")
            elif format_name == "xlsx":
                workbook = self._load("openpyxl").Workbook(); sheet = workbook.active
                for row in rows: sheet.append(row)
                workbook.save(path)
            elif format_name == "docx":
                document = self._load("docx").Document(); document.add_heading(title, 0)
                table = document.add_table(rows=len(rows), cols=max((len(row) for row in rows), default=1))
                for r, row in enumerate(rows):
                    for c, value in enumerate(row): table.cell(r, c).text = str(value)
                document.save(path)
            else:
                canvas = self._load("reportlab.pdfgen.canvas").Canvas(str(path)); canvas.drawString(72, 800, title)
                y = 780
                for row in rows:
                    canvas.drawString(72, y, " | ".join(str(value) for value in row)[:200]); y -= 14
                    if y < 72: canvas.showPage(); y = 800
                canvas.save()
            os.replace(path, destination)
            return destination
        except Exception:
            try: path.unlink()
            except FileNotFoundError: pass
            raise
