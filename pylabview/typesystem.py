"""Explicit data types used by wires, persistence, and the runtime."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any
import json
import math


NUMERIC = "numeric"
BOOLEAN = "boolean"
STRING = "string"
ARRAY = "array"
CLUSTER = "cluster"
WAVEFORM = "waveform"
VARIANT = "variant"
ERROR = "error"
IMAGE = "image"

DATA_TYPES = (NUMERIC, BOOLEAN, STRING, ARRAY, CLUSTER, WAVEFORM, VARIANT, ERROR, IMAGE)

WIRE_COLORS = {
    NUMERIC: "#ff9f1c",
    BOOLEAN: "#45d66b",
    STRING: "#f4d35e",
    ARRAY: "#8ecae6",
    CLUSTER: "#b388eb",
    WAVEFORM: "#00c2a8",
    VARIANT: "#b0bec5",
    ERROR: "#ef476f",
    IMAGE: "#557a95",
}


def editor_value_text(value: Any) -> str:
    if isinstance(value, (bool, list, dict)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


@dataclass(frozen=True)
class Waveform:
    t0: float
    dt: float
    y: list[float]

    def __post_init__(self) -> None:
        if not math.isfinite(self.t0) or not math.isfinite(self.dt) or self.dt <= 0:
            raise ValueError("waveform t0 must be finite and dt must be positive")
        if not all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in self.y):
            raise TypeError("waveform samples must be numeric")


@dataclass(frozen=True)
class ErrorCluster:
    status: bool = False
    code: int = 0
    source: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.status, bool) or not isinstance(self.code, int) or not isinstance(self.source, str):
            raise TypeError("invalid error cluster fields")


def infer_type(value: Any) -> str:
    if isinstance(value, ErrorCluster):
        return ERROR
    if isinstance(value, Waveform):
        return WAVEFORM
    if isinstance(value, bool):
        return BOOLEAN
    if isinstance(value, (int, float)):
        return NUMERIC
    if isinstance(value, str):
        return STRING
    if isinstance(value, (list, tuple)):
        return ARRAY
    if isinstance(value, dict):
        return CLUSTER
    try:
        from .integrations.vision_adapter import ImageFrame
        if isinstance(value, ImageFrame): return IMAGE
    except ImportError:
        pass
    return VARIANT


def compatible(source: str, target: str) -> bool:
    _check_type_name(source)
    _check_type_name(target)
    return source == target or VARIANT in (source, target)


def validate(value: Any, data_type: str) -> bool:
    try:
        coerce(value, data_type)
        return True
    except (TypeError, ValueError):
        return False


def coerce(value: Any, data_type: str) -> Any:
    _check_type_name(data_type)
    if data_type == VARIANT:
        return value
    if data_type == NUMERIC:
        if isinstance(value, bool):
            raise TypeError("boolean is not numeric")
        result = float(value)
        return int(result) if result.is_integer() and isinstance(value, int) else result
    if data_type == BOOLEAN:
        if isinstance(value, bool):
            return value
        if isinstance(value, str) and value.lower() in ("true", "false"):
            return value.lower() == "true"
        raise TypeError("value is not boolean")
    if data_type == STRING:
        if not isinstance(value, str):
            raise TypeError("value is not string")
        return value
    if data_type == ARRAY:
        if not isinstance(value, (list, tuple)):
            raise TypeError("value is not array")
        return list(value)
    if data_type == CLUSTER:
        if not isinstance(value, dict):
            raise TypeError("value is not cluster")
        return dict(value)
    if data_type == WAVEFORM:
        if isinstance(value, Waveform):
            return value
        if isinstance(value, dict):
            return Waveform(float(value["t0"]), float(value["dt"]), list(value["y"]))
        raise TypeError("value is not waveform")
    if data_type == ERROR:
        if isinstance(value, ErrorCluster):
            return value
        if isinstance(value, dict):
            return ErrorCluster(bool(value["status"]), int(value["code"]), str(value["source"]))
        raise TypeError("value is not error cluster")
    if data_type == IMAGE:
        from .integrations.vision_adapter import ImageFrame
        if not isinstance(value, ImageFrame): raise TypeError("value is not an image frame")
        return value
    raise AssertionError(data_type)


def serialize(value: Any) -> Any:
    if isinstance(value, Waveform):
        return {"__type__": WAVEFORM, **asdict(value)}
    if isinstance(value, ErrorCluster):
        return {"__type__": ERROR, **asdict(value)}
    if isinstance(value, list):
        return [serialize(item) for item in value]
    if isinstance(value, dict):
        return {str(key): serialize(item) for key, item in value.items()}
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    raise TypeError(f"cannot serialize {type(value).__name__}")


def deserialize(value: Any) -> Any:
    if isinstance(value, list):
        return [deserialize(item) for item in value]
    if isinstance(value, dict):
        marker = value.get("__type__")
        if marker == WAVEFORM:
            return coerce(value, WAVEFORM)
        if marker == ERROR:
            return coerce(value, ERROR)
        return {key: deserialize(item) for key, item in value.items()}
    return value


def _check_type_name(data_type: str) -> None:
    if data_type not in DATA_TYPES:
        raise ValueError(f"unknown data type: {data_type}")
