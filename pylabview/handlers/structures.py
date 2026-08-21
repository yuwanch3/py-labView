from __future__ import annotations

from .api import HandlerContext
from .registry import BUILTIN_HANDLERS as registry


@registry.register("case")
def legacy_case(context: HandlerContext):
    return context.inputs["true"] if context.inputs["selector"] else context.inputs["false"]


@registry.register("sequence")
def legacy_sequence(context: HandlerContext):
    return context.inputs["second"]


@registry.register("for_loop")
def legacy_for(context: HandlerContext):
    values = context.inputs["array"]
    maximum = context.runtime._bounded_int(context.node, "max_iterations", 1000)
    if len(values) > maximum:
        from ..runtime import DataflowError
        raise DataflowError("for-loop iteration bound exceeded")
    operation = context.node.properties.get("operation", "identity")
    scale = float(context.node.properties.get("scale", 1))
    if operation not in ("identity", "abs", "scale"):
        from ..runtime import DataflowError
        raise DataflowError("unsupported for-loop operation")
    return [item if operation == "identity" else abs(item) if operation == "abs" else item * scale
            for item in values]


@registry.register("while_loop")
def legacy_while(context: HandlerContext):
    value, count = float(context.inputs["initial"]), 0
    maximum = context.runtime._bounded_int(context.node, "max_iterations", 100)
    limit = float(context.node.properties.get("limit", 10))
    step = float(context.node.properties.get("step", 1))
    condition = context.node.properties.get("condition", "less_than")
    predicates = {"less_than": lambda x: x < limit, "greater_than": lambda x: x > limit}
    if condition not in predicates:
        from ..runtime import DataflowError
        raise DataflowError("unsupported while-loop condition")
    while predicates[condition](value) and count < maximum:
        value, count = value + step, count + 1
    if predicates[condition](value):
        from ..runtime import DataflowError
        raise DataflowError("while-loop iteration bound reached")
    return value


@registry.register("structure_input")
def structure_input(context: HandlerContext):
    return context.controls.get(context.node.id, context.controls.get(str(context.node.properties.get("name", "value"))))


@registry.register("iteration_terminal")
def iteration_terminal(context: HandlerContext):
    return context.controls.get(context.node.id, context.controls.get("iteration", 0))


@registry.register("structure_output")
def structure_output(context: HandlerContext):
    return context.inputs["value"]


@registry.register("feedback")
def feedback(context: HandlerContext):
    key = f"feedback:{context.caller_vi or 'graph'}:{context.graph_scope}:{context.node.id}"
    return context.session.state.get(key, context.node.properties.get("initial", 0.0))


@registry.register("visual_case")
def visual_case(context: HandlerContext):
    key = "true_diagram" if context.inputs["selector"] else "false_diagram"
    diagram_id = str(context.node.properties.get(key, ""))
    return context.runtime._run_structure(context.project, context.caller_vi, diagram_id,
                                          context.inputs["value"], 0, context.session)


@registry.register("visual_for")
def visual_for(context: HandlerContext):
    values = context.inputs["array"]
    maximum = context.runtime._bounded_int(context.node, "max_iterations", 1000)
    if len(values) > maximum:
        from ..runtime import DataflowError
        raise DataflowError("visual for-loop iteration bound exceeded")
    diagram_id = str(context.node.properties.get("body_diagram", ""))
    return [context.runtime._run_structure(context.project, context.caller_vi, diagram_id,
                                           value, index, context.session)
            for index, value in enumerate(values)]
