from __future__ import annotations

from pathlib import Path
import json

from .model import Graph


def save_graph(graph: Graph, path: str | Path) -> None:
    Path(path).write_text(json.dumps(graph.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def load_graph(path: str | Path) -> Graph:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Project root must be a JSON object")
    return Graph.from_dict(data)
