from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
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
from .execution import CancelledError, RunSession
from .resources import ResourceManager
from .protocols import ModbusTcpClient, OPCUA_CAPABILITIES, TcpConnection, UdpEndpoint, open_serial


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
                  drivers: DriverRegistry | None = None, max_sync_workers: int = 64) -> None:
        self.clock = clock
        self.rng = rng or random.Random()
        self.started_at = self.clock()
        self.max_workers = max(1, max_workers)
        if max_sync_workers < 1:
            raise ValueError("max_sync_workers must be positive")
        self.max_sync_workers = max_sync_workers
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
            if graph.nodes[wire.target_node].type == "feedback":
                continue
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
            if node.type in ("visual_case", "visual_for"):
                vi = project.vis.get(str(vi_id)) if project and vi_id else None
                keys = (("true_diagram", "false_diagram") if node.type == "visual_case" else ("body_diagram",))
                for key in keys:
                    if not vi or node.properties.get(key) not in vi.subdiagrams:
                        errors.append(f"{node.label}: referenced subdiagram does not exist: {key}")
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
            try:
                project.validate_structures()
            except ValueError as exc:
                errors.append(str(exc))
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
            vi = project.vis[vi_id]
            for graph in (vi.graph, *vi.subdiagrams.values()):
                for node in graph.nodes.values():
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
            project: Project | None = None, vi_id: str | None = None,
            session: RunSession | None = None, debug: bool = False,
            graph_scope: str | None = None) -> RunResult:
        project = project or graph.project
        owns_session = session is None
        session = session or RunSession()
        session.debug = session.debug or debug
        if session.resources is None:
            session.resources = ResourceManager()
        result = RunResult(statuses={node_id: "idle" for node_id in graph.nodes})
        validation = self.validate(graph, project, vi_id)
        if validation:
            result.errors.extend(validation)
            result.statuses = {node_id: "error" for node_id in graph.nodes}
            if owns_session:
                session.close()
            return result
        controls = control_values or {}
        scope = graph_scope or ("root" if vi_id else "standalone")
        try:
            levels = self._levels(graph)
            for level in levels:
                wait_count = sum(graph.nodes[node_id].type in _WAIT_NODE_TYPES for node_id in level)
                action_count = sum(graph.nodes[node_id].type in _ACTION_NODE_TYPES for node_id in level)
                if wait_count > self.max_sync_workers or action_count > self.max_sync_workers:
                    raise DataflowError(
                        f"synchronization level exceeds max_sync_workers={self.max_sync_workers}")
            with ExitStack() as stack:
                compute_executor = stack.enter_context(ThreadPoolExecutor(
                    max_workers=1 if session.debug else self.max_workers, thread_name_prefix="pylabview-compute"))
                wait_executor = stack.enter_context(ThreadPoolExecutor(
                    max_workers=self.max_sync_workers, thread_name_prefix="pylabview-wait"))
                action_executor = stack.enter_context(ThreadPoolExecutor(
                    max_workers=self.max_sync_workers, thread_name_prefix="pylabview-action"))
                for level in levels:
                    jobs = {}
                    for node_id in level:
                        session.token.check()
                        node = graph.nodes[node_id]
                        incoming = graph.incoming(node_id)
                        inputs = {}
                        for port, wire in incoming.items():
                            if node.type == "feedback":
                                continue
                            value = result.port_values[(wire.source_node, wire.source_port)]
                            expected = graph.port_type(node, "in", port)
                            inputs[port] = value if expected == "variant" else coerce(value, expected)
                        result.statuses[node_id] = "running"
                        session.debugger.before_node(node_id, session.token)
                        session.debugger.emit("node_started", node_id)
                        executor = (wait_executor if node.type in _WAIT_NODE_TYPES else
                                    action_executor if node.type in _ACTION_NODE_TYPES else compute_executor)
                        jobs[node_id] = executor.submit(self._timed_evaluate, node, inputs, controls, project,
                                                        vi_id, scope, session)
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
                            session.debugger.emit("node_completed", node_id, value=result.values[node_id])
                            for wire in graph.wires:
                                if wire.source_node == node_id:
                                    session.debugger.probe(_wire_key(wire), node_id,
                                                           result.port_values.get((node_id, wire.source_port)))
                        except CancelledError:
                            raise
                        except Exception as exc:
                            if session.token.cancelled:
                                raise CancelledError("execution cancelled") from exc
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
            if not result.errors:
                for node in graph.nodes.values():
                    if node.type == "feedback":
                        incoming = graph.incoming(node.id).get("value")
                        if incoming:
                            key = f"feedback:{vi_id or 'graph'}:{scope}:{node.id}"
                            session.state[key] = result.port_values[(incoming.source_node, incoming.source_port)]
        except CancelledError:
            raise
        except Exception as exc:
            result.errors.append(str(exc))
        finally:
            if owns_session:
                session.close()
        return result

    def run_project(self, project: Project, vi_id: str | None = None,
                    inputs: dict[str, Any] | None = None, session: RunSession | None = None,
                    debug: bool = False) -> RunResult:
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
        return self.run(vi.graph, controls, project, target_id, session=session, debug=debug)

    def _timed_evaluate(self, node: Node, inputs: dict[str, Any], controls: dict[str, Any],
                        project: Project | None, caller_vi: str | None, graph_scope: str,
                        session: RunSession) -> tuple[dict[str, Any], Any, list[str], float]:
        started = self.clock()
        logs: list[str] = []
        value = self._evaluate(node, inputs, controls, logs, project, caller_vi, graph_scope, session)
        multi_output = ("cluster_unbundle", "waveform_stats", "file_read", "error_handler", "subvi",
                         "notifier_wait", "event_wait", "udp_receive")
        definition_outputs = NODE_DEFINITIONS[node.type].outputs
        outputs = value if isinstance(value, dict) and (node.type in multi_output or len(definition_outputs) > 1) else {"out": value}
        if node.type not in ("subvi",) and len(definition_outputs) == 1 and definition_outputs[0] != "out":
            outputs = {definition_outputs[0]: value}
        return outputs, value, logs, self.clock() - started

    def _evaluate(self, node: Node, inputs: dict[str, Any], controls: dict[str, Any], logs: list[str],
                  project: Project | None = None, caller_vi: str | None = None,
                  graph_scope: str = "standalone",
                  session: RunSession | None = None) -> Any:
        session = session or RunSession(resources=ResourceManager())
        session.token.check()
        kind = node.type
        if kind in ("numeric_constant", "string_constant", "boolean_constant", "array_constant"):
            return controls.get(node.id, node.properties.get("value"))
        if kind == "bytes_constant": return bytes.fromhex(str(node.properties.get("hex", "")))
        if kind == "structure_input": return controls.get(node.id, controls.get(str(node.properties.get("name", "value"))))
        if kind == "iteration_terminal": return controls.get(node.id, controls.get("iteration", 0))
        if kind == "structure_output": return inputs["value"]
        if kind == "feedback":
            key = f"feedback:{caller_vi or 'graph'}:{graph_scope}:{node.id}"
            return session.state.get(key, node.properties.get("initial", 0.0))
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
            if session.token.wait(seconds): raise CancelledError("execution cancelled")
            return inputs["value"]
        if kind == "timed_loop":
            count = self._bounded_int(node, "iterations", 1)
            if count > self._bounded_int(node, "max_iterations", 1000): raise DataflowError("timed-loop iteration bound exceeded")
            interval = float(node.properties.get("interval", 0.01))
            if interval < 0 or interval > 5: raise DataflowError("timed-loop interval outside bound")
            ticks = []
            for _ in range(count):
                session.token.check(); ticks.append(self.clock())
                if session.token.wait(interval): raise CancelledError("execution cancelled")
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
        if kind == "queue_create":
            return self._session_resource(session, caller_vi, node, "queue",
                                          graph_scope,
                                          lambda: session.resources.create_queue(self._bounded_int(node, "capacity", 100), str(node.properties.get("type_name", "variant"))))
        if kind == "queue_put":
            queue = session.resources.get(inputs["queue"], "queue")
            queue.put(inputs["value"], float(node.properties.get("timeout", 1)), session.token)
            return inputs["queue"]
        if kind == "queue_get":
            return session.resources.get(inputs["queue"], "queue").get(float(node.properties.get("timeout", 1)), session.token)
        if kind == "notifier_create":
            return self._session_resource(session, caller_vi, node, "notifier", graph_scope,
                                          session.resources.create_notifier)
        if kind == "notifier_set":
            return session.resources.get(inputs["notifier"], "notifier").set(inputs["value"])
        if kind == "notifier_wait":
            value, generation = session.resources.get(inputs["notifier"], "notifier").wait(
                int(inputs["generation"]), float(node.properties.get("timeout", 1)), session.token)
            return {"value": value, "generation": generation}
        if kind == "event_create":
            return self._session_resource(session, caller_vi, node, "event",
                                          graph_scope,
                                          lambda: session.resources.create_event(str(node.properties.get("name", "event"))))
        if kind == "event_fire": return session.resources.get(inputs["event"], "event").fire(inputs["value"])
        if kind == "event_wait":
            value, generation = session.resources.get(inputs["event"], "event").wait(
                int(inputs["generation"]), float(node.properties.get("timeout", 1)), session.token)
            return {"value": value, "generation": generation}
        if kind == "channel_create":
            return self._session_resource(session, caller_vi, node, "channel",
                                          graph_scope,
                                          lambda: session.resources.create_channel(self._bounded_int(node, "capacity", 100), str(node.properties.get("type_name", "variant"))))
        if kind == "channel_send":
            channel = session.resources.get(inputs["channel"], "channel")
            channel.put(inputs["value"], float(node.properties.get("timeout", 1)), session.token)
            return inputs["channel"]
        if kind == "channel_receive":
            return session.resources.get(inputs["channel"], "channel").get(float(node.properties.get("timeout", 1)), session.token)
        if kind == "resource_close":
            session.resources.close(inputs["resource"]); return None
        if kind == "tcp_connect":
            return self._session_resource(
                session, caller_vi, node, "tcp",
                graph_scope,
                lambda: session.resources.add("tcp", TcpConnection.connect(
                    str(node.properties.get("host", "127.0.0.1")), node.properties.get("port", 502),
                    float(node.properties.get("timeout", 2)), session.token)))
        if kind == "tcp_read":
            connection = session.resources.get(inputs["connection"], "tcp")
            return connection.read(int(node.properties.get("size", 1024)), float(node.properties.get("timeout", 2)),
                                   session.token, str(node.properties.get("mode", "up_to")),
                                   bytes.fromhex(str(node.properties.get("delimiter_hex", "0a"))))
        if kind == "tcp_write":
            return session.resources.get(inputs["connection"], "tcp").write(
                inputs["data"], float(node.properties.get("timeout", 2)), session.token)
        if kind == "udp_open":
            return self._session_resource(
                session, caller_vi, node, "udp",
                graph_scope,
                lambda: session.resources.add("udp", UdpEndpoint.open(
                    str(node.properties.get("host", "127.0.0.1")), node.properties.get("port", 0),
                    float(node.properties.get("timeout", 2)))))
        if kind == "udp_send":
            return session.resources.get(inputs["endpoint"], "udp").send(
                inputs["data"], str(node.properties.get("host", "127.0.0.1")), node.properties.get("port", 9999),
                float(node.properties.get("timeout", 2)), session.token)
        if kind == "udp_receive":
            data, host, port = session.resources.get(inputs["endpoint"], "udp").receive(
                int(node.properties.get("max_bytes", 65535)), float(node.properties.get("timeout", 2)), session.token)
            return {"data": data, "host": host, "port": port}
        if kind == "modbus_connect":
            return self._session_resource(
                session, caller_vi, node, "modbus",
                graph_scope,
                lambda: session.resources.add("modbus", ModbusTcpClient(
                    TcpConnection.connect(str(node.properties.get("host", "127.0.0.1")),
                                          node.properties.get("port", 502),
                                          float(node.properties.get("timeout", 2)), session.token),
                    node.properties.get("unit_id", 1))))
        if kind == "modbus_read_holding":
            return session.resources.get(inputs["client"], "modbus").read_holding_registers(
                node.properties.get("address", 0), node.properties.get("quantity", 1),
                float(node.properties.get("timeout", 2)), session.token)
        if kind == "modbus_write_register":
            return session.resources.get(inputs["client"], "modbus").write_single_register(
                node.properties.get("address", 0), inputs["value"],
                float(node.properties.get("timeout", 2)), session.token)
        if kind == "serial_open":
            return self._session_resource(
                session, caller_vi, node, "serial",
                graph_scope,
                lambda: session.resources.add("serial", open_serial(
                    str(node.properties.get("port", "COM1")), int(node.properties.get("baudrate", 9600)),
                    float(node.properties.get("timeout", 1)))))
        if kind == "opcua_unavailable": raise DataflowError(OPCUA_CAPABILITIES.reason)
        if kind == "visual_case":
            diagram_id = str(node.properties.get("true_diagram" if inputs["selector"] else "false_diagram", ""))
            return self._run_structure(project, caller_vi, diagram_id, inputs["value"], 0, session)
        if kind == "visual_for":
            values = inputs["array"]
            maximum = self._bounded_int(node, "max_iterations", 1000)
            if len(values) > maximum: raise DataflowError("visual for-loop iteration bound exceeded")
            diagram_id = str(node.properties.get("body_diagram", ""))
            return [self._run_structure(project, caller_vi, diagram_id, value, index, session)
                    for index, value in enumerate(values)]
        if kind == "subvi":
            if not project: raise DataflowError("SubVI requires a project")
            target = str(node.properties.get("vi_id", ""))
            child = self.run_project(project, target, inputs, session=session)
            session.token.check()
            if child.errors: raise DataflowError("; ".join(child.errors))
            logs.extend(child.logs)
            vi = project.vis[target]
            return {terminal.name: child.port_values[(terminal.node_id, terminal.port)] for terminal in vi.connector_outputs}
        if kind in ("display", "chart"): return inputs["value"]
        if kind == "log":
            value = inputs["value"]; logs.append(f"{node.properties.get('prefix', '')}{value}"); return value
        from .plugins import DEFAULT_PLUGIN_REGISTRY
        evaluator = DEFAULT_PLUGIN_REGISTRY.evaluator(kind)
        if evaluator:
            return evaluator(node, inputs, session)
        raise DataflowError(f"unknown node type: {kind}")

    def _run_structure(self, project: Project | None, vi_id: str | None, diagram_id: str,
                       value: Any, iteration: int, session: RunSession) -> Any:
        if not project or vi_id not in project.vis:
            raise DataflowError("visual structure requires a project VI")
        graph = project.vis[str(vi_id)].subdiagrams.get(diagram_id)
        if not graph:
            raise DataflowError(f"visual structure subdiagram does not exist: {diagram_id}")
        controls: dict[str, Any] = {"value": value, "iteration": iteration}
        for child in graph.nodes.values():
            if child.type == "structure_input": controls[child.id] = value
            if child.type == "iteration_terminal": controls[child.id] = iteration
        result = self.run(graph, controls, project, str(vi_id), session=session, graph_scope=diagram_id)
        session.token.check()
        if result.errors: raise DataflowError("; ".join(result.errors))
        outputs = [result.values[child.id] for child in graph.nodes.values() if child.type == "structure_output"]
        if len(outputs) != 1: raise DataflowError("structure subdiagram must contain exactly one output tunnel")
        return outputs[0]

    @staticmethod
    def _session_resource(session: RunSession, vi_id: str | None, node: Node, kind: str,
                          graph_scope: str,
                          create: Callable[[], Any]) -> Any:
        key = f"resource:{vi_id or 'graph'}:{graph_scope}:{node.id}"
        ref = session.state.get(key)
        if ref is not None:
            try:
                session.resources.get(ref, kind)
                return ref
            except Exception:
                session.state.pop(key, None)
        ref = create()
        session.state[key] = ref
        return ref

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


def _wire_key(wire: Any) -> str:
    return f"{wire.source_node}:{wire.source_port}->{wire.target_node}:{wire.target_port}"


_WAIT_NODE_TYPES = {
    "delay", "timed_loop", "queue_get", "notifier_wait", "event_wait", "channel_receive",
    "tcp_connect", "tcp_read", "udp_receive", "modbus_connect", "modbus_read_holding",
    "serial_open", "subvi", "visual_case", "visual_for",
}

_ACTION_NODE_TYPES = {
    "queue_put", "notifier_set", "event_fire", "channel_send", "tcp_write", "udp_send",
    "modbus_write_register", "resource_close",
}
