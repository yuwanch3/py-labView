from __future__ import annotations

import csv

from ..typesystem import ErrorCluster
from .api import HandlerContext
from .registry import BUILTIN_HANDLERS as registry


@registry.register("analog_input", "daq_finite_input", "digital_input", "analog_output", "digital_output")
def daq(context: HandlerContext):
    return context.runtime._daq(context.node, context.inputs)


@registry.register("file_read")
def file_read(context: HandlerContext):
    try:
        return {"text": context.runtime._safe_path(context.node).read_text(encoding="utf-8"), "error": ErrorCluster()}
    except (OSError, ValueError) as exc:
        return {"text": "", "error": ErrorCluster(True, 20, str(exc))}


@registry.register("file_write")
def file_write(context: HandlerContext):
    try:
        context.runtime._safe_path(context.node).write_text(context.inputs["text"], encoding="utf-8")
        return ErrorCluster()
    except (OSError, ValueError) as exc:
        return ErrorCluster(True, 21, str(exc))


@registry.register("csv_logger")
def csv_logger(context: HandlerContext):
    try:
        path = context.runtime._safe_path(context.node)
        with path.open("a", newline="", encoding="utf-8") as stream:
            csv.writer(stream).writerow([context.inputs["value"]])
        return ErrorCluster()
    except (OSError, ValueError) as exc:
        return ErrorCluster(True, 22, str(exc))


@registry.register("error_constant")
def error_constant(context: HandlerContext):
    return ErrorCluster(bool(context.node.properties.get("status", False)),
                        int(context.node.properties.get("code", 0)),
                        str(context.node.properties.get("source", "")))


@registry.register("error_merge")
def error_merge(context: HandlerContext):
    return context.inputs["a"] if context.inputs["a"].status else context.inputs["b"]


@registry.register("error_handler")
def error_handler(context: HandlerContext):
    error = context.inputs["error"]
    if error.status:
        context.logs.append(f"ERROR {error.code}: {error.source}")
    return {"handled": error.status, "message": error.source if error.status else ""}


@registry.register("report_generate")
def report_generate(context: HandlerContext):
    try:
        path = context.runtime.reports.generate(
            context.inputs["data"], context.runtime._safe_path(context.node),
            str(context.node.properties.get("format", "html")),
            str(context.node.properties.get("title", "PyLabView Report")))
        return {"path": str(path), "error": ErrorCluster()}
    except (OSError, ValueError, RuntimeError, ImportError) as exc:
        return {"path": "", "error": ErrorCluster(True, 50, str(exc))}
