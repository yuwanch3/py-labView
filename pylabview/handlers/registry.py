from __future__ import annotations

from importlib import import_module
from typing import Iterable, Mapping

from .api import NodeHandler


class HandlerRegistry:
    def __init__(self, handlers: Mapping[str, NodeHandler] | None = None) -> None:
        self._handlers: dict[str, NodeHandler] = dict(handlers or {})

    def register(self, *node_types: str):
        if not node_types or any(not node_type for node_type in node_types):
            raise ValueError("handler registration requires a node type")

        def decorator(handler: NodeHandler) -> NodeHandler:
            duplicates = set(node_types) & self._handlers.keys()
            if duplicates:
                raise ValueError(f"node handler is already registered: {sorted(duplicates)[0]}")
            self._handlers.update(dict.fromkeys(node_types, handler))
            return handler

        return decorator

    def resolve(self, node_type: str) -> NodeHandler | None:
        return self._handlers.get(node_type)

    def registered_types(self) -> frozenset[str]:
        return frozenset(self._handlers)

    def handlers(self) -> Mapping[str, NodeHandler]:
        return self._handlers.copy()

    def audit(self, definitions: Iterable[str]) -> tuple[set[str], set[str]]:
        # Plugin node types are required to be namespaced and intentionally use the dynamic fallback.
        expected = {node_type for node_type in definitions if "." not in node_type}
        actual = set(self._handlers)
        return expected - actual, actual - expected


BUILTIN_HANDLERS = HandlerRegistry()

_MODULES = (
    "core_math", "collections", "structures", "sync", "io", "instrumentation",
    "vision", "network", "project", "spinning_drop", "spinning_drop_manual",
)


def load_builtin_handlers() -> HandlerRegistry:
    for module in _MODULES:
        import_module(f"{__package__}.{module}")
    return BUILTIN_HANDLERS
