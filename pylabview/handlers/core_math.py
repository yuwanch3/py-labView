from __future__ import annotations

import math

from ..execution import CancelledError
from .api import HandlerContext
from .registry import BUILTIN_HANDLERS as registry


@registry.register("numeric_constant", "string_constant", "boolean_constant", "array_constant")
def constant(context: HandlerContext):
    return context.controls.get(context.node.id, context.node.properties.get("value"))


@registry.register("bytes_constant")
def bytes_constant(context: HandlerContext):
    return bytes.fromhex(str(context.node.properties.get("hex", "")))


@registry.register("add", "subtract", "multiply", "divide", "numeric_min", "numeric_max")
def binary_numeric(context: HandlerContext):
    kind = context.node.type
    a, b = context.inputs["a"], context.inputs["b"]
    if kind == "divide" and b == 0:
        from ..runtime import DataflowError
        raise DataflowError("division by zero")
    operations = {
        "add": lambda: a + b,
        "subtract": lambda: a - b,
        "multiply": lambda: a * b,
        "divide": lambda: a / b,
        "numeric_min": lambda: min(a, b),
        "numeric_max": lambda: max(a, b),
    }
    return operations[kind]()


@registry.register("absolute")
def absolute(context: HandlerContext):
    return abs(context.inputs["x"])


@registry.register("sine")
def sine(context: HandlerContext):
    return math.sin(float(context.inputs["x"]))


@registry.register("compare")
def compare(context: HandlerContext):
    operators = {
        ">": lambda a, b: a > b,
        "<": lambda a, b: a < b,
        "==": lambda a, b: a == b,
        ">=": lambda a, b: a >= b,
        "<=": lambda a, b: a <= b,
        "!=": lambda a, b: a != b,
    }
    operator = context.node.properties.get("operator", ">")
    if operator not in operators:
        from ..runtime import DataflowError
        raise DataflowError(f"unsupported comparison: {operator}")
    return operators[operator](context.inputs["a"], context.inputs["b"])


@registry.register("select")
def select(context: HandlerContext):
    return context.inputs["true"] if context.inputs["condition"] else context.inputs["false"]


@registry.register("boolean_and", "boolean_or")
def binary_boolean(context: HandlerContext):
    return (context.inputs["a"] and context.inputs["b"] if context.node.type == "boolean_and"
            else context.inputs["a"] or context.inputs["b"])


@registry.register("boolean_not")
def boolean_not(context: HandlerContext):
    return not context.inputs["value"]


@registry.register("string_concat")
def string_concat(context: HandlerContext):
    return context.inputs["a"] + context.inputs["b"]


@registry.register("string_format")
def string_format(context: HandlerContext):
    try:
        return str(context.node.properties.get("template", "{}")).format(context.inputs["value"])
    except (IndexError, KeyError, ValueError) as exc:
        from ..runtime import DataflowError
        raise DataflowError(f"invalid format template: {exc}") from exc


@registry.register("random")
def random_value(context: HandlerContext):
    return context.runtime.rng.random()


@registry.register("timer")
def timer(context: HandlerContext):
    return context.runtime.clock() - context.runtime.started_at


@registry.register("delay")
def delay(context: HandlerContext):
    seconds = float(context.node.properties.get("seconds", 0))
    maximum = float(context.node.properties.get("maximum_seconds", 5))
    if seconds < 0 or seconds > maximum:
        from ..runtime import DataflowError
        raise DataflowError("delay outside configured bound")
    if context.session.token.wait(seconds):
        raise CancelledError("execution cancelled")
    return context.inputs["value"]


@registry.register("timed_loop")
def timed_loop(context: HandlerContext):
    count = context.runtime._bounded_int(context.node, "iterations", 1)
    if count > context.runtime._bounded_int(context.node, "max_iterations", 1000):
        from ..runtime import DataflowError
        raise DataflowError("timed-loop iteration bound exceeded")
    interval = float(context.node.properties.get("interval", 0.01))
    if interval < 0 or interval > 5:
        from ..runtime import DataflowError
        raise DataflowError("timed-loop interval outside bound")
    ticks = []
    for _ in range(count):
        context.session.token.check()
        ticks.append(context.runtime.clock())
        if context.session.token.wait(interval):
            raise CancelledError("execution cancelled")
    return ticks
