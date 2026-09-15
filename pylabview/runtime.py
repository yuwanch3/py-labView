from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable
import math
import random
import time

from .model import Graph, NODE_DEFINITIONS, Node


class DataflowError(Exception):
    """A graph validation or execution error."""


@dataclass
class RunResult:
    values: dict[str, Any] = field(default_factory=dict)
    statuses: dict[str, str] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    logs: list[str] = field(default_factory=list)


class DataflowRuntime:
    def __init__(self, clock: Callable[[], float] = time.monotonic, rng: random.Random | None = None) -> None:
        self.clock = clock
        self.rng = rng or random.Random()
        self.started_at = self.clock()

    def reset(self) -> None:
        self.started_at = self.clock()

    def topological_order(self, graph: Graph) -> list[str]:
        indegree = {node_id: 0 for node_id in graph.nodes}
        following: dict[str, list[str]] = {node_id: [] for node_id in graph.nodes}
        for wire in graph.wires:
            indegree[wire.target_node] += 1
            following[wire.source_node].append(wire.target_node)
        queue = [node_id for node_id, degree in indegree.items() if degree == 0]
        order: list[str] = []
        while queue:
            node_id = queue.pop(0)
            order.append(node_id)
            for target in following[node_id]:
                indegree[target] -= 1
                if indegree[target] == 0:
                    queue.append(target)
        if len(order) != len(graph.nodes):
            cyclic = [graph.nodes[node_id].label for node_id, degree in indegree.items() if degree]
            raise DataflowError("Cycle detected: " + ", ".join(cyclic))
        return order

    def validate(self, graph: Graph) -> list[str]:
        errors: list[str] = []
        try:
            self.topological_order(graph)
        except DataflowError as exc:
            errors.append(str(exc))
        for node in graph.nodes.values():
            connected = graph.incoming(node.id)
            for port in NODE_DEFINITIONS[node.type].inputs:
                if port not in connected:
                    errors.append(f"{node.label}: missing input '{port}'")
        return errors

    def run(self, graph: Graph, control_values: dict[str, Any] | None = None) -> RunResult:
        result = RunResult(statuses={node_id: "idle" for node_id in graph.nodes})
        validation = self.validate(graph)
        if validation:
            result.errors.extend(validation)
            for node_id in graph.nodes:
                result.statuses[node_id] = "error"
            return result
        controls = control_values or {}
        try:
            order = self.topological_order(graph)
            for node_id in order:
                node = graph.nodes[node_id]
                result.statuses[node_id] = "running"
                incoming = graph.incoming(node_id)
                inputs = {port: result.values[wire.source_node] for port, wire in incoming.items()}
                value = self._evaluate(node, inputs, controls, result.logs)
                result.values[node_id] = value
                result.statuses[node_id] = "success"
        except Exception as exc:
            result.statuses[node_id] = "error"
            result.errors.append(f"{graph.nodes[node_id].label}: {exc}")
        return result

    def _evaluate(self, node: Node, inputs: dict[str, Any], controls: dict[str, Any], logs: list[str]) -> Any:
        kind = node.type
        if kind in ("numeric_constant", "string_constant", "boolean_constant"):
            return controls.get(node.id, node.properties.get("value"))
        if kind == "add":
            return inputs["a"] + inputs["b"]
        if kind == "subtract":
            return inputs["a"] - inputs["b"]
        if kind == "multiply":
            return inputs["a"] * inputs["b"]
        if kind == "divide":
            if inputs["b"] == 0:
                raise DataflowError("division by zero")
            return inputs["a"] / inputs["b"]
        if kind == "sine":
            return math.sin(float(inputs["x"]))
        if kind == "compare":
            operators = {
                ">": lambda a, b: a > b, "<": lambda a, b: a < b, "==": lambda a, b: a == b,
                ">=": lambda a, b: a >= b, "<=": lambda a, b: a <= b, "!=": lambda a, b: a != b,
            }
            operator = node.properties.get("operator", ">")
            if operator not in operators:
                raise DataflowError(f"unsupported comparison: {operator}")
            return operators[operator](inputs["a"], inputs["b"])
        if kind == "select":
            return inputs["true"] if inputs["condition"] else inputs["false"]
        if kind == "random":
            return self.rng.random()
        if kind == "timer":
            return self.clock() - self.started_at
        if kind == "analog_input":
            low = float(node.properties.get("minimum", -10.0))
            high = float(node.properties.get("maximum", 10.0))
            if low > high:
                raise DataflowError("minimum must not exceed maximum")
            return self.rng.uniform(low, high)
        if kind in ("display", "chart"):
            return inputs["value"]
        if kind == "log":
            text = f"{node.properties.get('prefix', '')}{inputs['value']}"
            logs.append(text)
            return inputs["value"]
        raise DataflowError(f"unknown node type: {kind}")
