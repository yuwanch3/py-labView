from __future__ import annotations

from importlib import import_module
from threading import RLock
from typing import Any


def _timeout(value: float) -> float:
    value = float(value)
    if value <= 0 or value > 300: raise ValueError("serial timeout must be greater than 0 and at most 300 seconds")
    return value


class SerialConnection:
    def __init__(self, stream: Any, close_command: bytes | None = None) -> None:
        if close_command is not None and (not isinstance(close_command, bytes) or not close_command):
            raise ValueError("serial close command must be non-empty bytes")
        self.stream, self.close_command, self._closed, self._lock = stream, close_command, False, RLock()

    def read(self, size: int) -> Any:
        with self._lock:
            if self._closed: raise RuntimeError("serial connection is closed")
            return self.stream.read(size)

    def write(self, data: bytes) -> Any:
        with self._lock:
            if self._closed: raise RuntimeError("serial connection is closed")
            return self.stream.write(data)

    def query_lines(self, command: bytes, line_count: int, max_bytes: int) -> tuple[bytes, ...]:
        if not isinstance(command, bytes) or not command:
            raise ValueError("serial command must be non-empty bytes")
        line_count, max_bytes = int(line_count), int(max_bytes)
        if line_count < 1 or line_count > 16 or max_bytes < line_count or max_bytes > 65536:
            raise ValueError("serial response bounds are invalid")
        with self._lock:
            if self._closed:
                raise RuntimeError("serial connection is closed")
            if int(self.stream.write(command)) != len(command):
                raise OSError("incomplete serial command write")
            lines: list[bytes] = []
            remaining = max_bytes
            for _ in range(line_count):
                reader = getattr(self.stream, "readline", None)
                if not callable(reader):
                    raise TypeError("serial line protocol requires a readline-capable backend")
                raw = reader(remaining + 1)
                if not isinstance(raw, (bytes, bytearray)):
                    raise TypeError("serial response must be bytes")
                line = bytes(raw)
                if not line.endswith(b"\n"):
                    raise OSError("incomplete serial response line")
                if len(line) > remaining:
                    raise ValueError("serial response exceeds configured bound")
                lines.append(line)
                remaining -= len(line)
            return tuple(lines)

    def close(self) -> None:
        with self._lock:
            if self._closed: return
            self._closed = True
            try:
                self.safe_stop()
            finally:
                self.stream.close()

    def safe_stop(self) -> None:
        with self._lock:
            if self.close_command is None:
                return
            written = int(self.stream.write(self.close_command))
            if written != len(self.close_command):
                raise OSError("incomplete serial safe-stop write")


class SerialAdapter:
    def __init__(self, backend: Any = None) -> None:
        self.backend = backend

    @property
    def available(self) -> bool:
        if self.backend is not None: return True
        try: import_module("serial"); return True
        except Exception: return False

    def open(self, port: str, baudrate: int = 9600, timeout: float = 1,
             close_command: bytes | None = None) -> Any:
        if not isinstance(port, str) or not port.strip(): raise ValueError("serial port must be non-empty")
        baudrate = int(baudrate)
        if baudrate < 1 or baudrate > 20_000_000: raise ValueError("serial baudrate is outside bounds")
        timeout = _timeout(timeout)
        try: backend = self.backend or import_module("serial")
        except Exception as exc: raise RuntimeError(f"pyserial unavailable: {exc}") from exc
        stream = backend.serial_for_url(port, baudrate=baudrate, timeout=timeout, write_timeout=timeout)
        return SerialConnection(stream, close_command)
