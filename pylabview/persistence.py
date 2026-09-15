from __future__ import annotations

from pathlib import Path
import json
import math
import os
import tempfile

from .model import Graph, Project


def _read(path: str | Path) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"),
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError(f"invalid JSON number: {value}")))
    if not isinstance(data, dict):
        raise ValueError("Project root must be a JSON object")
    _validate_json_numbers(data)
    return data


def _validate_json_numbers(value: object) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("project contains a non-finite number")
    if isinstance(value, dict):
        for child in value.values():
            _validate_json_numbers(child)
    elif isinstance(value, list):
        for child in value:
            _validate_json_numbers(child)


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
    from .plugins import bootstrap_plugins

    bootstrap_plugins()
    data = _read(path)
    version = data.get("version")
    if type(version) is int and version == 1:
        return Project.migrate_v1(data)
    if type(version) is int and version in (2, 3):
        return Project.from_dict(data)
    raise ValueError(f"unsupported project version: {version}")


def save_graph(graph: Graph, path: str | Path) -> None:
    """Backward-compatible graph API; new files are v3 single-VI projects."""
    project = Project(graph.name)
    project.main.name = graph.name
    project.main.graph = graph
    project._bind_graphs()
    save_project(project, path)


def load_graph(path: str | Path) -> Graph:
    """Backward-compatible loader returning the main VI graph."""
    return load_project(path).main.graph
