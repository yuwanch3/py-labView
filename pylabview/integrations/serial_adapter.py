from __future__ import annotations

from importlib import import_module
from threading import RLock
from typing import Any


def _timeout(value: float) -> float:
    value = float(value)
    if value <= 0 or value > 300: raise ValueError("serial timeout must be greater than 0 and at most 300 seconds")
    return value


class SerialConnection:
    def __init__(self, stream: Any) -> None:
        self.stream, self._closed, self._lock = stream, False, RLock()

    def read(self, size: int) -> Any:
        with self._lock:
            if self._closed: raise RuntimeError("serial connection is closed")
            return self.stream.read(size)

    def write(self, data: bytes) -> Any:
        with self._lock:
            if self._closed: raise RuntimeError("serial connection is closed")
            return self.stream.write(data)

    def close(self) -> None:
        with self._lock:
            if self._closed: return
            self._closed = True
            self.stream.close()


class SerialAdapter:
    def __init__(self, backend: Any = None) -> None:
        self.backend = backend

    @property
    def available(self) -> bool:
        if self.backend is not None: return True
        try: import_module("serial"); return True
        except Exception: return False

    def open(self, port: str, baudrate: int = 9600, timeout: float = 1) -> Any:
        if not isinstance(port, str) or not port.strip(): raise ValueError("serial port must be non-empty")
        baudrate = int(baudrate)
        if baudrate < 1 or baudrate > 20_000_000: raise ValueError("serial baudrate is outside bounds")
        timeout = _timeout(timeout)
        try: backend = self.backend or import_module("serial")
        except Exception as exc: raise RuntimeError(f"pyserial unavailable: {exc}") from exc
        stream = backend.serial_for_url(port, baudrate=baudrate, timeout=timeout, write_timeout=timeout)
        return SerialConnection(stream)
