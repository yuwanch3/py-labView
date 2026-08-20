from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock
from typing import Any, Callable
import csv
import math
import random
import time

from .drivers import ChannelConfig, DriverRegistry
from .model import Graph, NODE_DEFINITIONS, Node, Project
from .typesystem import ErrorCluster, Waveform, coerce, compatible


class DataflowError(Exception):
    """A graph validation or execution error."""


@dataclass
class RunResult:
    values: dict[str, Any] = field(default_factory=dict)
    statuses: dict[str, str] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    logs: list[str] = field(default_factory=list)
    durations: dict[str, float] = field(default_factory=dict)
    port_values: dict[tuple[str, str], Any] = field(default_factory=dict)


class DataflowRuntime:
    def __init__(self, clock: Callable[[], float] = time.monotonic, rng: random.Random | None = None,
                 max_workers: int = 4, data_root: str | Path | None = None,
                 drivers: DriverRegistry | None = None) -> None:
        self.clock = clock
        self.rng = rng or random.Random()
        self.started_at = self.clock()
        self.max_workers = max(1, max_workers)
        self.data_root = Path(data_root or Path.cwd()).resolve()
        self.drivers = drivers or DriverRegistry.with_simulation(self.rng)
        self._daq_configured: dict[tuple[str, str], ChannelConfig] = {}
        self._daq_lock = Lock()

    def reset(self) -> None:
        self.started_at = self.clock()

    def topological_order(self, graph: Graph) -> list[str]:
        levels = self._levels(graph)
        return [node_id for level in levels for node_id in level]

    def _levels(self, graph: Graph) -> list[list[str]]:
        indegree = {node_id: 0 for node_id in graph.nodes}
        following: dict[str, list[str]] = {node_id: [] for node_id in graph.nodes}
        for wire in graph.wires:
            indegree[wire.target_node] += 1
            following[wire.source_node].append(wire.target_node)
        ready = [node_id for node_id in graph.nodes if indegree[node_id] == 0]
        levels: list[list[str]] = []
        visited = 0
        while ready:
            level = ready
            levels.append(level)
            ready = []
            for node_id in level:
                visited += 1
                for target in following[node_id]:
                    indegree[target] -= 1
                    if indegree[target] == 0:
                        ready.append(target)
        if visited != len(graph.nodes):
            cyclic = [graph.nodes[node_id].label for node_id, degree in indegree.items() if degree]
            raise DataflowError("Cycle detected: " + ", ".join(cyclic))
        return levels

    def validate(self, graph: Graph, project: Project | None = None, vi_id: str | None = None) -> list[str]:
        errors: list[str] = []
        try:
            self.topological_order(graph)
        except DataflowError as exc:
            errors.append(str(exc))
        for node in graph.nodes.values():
            connected = graph.incoming(node.id)
            try:
                ports = graph.ports(node, "in")
            except (KeyError, StopIteration, ValueError):
                ports = ()
                errors.append(f"{node.label}: invalid port configuration")
            if node.type == "subvi" and (not project or node.properties.get("vi_id") not in project.vis):
                errors.append(f"{node.label}: referenced VI does not exist")
            for port in ports:
                if port not in connected:
                    errors.append(f"{node.label}: missing input '{port}'")
        for wire in graph.wires:
            try:
                source, target = graph.nodes[wire.source_node], graph.nodes[wire.target_node]
                if wire.source_port not in graph.ports(source, "out") or wire.target_port not in graph.ports(target, "in"):
                    raise ValueError("port no longer exists")
                source_type = graph.port_type(source, "out", wire.source_port)
                target_type = graph.port_type(target, "in", wire.target_port)
                if not compatible(source_type, target_type):
                    raise ValueError(f"incompatible types {source_type} -> {target_type}")
            except (KeyError, StopIteration, ValueError) as exc:
                errors.append(f"Invalid wire {wire.source_node}:{wire.source_port} -> {wire.target_node}:{wire.target_port}: {exc}")
        if project:
            errors.extend(self._validate_call_graph(project, vi_id))
        return list(dict.fromkeys(errors))

    def _validate_call_graph(self, project: Project, start: str | None = None) -> list[str]:
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(vi_id: str, trail: list[str]) -> str | None:
            if vi_id in visiting:
                names = [project.vis[item].name for item in trail + [vi_id]]
                return "SubVI recursion detected: " + " -> ".join(names)
            if vi_id in visited:
                return None
            visiting.add(vi_id)
            for node in project.vis[vi_id].graph.nodes.values():
                target = node.properties.get("vi_id") if node.type == "subvi" else None
                if target in project.vis:
                    error = visit(str(target), trail + [vi_id])
                    if error:
                        return error
            visiting.remove(vi_id)
            visited.add(vi_id)
            return None

        roots = [start] if start else list(project.vis)
        for root in roots:
            if root in project.vis:
                error = visit(root, [])
                if error:
                    return [error]
        return []

    def run(self, graph: Graph, control_values: dict[str, Any] | None = None,
            project: Project | None = None, vi_id: str | None = None) -> RunResult:
        project = project or graph.project
        result = RunResult(statuses={node_id: "idle" for node_id in graph.nodes})
        validation = self.validate(graph, project, vi_id)
        if validation:
            result.errors.extend(validation)
            result.statuses = {node_id: "error" for node_id in graph.nodes}
            return result
        controls = control_values or {}
        try:
            levels = self._levels(graph)
            with ThreadPoolExecutor(max_workers=self.max_workers, thread_name_prefix="pylabview") as executor:
                for level in levels:
                    jobs = {}
                    for node_id in level:
                        node = graph.nodes[node_id]
                        incoming = graph.incoming(node_id)
                        inputs = {}
                        for port, wire in incoming.items():
                            value = result.port_values[(wire.source_node, wire.source_port)]
                            expected = graph.port_type(node, "in", port)
                            inputs[port] = value if expected == "variant" else coerce(value, expected)
                        result.statuses[node_id] = "running"
                        jobs[node_id] = executor.submit(self._timed_evaluate, node, inputs, controls, project, vi_id)
                    for node_id in level:  # merge in graph order, independent of completion order
                        node = graph.nodes[node_id]
                        try:
                            outputs, raw_value, logs, duration = jobs[node_id].result()
                            output_ports = graph.ports(node, "out")
                            normalized_outputs: dict[str, Any] = {}
                            for port in output_ports:
                                if port not in outputs:
                                    raise DataflowError(f"node did not produce output '{port}'")
                                value = outputs[port]
                                expected = graph.port_type(node, "out", port)
                                if expected != "variant":
                                    value = coerce(value, expected)
                                normalized_outputs[port] = value
                                result.port_values[(node_id, port)] = value
                            result.values[node_id] = (normalized_outputs[output_ports[0]] if len(output_ports) == 1 else
                                                      normalized_outputs) if output_ports else raw_value
                            result.logs.extend(logs)
                            result.durations[node_id] = duration
                            result.statuses[node_id] = "success"
                        except Exception as exc:
                            result.statuses[node_id] = "error"
                            result.errors.append(f"{node.label}: {exc}")
                    if result.errors:
                        following: dict[str, list[str]] = {node_id: [] for node_id in graph.nodes}
                        for wire in graph.wires:
                            following[wire.source_node].append(wire.target_node)
                        pending = [node_id for node_id, status in result.statuses.items() if status == "error"]
                        blocked: set[str] = set()
                        while pending:
                            for target in following[pending.pop()]:
                                if target not in blocked:
                                    blocked.add(target)
                                    pending.append(target)
                        for blocked_id in blocked:
                            if result.statuses[blocked_id] == "idle":
                                result.statuses[blocked_id] = "blocked"
                        break
        except Exception as exc:
            result.errors.append(str(exc))
        return result

    def run_project(self, project: Project, vi_id: str | None = None,
                    inputs: dict[str, Any] | None = None) -> RunResult:
        target_id = vi_id or project.main_vi
        if target_id not in project.vis:
            return RunResult(errors=["unknown VI"])
        vi = project.vis[target_id]
        controls: dict[str, Any] = {}
        provided = inputs or {}
        for terminal in vi.connector_inputs:
            if terminal.name not in provided:
                return RunResult(errors=[f"{vi.name}: missing connector input '{terminal.name}'"])
            controls[terminal.node_id] = coerce(provided[terminal.name], terminal.data_type)
        return self.run(vi.graph, controls, project, target_id)

    def _timed_evaluate(self, node: Node, inputs: dict[str, Any], controls: dict[str, Any],
                        project: Project | None, caller_vi: str | None) -> tuple[dict[str, Any], Any, list[str], float]:
        started = self.clock()
        logs: list[str] = []
        value = self._evaluate(node, inputs, controls, logs, project, caller_vi)
        outputs = value if isinstance(value, dict) and node.type in ("cluster_unbundle", "waveform_stats", "file_read", "error_handler", "subvi") else {"out": value}
        definition_outputs = NODE_DEFINITIONS[node.type].outputs
        if node.type not in ("subvi",) and len(definition_outputs) == 1 and definition_outputs[0] != "out":
            outputs = {definition_outputs[0]: value}
        return outputs, value, logs, self.clock() - started

    def _evaluate(self, node: Node, inputs: dict[str, Any], controls: dict[str, Any], logs: list[str],
                  project: Project | None = None, caller_vi: str | None = None) -> Any:
        kind = node.type
        if kind in ("numeric_constant", "string_constant", "boolean_constant", "array_constant"):
            return controls.get(node.id, node.properties.get("value"))
        if kind in ("add", "subtract", "multiply", "divide", "numeric_min", "numeric_max"):
            a, b = inputs["a"], inputs["b"]
            if kind == "divide" and b == 0:
                raise DataflowError("division by zero")
            return {"add": a + b, "subtract": a - b, "multiply": a * b,
                    "divide": a / b if b else 0, "numeric_min": min(a, b), "numeric_max": max(a, b)}[kind]
        if kind == "absolute": return abs(inputs["x"])
        if kind == "sine": return math.sin(float(inputs["x"]))
        if kind == "compare":
            operators = {">": lambda a, b: a > b, "<": lambda a, b: a < b, "==": lambda a, b: a == b,
                         ">=": lambda a, b: a >= b, "<=": lambda a, b: a <= b, "!=": lambda a, b: a != b}
            operator = node.properties.get("operator", ">")
            if operator not in operators: raise DataflowError(f"unsupported comparison: {operator}")
            return operators[operator](inputs["a"], inputs["b"])
        if kind in ("select", "case"): return inputs["true"] if inputs.get("condition", inputs.get("selector")) else inputs["false"]
        if kind == "sequence": return inputs["second"]
        if kind == "boolean_and": return inputs["a"] and inputs["b"]
        if kind == "boolean_or": return inputs["a"] or inputs["b"]
        if kind == "boolean_not": return not inputs["value"]
        if kind == "string_concat": return inputs["a"] + inputs["b"]
        if kind == "string_format":
            try: return str(node.properties.get("template", "{}")).format(inputs["value"])
            except (IndexError, KeyError, ValueError) as exc: raise DataflowError(f"invalid format template: {exc}") from exc
        if kind == "array_build":
            return (list(inputs["a"]) if isinstance(inputs["a"], list) else [inputs["a"]]) + (list(inputs["b"]) if isinstance(inputs["b"], list) else [inputs["b"]])
        if kind == "array_index":
            index = int(inputs["index"])
            if index != inputs["index"]: raise DataflowError("array index must be an integer")
            try: return inputs["array"][index]
            except IndexError as exc: raise DataflowError("array index out of range") from exc
        if kind == "array_size": return len(inputs["array"])
        if kind == "cluster_bundle": return {str(node.properties.get("name_a", "a")): inputs["a"], str(node.properties.get("name_b", "b")): inputs["b"]}
        if kind == "cluster_unbundle":
            names = (str(node.properties.get("name_a", "a")), str(node.properties.get("name_b", "b")))
            try: return {"a": inputs["cluster"][names[0]], "b": inputs["cluster"][names[1]]}
            except KeyError as exc: raise DataflowError(f"cluster field missing: {exc.args[0]}") from exc
        if kind == "waveform_create": return Waveform(float(inputs["t0"]), float(inputs["dt"]), list(inputs["y"]))
        if kind == "waveform_stats":
            values = inputs["waveform"].y
            if not values: raise DataflowError("waveform has no samples")
            return {"min": min(values), "max": max(values), "mean": sum(values) / len(values)}
        if kind == "for_loop":
            values = inputs["array"]
            maximum = self._bounded_int(node, "max_iterations", 1000)
            if len(values) > maximum: raise DataflowError("for-loop iteration bound exceeded")
            operation, scale = node.properties.get("operation", "identity"), float(node.properties.get("scale", 1))
            if operation not in ("identity", "abs", "scale"): raise DataflowError("unsupported for-loop operation")
            return [item if operation == "identity" else abs(item) if operation == "abs" else item * scale for item in values]
        if kind == "while_loop":
            value, count = float(inputs["initial"]), 0
            maximum = self._bounded_int(node, "max_iterations", 100)
            limit, step, condition = float(node.properties.get("limit", 10)), float(node.properties.get("step", 1)), node.properties.get("condition", "less_than")
            predicates = {"less_than": lambda x: x < limit, "greater_than": lambda x: x > limit}
            if condition not in predicates: raise DataflowError("unsupported while-loop condition")
            while predicates[condition](value) and count < maximum: value, count = value + step, count + 1
            if predicates[condition](value): raise DataflowError("while-loop iteration bound reached")
            return value
        if kind == "random": return self.rng.random()
        if kind == "timer": return self.clock() - self.started_at
        if kind == "delay":
            seconds, maximum = float(node.properties.get("seconds", 0)), float(node.properties.get("maximum_seconds", 5))
            if seconds < 0 or seconds > maximum: raise DataflowError("delay outside configured bound")
            time.sleep(seconds); return inputs["value"]
        if kind == "timed_loop":
            count = self._bounded_int(node, "iterations", 1)
            if count > self._bounded_int(node, "max_iterations", 1000): raise DataflowError("timed-loop iteration bound exceeded")
            interval = float(node.properties.get("interval", 0.01))
            if interval < 0 or interval > 5: raise DataflowError("timed-loop interval outside bound")
            ticks = []
            for _ in range(count): ticks.append(self.clock()); time.sleep(interval)
            return ticks
        if kind in ("analog_input", "digital_input", "analog_output", "digital_output"):
            return self._daq(node, inputs)
        if kind == "file_read":
            try: return {"text": self._safe_path(node).read_text(encoding="utf-8"), "error": ErrorCluster()}
            except (OSError, ValueError) as exc: return {"text": "", "error": ErrorCluster(True, 20, str(exc))}
        if kind == "file_write":
            try: self._safe_path(node).write_text(inputs["text"], encoding="utf-8"); return ErrorCluster()
            except (OSError, ValueError) as exc: return ErrorCluster(True, 21, str(exc))
        if kind == "csv_logger":
            try:
                path = self._safe_path(node)
                with path.open("a", newline="", encoding="utf-8") as stream: csv.writer(stream).writerow([inputs["value"]])
                return ErrorCluster()
            except (OSError, ValueError) as exc: return ErrorCluster(True, 22, str(exc))
        if kind == "error_constant": return ErrorCluster(bool(node.properties.get("status", False)), int(node.properties.get("code", 0)), str(node.properties.get("source", "")))
        if kind == "error_merge": return inputs["a"] if inputs["a"].status else inputs["b"]
        if kind == "error_handler":
            error = inputs["error"]
            if error.status: logs.append(f"ERROR {error.code}: {error.source}")
            return {"handled": error.status, "message": error.source if error.status else ""}
        if kind == "subvi":
            if not project: raise DataflowError("SubVI requires a project")
            target = str(node.properties.get("vi_id", ""))
            child = self.run_project(project, target, inputs)
            if child.errors: raise DataflowError("; ".join(child.errors))
            logs.extend(child.logs)
            vi = project.vis[target]
            return {terminal.name: child.port_values[(terminal.node_id, terminal.port)] for terminal in vi.connector_outputs}
        if kind in ("display", "chart"): return inputs["value"]
        if kind == "log":
            value = inputs["value"]; logs.append(f"{node.properties.get('prefix', '')}{value}"); return value
        raise DataflowError(f"unknown node type: {kind}")

    def _daq(self, node: Node, inputs: dict[str, Any]) -> Any:
        driver_name, channel = str(node.properties.get("driver", "simulated")), str(node.properties.get("channel", ""))
        driver = self.drivers.get(driver_name)
        key = (driver_name, channel)
        config = ChannelConfig(channel, node.type, float(node.properties.get("minimum", -10)),
                               float(node.properties.get("maximum", 10)))
        with self._daq_lock:
            if self._daq_configured.get(key) != config:
                driver.configure(config)
                self._daq_configured[key] = config
            if node.type.endswith("input"):
                return driver.read(channel)
            driver.write(channel, inputs["value"])
            return None

    def _safe_path(self, node: Node) -> Path:
        raw = node.properties.get("path")
        if not isinstance(raw, str) or not raw.strip(): raise ValueError("file path must be non-empty")
        path = (self.data_root / raw).resolve()
        if path != self.data_root and self.data_root not in path.parents: raise ValueError("file path escapes configured data root")
        if not path.parent.is_dir(): raise ValueError("parent directory does not exist")
        return path

    @staticmethod
    def _bounded_int(node: Node, name: str, default: int) -> int:
        value = int(node.properties.get(name, default))
        if value < 0: raise DataflowError(f"{name} must be non-negative")
        return value
