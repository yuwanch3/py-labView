from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from queue import Empty, Queue
from threading import Condition, Event, Lock, Thread
from typing import Any, Callable
import itertools
import time


class CancelledError(RuntimeError):
    pass


class CancellationToken:
    def __init__(self) -> None:
        self._event = Event()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def cancel(self) -> None:
        self._event.set()

    def check(self) -> None:
        if self.cancelled:
            raise CancelledError("execution cancelled")

    def wait(self, timeout: float) -> bool:
        if timeout < 0:
            raise ValueError("timeout must be non-negative")
        return self._event.wait(timeout)


@dataclass(frozen=True)
class ExecutionEvent:
    sequence: int
    timestamp: float
    kind: str
    node_id: str | None = None
    wire_id: str | None = None
    value_preview: str | None = None
    message: str = ""
    payload: Any = None


def value_preview(value: Any, limit: int = 160) -> str:
    text = repr(value)
    return text if len(text) <= limit else text[: limit - 3] + "..."


class Debugger:
    def __init__(self, trace_limit: int = 10000, event_sink: Callable[[ExecutionEvent], None] | None = None) -> None:
        if trace_limit < 1:
            raise ValueError("trace_limit must be positive")
        self.breakpoints: set[str] = set()
        self.probes: set[str] = set()
        self.trace: deque[ExecutionEvent] = deque(maxlen=trace_limit)
        self._sequence = itertools.count(1)
        self._condition = Condition()
        self._paused = False
        self._step_budget: int | None = None
        self._sink = event_sink

    @property
    def paused(self) -> bool:
        with self._condition:
            return self._paused

    def emit(self, kind: str, node_id: str | None = None, wire_id: str | None = None,
             value: Any = None, message: str = "") -> ExecutionEvent:
        event = ExecutionEvent(next(self._sequence), time.monotonic(), kind, node_id, wire_id,
                               value_preview(value) if value is not None else None, message)
        self.trace.append(event)
        if self._sink:
            self._sink(event)
        return event

    def before_node(self, node_id: str, token: CancellationToken) -> None:
        with self._condition:
            should_pause = node_id in self.breakpoints or self._step_budget == 0
            if should_pause:
                self._paused = True
                self.emit("breakpoint", node_id)
            while self._paused and not token.cancelled:
                self._condition.wait(0.05)
            token.check()
            if self._step_budget is not None:
                self._step_budget -= 1

    def pause(self) -> None:
        with self._condition:
            self._paused = True
            self.emit("paused")

    def resume(self) -> None:
        with self._condition:
            self._paused = False
            self._step_budget = None
            self._condition.notify_all()
            self.emit("resumed")

    def step(self) -> None:
        with self._condition:
            self._paused = False
            self._step_budget = 1
            self._condition.notify_all()
            self.emit("step")

    def cancel_wait(self) -> None:
        with self._condition:
            self._paused = False
            self._condition.notify_all()

    def probe(self, wire_id: str, node_id: str, value: Any) -> None:
        if wire_id in self.probes:
            self.emit("probe", node_id=node_id, wire_id=wire_id, value=value)


@dataclass
class RunSession:
    token: CancellationToken = field(default_factory=CancellationToken)
    debugger: Debugger = field(default_factory=Debugger)
    resources: Any = None
    state: dict[str, Any] = field(default_factory=dict)
    debug: bool = False

    def close(self) -> None:
        if self.resources is not None:
            self.resources.close_all()


class RunController:
    """Runs a synchronous runtime outside Tk and exposes events through a queue."""

    def __init__(self, runtime: Any) -> None:
        self.runtime = runtime
        self.events: Queue[ExecutionEvent] = Queue()
        self.session: RunSession | None = None
        self._thread: Thread | None = None
        self._lock = Lock()
        self._controls: dict[str, Any] = {}
        self.last_result: Any = None

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def start(self, graph: Any, controls: dict[str, Any] | None = None, project: Any = None,
              vi_id: str | None = None, continuous: bool = False, debug: bool = False,
              interval: float = 0.15, breakpoints: set[str] | None = None,
              probes: set[str] | None = None) -> None:
        with self._lock:
            if self.running:
                raise RuntimeError("execution is already running")
            project = project or getattr(graph, "project", None)
            debugger = Debugger(event_sink=self.events.put)
            debugger.breakpoints = set(breakpoints or ())
            debugger.probes = set(probes or ())
            self.session = RunSession(debugger=debugger, debug=debug)
            self._controls = dict(controls or {})
            self.last_result = None
            while True:
                try:
                    self.events.get_nowait()
                except Empty:
                    break
            graph_scope = "standalone"
            if project is not None:
                from .model import Project
                target_vi_id = vi_id or project.main_vi
                original_vi = project.vis.get(target_vi_id)
                diagram_id = None
                if original_vi and graph is not original_vi.graph:
                    diagram_id = next((key for key, candidate in original_vi.subdiagrams.items() if candidate is graph), None)
                project = Project.from_dict(project.to_dict())
                if target_vi_id in project.vis:
                    graph = project.vis[target_vi_id].subdiagrams[diagram_id] if diagram_id else project.vis[target_vi_id].graph
                    vi_id = target_vi_id
                    graph_scope = diagram_id or "root"
            else:
                from .model import Graph
                graph = Graph.from_dict(graph.graph_dict())
            self._thread = Thread(
                target=self._worker,
                args=(graph, project, vi_id, graph_scope, continuous, debug, interval),
                name="pylabview-run-controller",
                daemon=True,
            )
            self._thread.start()

    def _worker(self, graph: Any, project: Any, vi_id: str | None, graph_scope: str,
                continuous: bool, debug: bool, interval: float) -> None:
        assert self.session is not None
        self.session.debugger.emit("run_started")
        try:
            while True:
                with self._lock:
                    controls = dict(self._controls)
                result = self.runtime.run(graph, controls, project, vi_id, session=self.session,
                                          debug=debug, graph_scope=graph_scope)
                self.last_result = result
                self.events.put(ExecutionEvent(0, time.monotonic(), "result", message="result available",
                                               payload=result))
                if not continuous or self.session.token.cancelled:
                    break
                if self.session.token.wait(interval):
                    break
        except CancelledError:
            self.session.debugger.emit("run_cancelled")
        except Exception as exc:
            self.session.debugger.emit("run_failed", message=str(exc))
        finally:
            self.session.close()
            self.session.debugger.emit("run_completed")

    def stop(self) -> None:
        if self.session:
            self.session.token.cancel()
            self.session.debugger.cancel_wait()
            if self.session.resources is not None:
                self.session.resources.close_all()

    def update_controls(self, controls: dict[str, Any]) -> None:
        with self._lock:
            self._controls = dict(controls)

    def pause(self) -> None:
        if self.session:
            self.session.debugger.pause()

    def resume(self) -> None:
        if self.session:
            self.session.debugger.resume()

    def step(self) -> None:
        if self.session:
            self.session.debugger.step()

    def drain_events(self) -> list[ExecutionEvent]:
        events: list[ExecutionEvent] = []
        while True:
            try:
                events.append(self.events.get_nowait())
            except Empty:
                return events
