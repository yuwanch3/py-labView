from __future__ import annotations

from importlib import import_module
from threading import RLock
from typing import Any, Callable


def _timeout(value: float) -> float:
    value = float(value)
    if value <= 0 or value > 300: raise ValueError("OPC UA timeout must be greater than 0 and at most 300 seconds")
    return value


class OpcUaConnection:
    def __init__(self, client: Any) -> None:
        self.client, self._closed = client, False
        self._lock = RLock()

    def read(self, node_id: str) -> Any:
        with self._lock:
            if self._closed: raise RuntimeError("OPC UA connection is closed")
            if not isinstance(node_id, str) or not node_id: raise ValueError("OPC UA node id must be non-empty")
            return self.client.get_node(node_id).read_value()

    def write(self, node_id: str, value: Any) -> None:
        with self._lock:
            if self._closed: raise RuntimeError("OPC UA connection is closed")
            if not isinstance(node_id, str) or not node_id: raise ValueError("OPC UA node id must be non-empty")
            self.client.get_node(node_id).write_value(value)

    def close(self) -> None:
        with self._lock:
            if not self._closed:
                self._closed = True
                self.client.disconnect()


class OpcUaAdapter:
    """Synchronous asyncua adapter. Subscriptions are intentionally not claimed."""

    def __init__(self, client_factory: Callable[..., Any] | None = None) -> None:
        self._factory = client_factory

    @property
    def available(self) -> bool:
        if self._factory: return True
        try: import_module("asyncua.sync"); return True
        except Exception: return False

    def connect(self, endpoint: str, timeout: float = 2) -> OpcUaConnection:
        if not isinstance(endpoint, str) or not endpoint.startswith(("opc.tcp://", "https://")):
            raise ValueError("OPC UA endpoint must use opc.tcp:// or https://")
        timeout = _timeout(timeout)
        if self._factory is None:
            try: factory = import_module("asyncua.sync").Client
            except Exception as exc: raise RuntimeError(f"asyncua unavailable: {exc}") from exc
        else: factory = self._factory
        client = factory(endpoint, timeout=timeout)
        try: client.connect()
        except BaseException:
            try: client.disconnect()
            except Exception: pass
            raise
        return OpcUaConnection(client)
