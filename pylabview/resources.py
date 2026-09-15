from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from threading import Condition, Lock
from typing import Any
import itertools
import time
import uuid

from .execution import CancellationToken
from .typesystem import DATA_TYPES, VARIANT, coerce


class ResourceError(RuntimeError):
    pass


@dataclass(frozen=True)
class ResourceRef:
    id: str
    kind: str
    owner: str


class _Closable:
    def close(self) -> None:
        raise NotImplementedError


class BoundedQueue(_Closable):
    def __init__(self, capacity: int, type_name: str = "variant") -> None:
        if capacity < 1:
            raise ValueError("queue capacity must be positive")
        if type_name not in DATA_TYPES:
            raise ValueError(f"unknown queue/channel type: {type_name}")
        self.capacity, self.type_name = capacity, type_name
        self._items: deque[Any] = deque()
        self._closed = False
        self._condition = Condition()

    def put(self, value: Any, timeout: float, token: CancellationToken) -> None:
        if self.type_name != VARIANT:
            value = coerce(value, self.type_name)
        deadline = _deadline(timeout)
        with self._condition:
            while len(self._items) >= self.capacity and not self._closed:
                _wait(self._condition, deadline, token, "queue put timed out")
            token.check()
            if self._closed:
                raise ResourceError("queue is closed")
            self._items.append(value)
            self._condition.notify_all()

    def get(self, timeout: float, token: CancellationToken) -> Any:
        deadline = _deadline(timeout)
        with self._condition:
            while not self._items and not self._closed:
                _wait(self._condition, deadline, token, "queue get timed out")
            token.check()
            if not self._items:
                raise ResourceError("queue is closed")
            value = self._items.popleft()
            self._condition.notify_all()
            return value

    def close(self) -> None:
        with self._condition:
            self._closed = True
            self._condition.notify_all()


class Notifier(_Closable):
    def __init__(self) -> None:
        self.value: Any = None
        self.generation = 0
        self._closed = False
        self._condition = Condition()

    def set(self, value: Any) -> int:
        with self._condition:
            if self._closed:
                raise ResourceError("notifier is closed")
            self.value = value
            self.generation += 1
            self._condition.notify_all()
            return self.generation

    def wait(self, after_generation: int, timeout: float, token: CancellationToken) -> tuple[Any, int]:
        deadline = _deadline(timeout)
        with self._condition:
            while self.generation <= after_generation and not self._closed:
                _wait(self._condition, deadline, token, "notifier wait timed out")
            token.check()
            if self._closed:
                raise ResourceError("notifier is closed")
            return self.value, self.generation

    def close(self) -> None:
        with self._condition:
            self._closed = True
            self._condition.notify_all()


class RuntimeEvent(_Closable):
    def __init__(self, name: str) -> None:
        self.name, self.generation, self.payload = name, 0, None
        self._notifier = Notifier()

    def fire(self, payload: Any) -> int:
        self.generation = self._notifier.set(payload)
        self.payload = payload
        return self.generation

    def wait(self, after_generation: int, timeout: float, token: CancellationToken) -> tuple[Any, int]:
        return self._notifier.wait(after_generation, timeout, token)

    def close(self) -> None:
        self._notifier.close()


class MessageChannel(BoundedQueue):
    pass


class ResourceManager:
    def __init__(self) -> None:
        self._owner = uuid.uuid4().hex
        self._counter = itertools.count(1)
        self._resources: dict[str, Any] = {}
        self._lock = Lock()
        self._named_events: dict[str, ResourceRef] = {}

    def add(self, kind: str, resource: Any) -> ResourceRef:
        with self._lock:
            ref = ResourceRef(f"r{next(self._counter)}", kind, self._owner)
            self._resources[ref.id] = resource
            return ref

    def get(self, ref: ResourceRef, kind: str | None = None) -> Any:
        if not isinstance(ref, ResourceRef):
            raise ResourceError("invalid resource reference")
        if ref.owner != self._owner:
            raise ResourceError("resource belongs to another session")
        with self._lock:
            try:
                resource = self._resources[ref.id]
            except KeyError as exc:
                raise ResourceError("resource is closed or belongs to another session") from exc
        if kind and ref.kind != kind:
            raise ResourceError(f"expected {kind} resource, got {ref.kind}")
        return resource

    def create_queue(self, capacity: int, type_name: str = "variant") -> ResourceRef:
        return self.add("queue", BoundedQueue(capacity, type_name))

    def create_notifier(self) -> ResourceRef:
        return self.add("notifier", Notifier())

    def create_event(self, name: str) -> ResourceRef:
        if not name:
            raise ValueError("event name must be non-empty")
        with self._lock:
            existing = self._named_events.get(name)
            if existing:
                return existing
            ref = ResourceRef(f"r{next(self._counter)}", "event", self._owner)
            self._resources[ref.id] = RuntimeEvent(name)
            self._named_events[name] = ref
        return ref

    def create_channel(self, capacity: int, type_name: str = "variant") -> ResourceRef:
        return self.add("channel", MessageChannel(capacity, type_name))

    def close(self, ref: ResourceRef) -> None:
        if not isinstance(ref, ResourceRef) or ref.owner != self._owner:
            raise ResourceError("resource belongs to another session")
        with self._lock:
            resource = self._resources.pop(ref.id, None)
            for name, event_ref in list(self._named_events.items()):
                if event_ref == ref:
                    del self._named_events[name]
        if resource is None:
            raise ResourceError("resource is already closed")
        close = getattr(resource, "close", None)
        if close:
            close()

    def close_all(self) -> None:
        with self._lock:
            resources = list(self._resources.values())
            self._resources.clear()
            self._named_events.clear()
        for resource in resources:
            close = getattr(resource, "close", None)
            if close:
                try:
                    close()
                except Exception:
                    pass


def _deadline(timeout: float) -> float:
    if timeout < 0 or timeout > 3600:
        raise ValueError("timeout must be between 0 and 3600 seconds")
    return time.monotonic() + timeout


def _wait(condition: Condition, deadline: float, token: CancellationToken, timeout_message: str) -> None:
    token.check()
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError(timeout_message)
    condition.wait(min(remaining, 0.05))
