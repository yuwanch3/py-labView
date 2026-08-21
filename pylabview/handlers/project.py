from __future__ import annotations

from .api import HandlerContext
from .registry import BUILTIN_HANDLERS as registry


@registry.register("subvi")
def subvi(context: HandlerContext):
    if not context.project:
        from ..runtime import DataflowError
        raise DataflowError("SubVI requires a project")
    target = str(context.node.properties.get("vi_id", ""))
    child = context.runtime.run_project(context.project, target, context.inputs, session=context.session)
    context.session.token.check()
    if child.errors:
        from ..runtime import DataflowError
        raise DataflowError("; ".join(child.errors))
    context.logs.extend(child.logs)
    vi = context.project.vis[target]
    return {terminal.name: child.port_values[(terminal.node_id, terminal.port)] for terminal in vi.connector_outputs}


@registry.register("display", "chart")
def display(context: HandlerContext):
    return context.inputs["value"]


@registry.register("image_display")
def image_display(context: HandlerContext):
    return context.inputs["image"]


@registry.register("log")
def log(context: HandlerContext):
    value = context.inputs["value"]
    context.logs.append(f"{context.node.properties.get('prefix', '')}{value}")
    return value
