from __future__ import annotations

from pathlib import Path
import json
import os
import tempfile

from .model import Graph, Project


def _read(path: str | Path) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Project root must be a JSON object")
    return data


def _atomic_json(data: dict, path: str | Path) -> None:
    destination = Path(path)
    if not destination.parent.is_dir():
        raise OSError("project parent directory does not exist")
    descriptor, temporary = tempfile.mkstemp(prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(data, stream, indent=2, ensure_ascii=False, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
    except Exception:
        try: os.unlink(temporary)
        except FileNotFoundError: pass
        raise


def save_project(project: Project, path: str | Path) -> None:
    data = project.to_dict()
    Project.from_dict(data)
    _atomic_json(data, path)


def load_project(path: str | Path) -> Project:
    data = _read(path)
    version = data.get("version")
    if type(version) is int and version == 1:
        return Project.migrate_v1(data)
    if type(version) is int and version == 2:
        return Project.from_dict(data)
    raise ValueError(f"unsupported project version: {version}")


def save_graph(graph: Graph, path: str | Path) -> None:
    """Backward-compatible graph save; new files are v2 single-VI projects."""
    project = Project(graph.name)
    project.main.name = graph.name
    project.main.graph = graph
    project._bind_graphs()
    save_project(project, path)


def load_graph(path: str | Path) -> Graph:
    """Backward-compatible loader returning the main VI graph."""
    return load_project(path).main.graph
