from __future__ import annotations

from ..typesystem import Waveform
from .api import HandlerContext
from .registry import BUILTIN_HANDLERS as registry


@registry.register("array_build")
def array_build(context: HandlerContext):
    a, b = context.inputs["a"], context.inputs["b"]
    return (list(a) if isinstance(a, list) else [a]) + (list(b) if isinstance(b, list) else [b])


@registry.register("array_index")
def array_index(context: HandlerContext):
    index = int(context.inputs["index"])
    if index != context.inputs["index"]:
        from ..runtime import DataflowError
        raise DataflowError("array index must be an integer")
    try:
        return context.inputs["array"][index]
    except IndexError as exc:
        from ..runtime import DataflowError
        raise DataflowError("array index out of range") from exc


@registry.register("array_size")
def array_size(context: HandlerContext):
    return len(context.inputs["array"])


@registry.register("cluster_bundle")
def cluster_bundle(context: HandlerContext):
    return {
        str(context.node.properties.get("name_a", "a")): context.inputs["a"],
        str(context.node.properties.get("name_b", "b")): context.inputs["b"],
    }


@registry.register("cluster_unbundle")
def cluster_unbundle(context: HandlerContext):
    names = (str(context.node.properties.get("name_a", "a")),
             str(context.node.properties.get("name_b", "b")))
    try:
        return {"a": context.inputs["cluster"][names[0]], "b": context.inputs["cluster"][names[1]]}
    except KeyError as exc:
        from ..runtime import DataflowError
        raise DataflowError(f"cluster field missing: {exc.args[0]}") from exc


@registry.register("waveform_create")
def waveform_create(context: HandlerContext):
    return Waveform(float(context.inputs["t0"]), float(context.inputs["dt"]), list(context.inputs["y"]))


@registry.register("waveform_stats")
def waveform_stats(context: HandlerContext):
    values = context.inputs["waveform"].y
    if not values:
        from ..runtime import DataflowError
        raise DataflowError("waveform has no samples")
    return {"min": min(values), "max": max(values), "mean": sum(values) / len(values)}
