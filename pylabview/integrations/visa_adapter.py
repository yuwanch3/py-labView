from __future__ import annotations

from importlib import import_module
from threading import RLock
from typing import Any, Callable


MAX_VISA_BYTES = 16 * 1024 * 1024


def _timeout_ms(seconds: float) -> int:
    value = float(seconds)
    if value <= 0 or value > 300:
        raise ValueError("VISA timeout must be greater than 0 and at most 300 seconds")
    return max(1, int(value * 1000))


class VisaInstrument:
    def __init__(self, instrument: Any, manager: Any, timeout: float, max_bytes: int) -> None:
        if not 1 <= int(max_bytes) <= MAX_VISA_BYTES:
            raise ValueError(f"VISA max_bytes must be between 1 and {MAX_VISA_BYTES}")
        self.instrument, self.manager, self.max_bytes = instrument, manager, int(max_bytes)
        self.instrument.timeout = _timeout_ms(timeout)
        self._closed = False
        self._lock = RLock()

    def _check_open(self) -> None:
        if self._closed: raise RuntimeError("VISA instrument is closed")

    def write(self, text: str) -> int:
        with self._lock:
            self._check_open()
            if not isinstance(text, str): raise TypeError("VISA write requires text")
            if len(text.encode("utf-8")) > self.max_bytes: raise ValueError("VISA write exceeds max_bytes")
            return int(self.instrument.write(text))

    def query(self, text: str) -> str:
        with self._lock:
            self._check_open()
            if not isinstance(text, str): raise TypeError("VISA query requires text")
            if len(text.encode("utf-8")) > self.max_bytes: raise ValueError("VISA query exceeds max_bytes")
            value = self.instrument.query(text)
            if not isinstance(value, str): raise TypeError("VISA query did not return text")
            if len(value.encode("utf-8")) > self.max_bytes: raise ValueError("VISA response exceeds max_bytes")
            return value

    def read_raw(self) -> bytes:
        with self._lock:
            self._check_open()
            value = self.instrument.read_raw()
            if not isinstance(value, bytes): value = bytes(value)
            if len(value) > self.max_bytes: raise ValueError("VISA raw response exceeds max_bytes")
            return value

    def write_raw(self, data: bytes) -> int:
        with self._lock:
            self._check_open()
            if not isinstance(data, bytes): raise TypeError("VISA raw write requires bytes")
            if len(data) > self.max_bytes: raise ValueError("VISA raw write exceeds max_bytes")
            return int(self.instrument.write_raw(data))

    def close(self) -> None:
        with self._lock:
            if self._closed: return
            self._closed = True
            try: self.instrument.close()
            finally: self.manager.close()


class VisaAdapter:
    def __init__(self, resource_manager: Callable[..., Any] | None = None) -> None:
        self._factory = resource_manager

    @property
    def available(self) -> bool:
        if self._factory is not None: return True
        try: import_module("pyvisa"); return True
        except Exception: return False

    def _manager(self) -> Any:
        if self._factory is not None: return self._factory()
        try: return import_module("pyvisa").ResourceManager()
        except Exception as exc: raise RuntimeError(f"PyVISA unavailable: {exc}") from exc

    def open(self, resource: str, timeout: float = 2, max_bytes: int = 1024 * 1024) -> VisaInstrument:
        if not isinstance(resource, str) or not resource.strip(): raise ValueError("VISA resource must be non-empty")
        manager = self._manager()
        try: instrument = manager.open_resource(resource)
        except BaseException:
            manager.close(); raise
        try: return VisaInstrument(instrument, manager, timeout, max_bytes)
        except BaseException:
            try: instrument.close()
            finally: manager.close()
            raise

    def list_resources(self) -> list[str]:
        manager = self._manager()
        try: return [str(value) for value in manager.list_resources()]
        finally: manager.close()
