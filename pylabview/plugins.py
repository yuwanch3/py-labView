from __future__ import annotations

from dataclasses import dataclass, field
from importlib import metadata
from typing import Any, Callable

from .model import NODE_DEFINITIONS, NodeDefinition


PLUGIN_API_VERSION = 1


@dataclass(frozen=True)
class PluginManifest:
    plugin_id: str
    version: str
    api_version: int = PLUGIN_API_VERSION
    description: str = ""


@dataclass
class PluginStatus:
    plugin_id: str
    version: str = ""
    state: str = "discovered"
    message: str = ""


class PluginRegistry:
    def __init__(self) -> None:
        self.node_definitions: dict[str, NodeDefinition] = dict(NODE_DEFINITIONS)
        self.evaluators: dict[str, Callable[..., Any]] = {}
        self.statuses: list[PluginStatus] = [PluginStatus("builtin", "4.3.2", "active")]
        self.isolated_evaluators: dict[str, tuple[Callable[[Any], Any], float]] = {}
        self._discovered = False

    def register_node(self, type_id: str, definition: NodeDefinition,
                      evaluator: Callable[..., Any] | None = None) -> None:
        if "." not in type_id:
            raise ValueError("plugin node type must be namespaced")
        if type_id in self.node_definitions:
            raise ValueError(f"node type is already registered: {type_id}")
        self.node_definitions[type_id] = definition
        NODE_DEFINITIONS[type_id] = definition
        if evaluator:
            self.evaluators[type_id] = evaluator

    def evaluator(self, type_id: str) -> Callable[..., Any] | None:
        return self.evaluators.get(type_id)

    def register_isolated_evaluator(self, type_id: str, evaluator: Callable[[Any], Any],
                                    timeout: float = 2.0) -> None:
        """Opt in to per-call process isolation for a JSON-only evaluator."""
        if type_id not in self.node_definitions: raise ValueError("isolated evaluator node is not registered")
        if timeout <= 0 or timeout > 300: raise ValueError("isolated evaluator timeout is outside bounds")
        from .integrations.isolation import importable_callable_path
        importable_callable_path(evaluator)
        self.isolated_evaluators[type_id] = (evaluator, float(timeout))

    def isolated(self, type_id: str) -> tuple[Callable[[Any], Any], float] | None:
        return self.isolated_evaluators.get(type_id)

    def discover(self) -> list[PluginStatus]:
        if self._discovered:
            return self.statuses
        self._discovered = True
        try:
            points = metadata.entry_points()
            entries = points.select(group="pylabview.plugins") if hasattr(points, "select") else points.get("pylabview.plugins", [])
        except Exception as exc:
            status = PluginStatus("discovery", state="failed", message=str(exc))
            self.statuses.append(status)
            return self.statuses
        for entry in entries:
            status = PluginStatus(entry.name)
            self.statuses.append(status)
            try:
                plugin = entry.load()()
                manifest = plugin.manifest
                if not isinstance(manifest, PluginManifest):
                    raise TypeError("plugin manifest has an invalid type")
                status.plugin_id, status.version = manifest.plugin_id, manifest.version
                if manifest.api_version != PLUGIN_API_VERSION:
                    status.state = "incompatible"
                    status.message = f"requires plugin API {manifest.api_version}"
                    continue
                plugin.activate(self)
                status.state = "active"
            except Exception as exc:
                status.state = "failed"
                status.message = str(exc)
        return self.statuses


DEFAULT_PLUGIN_REGISTRY = PluginRegistry()


def bootstrap_plugins() -> list[PluginStatus]:
    """Discover trusted installed plugins before deserializing plugin node types."""
    return DEFAULT_PLUGIN_REGISTRY.discover()
