from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any
import copy
import uuid


@dataclass(frozen=True)
class NodeDefinition:
    title: str
    category: str
    inputs: tuple[str, ...] = ()
    outputs: tuple[str, ...] = ("out",)
    defaults: dict[str, Any] = field(default_factory=dict)
    front_panel: str | None = None


NODE_DEFINITIONS: dict[str, NodeDefinition] = {
    "numeric_constant": NodeDefinition("Numeric", "Constants", defaults={"value": 0.0}, front_panel="control"),
    "string_constant": NodeDefinition("String", "Constants", defaults={"value": "text"}, front_panel="control"),
    "boolean_constant": NodeDefinition("Boolean", "Constants", defaults={"value": True}, front_panel="control"),
    "add": NodeDefinition("Add", "Arithmetic", ("a", "b")),
    "subtract": NodeDefinition("Subtract", "Arithmetic", ("a", "b")),
    "multiply": NodeDefinition("Multiply", "Arithmetic", ("a", "b")),
    "divide": NodeDefinition("Divide", "Arithmetic", ("a", "b")),
    "sine": NodeDefinition("Sine", "Math", ("x",)),
    "compare": NodeDefinition("Compare", "Logic", ("a", "b"), defaults={"operator": ">"}),
    "select": NodeDefinition("Select", "Logic", ("condition", "true", "false")),
    "random": NodeDefinition("Random", "Sources"),
    "timer": NodeDefinition("Timer", "Sources", defaults={"mode": "elapsed"}),
    "analog_input": NodeDefinition(
        "Analog Input", "Sources", defaults={"channel": "AI0", "minimum": -10.0, "maximum": 10.0}
    ),
    "display": NodeDefinition("Display", "Outputs", ("value",), (), front_panel="indicator"),
    "chart": NodeDefinition("Waveform Chart", "Outputs", ("value",), (), defaults={"history": 100}, front_panel="chart"),
    "log": NodeDefinition("Log Output", "Outputs", ("value",), (), defaults={"prefix": ""}),
}


@dataclass
class Node:
    id: str
    type: str
    x: float
    y: float
    label: str
    properties: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def create(cls, node_type: str, x: float, y: float) -> "Node":
        definition = NODE_DEFINITIONS[node_type]
        return cls(uuid.uuid4().hex[:10], node_type, x, y, definition.title, copy.deepcopy(definition.defaults))


@dataclass
class Wire:
    source_node: str
    source_port: str
    target_node: str
    target_port: str


class Graph:
    def __init__(self, name: str = "Untitled") -> None:
        self.name = name
        self.nodes: dict[str, Node] = {}
        self.wires: list[Wire] = []

    def add_node(self, node_type: str, x: float = 100, y: float = 100) -> Node:
        if node_type not in NODE_DEFINITIONS:
            raise ValueError(f"Unknown node type: {node_type}")
        node = Node.create(node_type, x, y)
        self.nodes[node.id] = node
        return node

    def remove_node(self, node_id: str) -> None:
        if node_id not in self.nodes:
            return
        del self.nodes[node_id]
        self.wires = [w for w in self.wires if node_id not in (w.source_node, w.target_node)]

    def connect(self, source_node: str, source_port: str, target_node: str, target_port: str) -> Wire:
        if source_node == target_node:
            raise ValueError("A node cannot be wired to itself")
        source = self.nodes[source_node]
        target = self.nodes[target_node]
        if source_port not in NODE_DEFINITIONS[source.type].outputs:
            raise ValueError(f"Unknown output port: {source_port}")
        if target_port not in NODE_DEFINITIONS[target.type].inputs:
            raise ValueError(f"Unknown input port: {target_port}")
        self.wires = [
            w for w in self.wires if not (w.target_node == target_node and w.target_port == target_port)
        ]
        wire = Wire(source_node, source_port, target_node, target_port)
        self.wires.append(wire)
        return wire

    def disconnect(self, wire: Wire) -> None:
        if wire in self.wires:
            self.wires.remove(wire)

    def incoming(self, node_id: str) -> dict[str, Wire]:
        return {w.target_port: w for w in self.wires if w.target_node == node_id}

    def to_dict(self) -> dict[str, Any]:
        return {
            "format": "pylabview-project",
            "version": 1,
            "name": self.name,
            "nodes": [asdict(node) for node in self.nodes.values()],
            "wires": [asdict(wire) for wire in self.wires],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Graph":
        if data.get("format") != "pylabview-project":
            raise ValueError("Not a PyLabView Studio project")
        graph = cls(str(data.get("name", "Untitled")))
        for item in data.get("nodes", []):
            node = Node(**item)
            if node.type not in NODE_DEFINITIONS:
                raise ValueError(f"Unknown node type in project: {node.type}")
            graph.nodes[node.id] = node
        for item in data.get("wires", []):
            wire = Wire(**item)
            if wire.source_node not in graph.nodes or wire.target_node not in graph.nodes:
                raise ValueError("Wire references a missing node")
            graph.connect(wire.source_node, wire.source_port, wire.target_node, wire.target_port)
        return graph

    def clone(self) -> "Graph":
        return Graph.from_dict(copy.deepcopy(self.to_dict()))
