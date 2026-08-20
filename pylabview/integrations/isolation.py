"""Crash isolation for explicitly registered, JSON-only plugin evaluators.

This is not a security sandbox. Child code has the user's OS permissions.
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from multiprocessing import get_context
from multiprocessing.connection import Connection
from typing import Any, Callable
import json
import uuid


MAX_ISOLATION_PAYLOAD = 1024 * 1024


class IsolatedEvaluatorError(RuntimeError):
    pass


def _json(value: Any) -> bytes:
    try: payload = json.dumps(value, allow_nan=False, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError) as exc: raise ValueError(f"plugin payload must be JSON-serializable: {exc}") from exc
    if len(payload) > MAX_ISOLATION_PAYLOAD: raise ValueError("plugin payload exceeds isolation limit")
    return payload


def importable_callable_path(evaluator: Callable[[Any], Any] | str) -> str:
    if isinstance(evaluator, str):
        if ":" not in evaluator: raise ValueError("isolated evaluator path must use module:qualname")
        module_name, qualname = evaluator.split(":", 1)
    else:
        module_name = getattr(evaluator, "__module__", "")
        qualname = getattr(evaluator, "__qualname__", "")
    if not module_name or not qualname or "<locals>" in qualname or "<lambda>" in qualname:
        raise ValueError("isolated evaluator must be an importable module-level callable")
    try:
        value: Any = import_module(module_name)
        for part in qualname.split("."): value = getattr(value, part)
    except (ImportError, AttributeError) as exc:
        raise ValueError("isolated evaluator path cannot be imported") from exc
    if not callable(value): raise ValueError("isolated evaluator path is not callable")
    if not isinstance(evaluator, str) and value is not evaluator:
        raise ValueError("isolated evaluator must resolve to the registered callable")
    return f"{module_name}:{qualname}"


def _worker(connection: Connection, evaluator_path: str) -> None:
    try:
        module_name, qualname = evaluator_path.split(":", 1)
        evaluator: Any = import_module(module_name)
        for part in qualname.split("."): evaluator = getattr(evaluator, part)
        while True:
            raw = connection.recv_bytes(MAX_ISOLATION_PAYLOAD + 1)
            request = json.loads(raw)
            if request.get("method") == "close": return
            try: response = {"id": request["id"], "ok": True, "result": evaluator(request["payload"])}
            except BaseException as exc: response = {"id": request.get("id"), "ok": False, "error": f"{type(exc).__name__}: {exc}"}
            connection.send_bytes(_json(response))
    except (EOFError, OSError, ValueError):
        return
    finally: connection.close()


@dataclass
class IsolatedEvaluatorHost:
    evaluator: Callable[[Any], Any] | str

    def __post_init__(self) -> None:
        evaluator_path = importable_callable_path(self.evaluator)
        context = get_context("spawn")
        self._parent, child = context.Pipe()
        self._process = context.Process(target=_worker, args=(child, evaluator_path), daemon=True)
        try:
            self._process.start()
        except BaseException:
            self._parent.close(); child.close()
            raise
        child.close()

    def call(self, payload: Any, timeout: float = 2) -> Any:
        timeout = float(timeout)
        if timeout <= 0 or timeout > 300: raise ValueError("isolation timeout must be greater than 0 and at most 300 seconds")
        request_id = uuid.uuid4().hex
        try: self._parent.send_bytes(_json({"id": request_id, "method": "evaluate", "payload": payload}))
        except (BrokenPipeError, EOFError, OSError) as exc: raise IsolatedEvaluatorError("plugin process crashed") from exc
        if not self._parent.poll(timeout):
            self.terminate(); raise TimeoutError("isolated plugin evaluator timed out")
        try: response = json.loads(self._parent.recv_bytes(MAX_ISOLATION_PAYLOAD + 1))
        except (EOFError, OSError, ValueError) as exc: raise IsolatedEvaluatorError("plugin process crashed or returned invalid JSON") from exc
        if response.get("id") != request_id: raise IsolatedEvaluatorError("plugin response id mismatch")
        if not response.get("ok"): raise IsolatedEvaluatorError(str(response.get("error", "plugin evaluator failed")))
        return response.get("result")

    def close(self) -> None:
        if not self._process.is_alive():
            self._parent.close(); return
        try: self._parent.send_bytes(_json({"id": uuid.uuid4().hex, "method": "close"}))
        except (BrokenPipeError, OSError): pass
        self._process.join(0.5)
        if self._process.is_alive(): self.terminate()
        self._parent.close()

    def terminate(self) -> None:
        if self._process.is_alive(): self._process.terminate(); self._process.join(1)

    def __enter__(self) -> "IsolatedEvaluatorHost": return self
    def __exit__(self, *_args: Any) -> None: self.close()
