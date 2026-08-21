from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, TYPE_CHECKING

if TYPE_CHECKING:
    from ..execution import RunSession
    from ..model import Node, Project
    from ..runtime import DataflowRuntime


@dataclass(frozen=True)
class HandlerContext:
    runtime: "DataflowRuntime"
    node: "Node"
    inputs: dict[str, Any]
    controls: dict[str, Any]
    logs: list[str]
    project: "Project | None"
    caller_vi: str | None
    session: "RunSession"
    graph_scope: str


class NodeHandler(Protocol):
    def __call__(self, context: HandlerContext) -> Any: ...
