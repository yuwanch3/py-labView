from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any
import copy
import math
import uuid

from .typesystem import ARRAY, BOOLEAN, CLUSTER, DATA_TYPES, ERROR, NUMERIC, STRING, VARIANT, WAVEFORM, compatible


@dataclass(frozen=True)
class NodeDefinition:
    title: str
    category: str
    inputs: tuple[str, ...] = ()
    outputs: tuple[str, ...] = ("out",)
    defaults: dict[str, Any] = field(default_factory=dict)
    front_panel: str | None = None
    input_types: tuple[str, ...] = ()
    output_types: tuple[str, ...] = ()

    def type_for_input(self, port: str) -> str:
        return self.input_types[self.inputs.index(port)] if self.input_types else VARIANT

    def type_for_output(self, port: str) -> str:
        return self.output_types[self.outputs.index(port)] if self.output_types else VARIANT


def _d(title: str, category: str, inputs: tuple[str, ...] = (), outputs: tuple[str, ...] = ("out",),
       defaults: dict[str, Any] | None = None, front_panel: str | None = None,
       input_types: tuple[str, ...] = (), output_types: tuple[str, ...] = ()) -> NodeDefinition:
    return NodeDefinition(title, category, inputs, outputs, defaults or {}, front_panel, input_types, output_types)


NODE_DEFINITIONS: dict[str, NodeDefinition] = {
    "numeric_constant": _d("Numeric", "Constants", defaults={"value": 0.0, "display_type": "numeric"}, front_panel="control", output_types=(NUMERIC,)),
    "string_constant": _d("String", "Constants", defaults={"value": "text", "display_type": "string"}, front_panel="control", output_types=(STRING,)),
    "boolean_constant": _d("Boolean", "Constants", defaults={"value": True, "display_type": "boolean"}, front_panel="control", output_types=(BOOLEAN,)),
    "array_constant": _d("Array", "Constants", defaults={"value": [], "display_type": "array"}, front_panel="control", output_types=(ARRAY,)),
    "add": _d("Add", "Numeric", ("a", "b"), input_types=(NUMERIC, NUMERIC), output_types=(NUMERIC,)),
    "subtract": _d("Subtract", "Numeric", ("a", "b"), input_types=(NUMERIC, NUMERIC), output_types=(NUMERIC,)),
    "multiply": _d("Multiply", "Numeric", ("a", "b"), input_types=(NUMERIC, NUMERIC), output_types=(NUMERIC,)),
    "divide": _d("Divide", "Numeric", ("a", "b"), input_types=(NUMERIC, NUMERIC), output_types=(NUMERIC,)),
    "numeric_min": _d("Minimum", "Numeric", ("a", "b"), input_types=(NUMERIC, NUMERIC), output_types=(NUMERIC,)),
    "numeric_max": _d("Maximum", "Numeric", ("a", "b"), input_types=(NUMERIC, NUMERIC), output_types=(NUMERIC,)),
    "absolute": _d("Absolute", "Numeric", ("x",), input_types=(NUMERIC,), output_types=(NUMERIC,)),
    "sine": _d("Sine", "Numeric", ("x",), input_types=(NUMERIC,), output_types=(NUMERIC,)),
    "compare": _d("Compare", "Logic", ("a", "b"), defaults={"operator": ">"}, input_types=(VARIANT, VARIANT), output_types=(BOOLEAN,)),
    "select": _d("Select", "Structures", ("condition", "true", "false"), input_types=(BOOLEAN, VARIANT, VARIANT)),
    "case": _d("Case", "Structures", ("selector", "true", "false"), input_types=(BOOLEAN, VARIANT, VARIANT)),
    "sequence": _d("Sequence", "Structures", ("first", "second"), input_types=(VARIANT, VARIANT)),
    "for_loop": _d("For Loop", "Structures", ("array",), defaults={"max_iterations": 1000, "operation": "identity", "scale": 1.0}, input_types=(ARRAY,), output_types=(ARRAY,)),
    "while_loop": _d("While Loop", "Structures", ("initial",), defaults={"max_iterations": 100, "condition": "less_than", "limit": 10.0, "step": 1.0}, input_types=(NUMERIC,), output_types=(NUMERIC,)),
    "boolean_and": _d("AND", "Boolean", ("a", "b"), input_types=(BOOLEAN, BOOLEAN), output_types=(BOOLEAN,)),
    "boolean_or": _d("OR", "Boolean", ("a", "b"), input_types=(BOOLEAN, BOOLEAN), output_types=(BOOLEAN,)),
    "boolean_not": _d("NOT", "Boolean", ("value",), input_types=(BOOLEAN,), output_types=(BOOLEAN,)),
    "string_concat": _d("Concatenate", "String", ("a", "b"), input_types=(STRING, STRING), output_types=(STRING,)),
    "string_format": _d("Format", "String", ("value",), defaults={"template": "{}"}, input_types=(VARIANT,), output_types=(STRING,)),
    "array_build": _d("Build Array", "Array", ("a", "b"), input_types=(VARIANT, VARIANT), output_types=(ARRAY,)),
    "array_index": _d("Index Array", "Array", ("array", "index"), input_types=(ARRAY, NUMERIC)),
    "array_size": _d("Array Size", "Array", ("array",), input_types=(ARRAY,), output_types=(NUMERIC,)),
    "cluster_bundle": _d("Bundle", "Cluster", ("a", "b"), defaults={"name_a": "a", "name_b": "b"}, input_types=(VARIANT, VARIANT), output_types=(CLUSTER,)),
    "cluster_unbundle": _d("Unbundle", "Cluster", ("cluster",), ("a", "b"), {"name_a": "a", "name_b": "b"}, input_types=(CLUSTER,), output_types=(VARIANT, VARIANT)),
    "waveform_create": _d("Create Waveform", "Waveform", ("t0", "dt", "y"), input_types=(NUMERIC, NUMERIC, ARRAY), output_types=(WAVEFORM,)),
    "waveform_stats": _d("Waveform Stats", "Waveform", ("waveform",), ("min", "max", "mean"), input_types=(WAVEFORM,), output_types=(NUMERIC, NUMERIC, NUMERIC)),
    "random": _d("Random", "Sources", output_types=(NUMERIC,)),
    "timer": _d("Timer", "Timing", defaults={"mode": "elapsed"}, output_types=(NUMERIC,)),
    "delay": _d("Delay", "Timing", ("value",), defaults={"seconds": 0.01, "maximum_seconds": 5.0}),
    "timed_loop": _d("Timed Loop", "Timing", defaults={"iterations": 1, "interval": 0.01, "max_iterations": 1000}, output_types=(ARRAY,)),
    "analog_input": _d("Analog Input", "DAQ", defaults={"driver": "simulated", "channel": "AI0", "minimum": -10.0, "maximum": 10.0}, output_types=(NUMERIC,)),
    "analog_output": _d("Analog Output", "DAQ", ("value",), (), {"driver": "simulated", "channel": "AO0", "minimum": -10.0, "maximum": 10.0}, input_types=(NUMERIC,)),
    "digital_input": _d("Digital Input", "DAQ", defaults={"driver": "simulated", "channel": "DI0"}, output_types=(BOOLEAN,)),
    "digital_output": _d("Digital Output", "DAQ", ("value",), (), {"driver": "simulated", "channel": "DO0"}, input_types=(BOOLEAN,)),
    "file_read": _d("Read Text File", "File", outputs=("text", "error"), defaults={"path": "input.txt"}, output_types=(STRING, ERROR)),
    "file_write": _d("Write Text File", "File", ("text",), ("error",), {"path": "output.txt"}, input_types=(STRING,), output_types=(ERROR,)),
    "csv_logger": _d("CSV Logger", "File", ("value",), ("error",), {"path": "data.csv"}, input_types=(VARIANT,), output_types=(ERROR,)),
    "error_constant": _d("Error Constant", "Error", outputs=("error",), defaults={"status": False, "code": 0, "source": ""}, output_types=(ERROR,)),
    "error_merge": _d("Merge Errors", "Error", ("a", "b"), ("error",), input_types=(ERROR, ERROR), output_types=(ERROR,)),
    "error_handler": _d("Error Handler", "Error", ("error",), ("handled", "message"), input_types=(ERROR,), output_types=(BOOLEAN, STRING)),
    "display": _d("Display", "Outputs", ("value",), (), {"display_type": "auto", "style": "default"}, "indicator"),
    "chart": _d("Waveform Chart", "Outputs", ("value",), (), {"history": 100, "display_type": "waveform_chart", "style": "default"}, "chart"),
    "log": _d("Log Output", "Outputs", ("value",), (), {"prefix": ""}),
    "subvi": _d("SubVI", "Project", defaults={"vi_id": ""}),
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
    data_type: str = VARIANT


class Graph:
    def __init__(self, name: str = "Untitled") -> None:
        self.name = name
        self.nodes: dict[str, Node] = {}
        self.wires: list[Wire] = []
        self.project: Project | None = None

    def add_node(self, node_type: str, x: float = 100, y: float = 100) -> Node:
        if node_type not in NODE_DEFINITIONS:
            raise ValueError(f"Unknown node type: {node_type}")
        node = Node.create(node_type, x, y)
        self.nodes[node.id] = node
        return node

    def remove_node(self, node_id: str) -> None:
        self.nodes.pop(node_id, None)
        self.wires = [w for w in self.wires if node_id not in (w.source_node, w.target_node)]

    def ports(self, node: Node, direction: str) -> tuple[str, ...]:
        if node.type == "subvi" and self.project:
            vi = self.project.vis.get(str(node.properties.get("vi_id", "")))
            if vi:
                terms = vi.connector_inputs if direction == "in" else vi.connector_outputs
                return tuple(term.name for term in terms)
        definition = NODE_DEFINITIONS[node.type]
        return definition.inputs if direction == "in" else definition.outputs

    def port_type(self, node: Node, direction: str, port: str) -> str:
        if node.type == "subvi" and self.project:
            vi = self.project.vis.get(str(node.properties.get("vi_id", "")))
            if vi:
                terms = vi.connector_inputs if direction == "in" else vi.connector_outputs
                return next(term.data_type for term in terms if term.name == port)
        definition = NODE_DEFINITIONS[node.type]
        return definition.type_for_input(port) if direction == "in" else definition.type_for_output(port)

    def connect(self, source_node: str, source_port: str, target_node: str, target_port: str) -> Wire:
        if source_node == target_node:
            raise ValueError("A node cannot be wired to itself")
        source, target = self.nodes[source_node], self.nodes[target_node]
        if source_port not in self.ports(source, "out"):
            raise ValueError(f"Unknown output port: {source_port}")
        if target_port not in self.ports(target, "in"):
            raise ValueError(f"Unknown input port: {target_port}")
        source_type = self.port_type(source, "out", source_port)
        target_type = self.port_type(target, "in", target_port)
        if not compatible(source_type, target_type):
            raise ValueError(f"Incompatible wire types: {source_type} -> {target_type}")
        self.wires = [w for w in self.wires if not (w.target_node == target_node and w.target_port == target_port)]
        wire = Wire(source_node, source_port, target_node, target_port, source_type if source_type != VARIANT else target_type)
        self.wires.append(wire)
        return wire

    def disconnect(self, wire: Wire) -> None:
        if wire in self.wires:
            self.wires.remove(wire)

    def incoming(self, node_id: str) -> dict[str, Wire]:
        return {w.target_port: w for w in self.wires if w.target_node == node_id}

    def to_dict(self) -> dict[str, Any]:
        return {"format": "pylabview-project", "version": 1, "name": self.name,
                "nodes": [asdict(node) for node in self.nodes.values()], "wires": [asdict(wire) for wire in self.wires]}

    def graph_dict(self) -> dict[str, Any]:
        return {"name": self.name, "nodes": [asdict(node) for node in self.nodes.values()],
                "wires": [asdict(wire) for wire in self.wires]}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Graph":
        try:
            if not isinstance(data, dict):
                raise ValueError("graph must be an object")
            standalone = "format" in data or "version" in data
            expected = ({"format", "version", "name", "nodes", "wires"} if standalone
                        else {"name", "nodes", "wires"})
            if set(data) != expected:
                raise ValueError("invalid graph schema")
            if standalone and (data["format"] != "pylabview-project" or type(data["version"]) is not int
                               or data["version"] != 1):
                raise ValueError("unsupported graph format version")
            if not isinstance(data["name"], str) or not isinstance(data["nodes"], list) or not isinstance(data["wires"], list):
                raise ValueError("invalid graph fields")
            graph = cls(data["name"])
            for item in data["nodes"]:
                if not isinstance(item, dict) or set(item) != {"id", "type", "x", "y", "label", "properties"}:
                    raise ValueError("invalid node schema")
                node = Node(**item)
                if (not isinstance(node.id, str) or not node.id or node.id in graph.nodes
                        or not isinstance(node.type, str) or node.type not in NODE_DEFINITIONS
                        or not isinstance(node.label, str) or not isinstance(node.properties, dict)
                        or isinstance(node.x, bool) or not isinstance(node.x, (int, float)) or not math.isfinite(node.x)
                        or isinstance(node.y, bool) or not isinstance(node.y, (int, float)) or not math.isfinite(node.y)):
                    raise ValueError(f"invalid or duplicate node: {node.id}")
                graph.nodes[node.id] = node
            required_wire = {"source_node", "source_port", "target_node", "target_port"}
            for item in data["wires"]:
                if (not isinstance(item, dict) or not required_wire <= set(item)
                        or not set(item) <= required_wire | {"data_type"}
                        or any(not isinstance(item[key], str) or not item[key] for key in required_wire)
                        or ("data_type" in item and item["data_type"] not in DATA_TYPES)):
                    raise ValueError("invalid wire schema")
                if item["source_node"] not in graph.nodes or item["target_node"] not in graph.nodes:
                    raise ValueError("wire references a missing node")
                source, target = graph.nodes[item["source_node"]], graph.nodes[item["target_node"]]
                if "subvi" in (source.type, target.type):
                    graph.wires.append(Wire(item["source_node"], item["source_port"], item["target_node"],
                                            item["target_port"], item.get("data_type", VARIANT)))
                else:
                    graph.connect(item["source_node"], item["source_port"], item["target_node"], item["target_port"])
            return graph
        except ValueError:
            raise
        except (AttributeError, KeyError, StopIteration, TypeError) as exc:
            raise ValueError("invalid graph schema") from exc

    def clone(self) -> "Graph":
        return Graph.from_dict(copy.deepcopy(self.to_dict()))


@dataclass
class ConnectorTerminal:
    name: str
    node_id: str
    port: str = "out"
    data_type: str = VARIANT


@dataclass
class VirtualInstrument:
    id: str
    name: str
    graph: Graph = field(default_factory=Graph)
    connector_inputs: list[ConnectorTerminal] = field(default_factory=list)
    connector_outputs: list[ConnectorTerminal] = field(default_factory=list)
    front_panel: dict[str, Any] = field(default_factory=lambda: {"title": "", "layout": {}})

    @classmethod
    def create(cls, name: str) -> "VirtualInstrument":
        return cls(uuid.uuid4().hex[:10], name, Graph(name))


class Project:
    def __init__(self, name: str = "Untitled Project") -> None:
        self.name = name
        vi = VirtualInstrument.create("Main VI")
        self.vis: dict[str, VirtualInstrument] = {vi.id: vi}
        self.main_vi = vi.id
        self._bind_graphs()

    @property
    def main(self) -> VirtualInstrument:
        return self.vis[self.main_vi]

    def add_vi(self, name: str) -> VirtualInstrument:
        clean_name = name.strip()
        if not clean_name or any(vi.name == clean_name for vi in self.vis.values()):
            raise ValueError("VI name must be non-empty and unique")
        vi = VirtualInstrument.create(clean_name)
        self.vis[vi.id] = vi
        vi.graph.project = self
        return vi

    def rename_vi(self, vi_id: str, name: str) -> None:
        clean_name = name.strip()
        if vi_id not in self.vis or not clean_name or any(vi.name == clean_name and vi.id != vi_id for vi in self.vis.values()):
            raise ValueError("VI name must be non-empty and unique")
        self.vis[vi_id].name = clean_name
        self.vis[vi_id].graph.name = clean_name

    def delete_vi(self, vi_id: str) -> None:
        if vi_id == self.main_vi:
            raise ValueError("cannot delete main VI")
        if vi_id not in self.vis:
            raise ValueError("unknown VI")
        if any(n.type == "subvi" and n.properties.get("vi_id") == vi_id for vi in self.vis.values() for n in vi.graph.nodes.values()):
            raise ValueError("VI is referenced by a SubVI node")
        del self.vis[vi_id]

    def set_main(self, vi_id: str) -> None:
        if vi_id not in self.vis:
            raise ValueError("unknown VI")
        self.main_vi = vi_id

    def to_dict(self) -> dict[str, Any]:
        return {"format": "pylabview-project", "version": 2, "name": self.name, "main_vi": self.main_vi,
                "vis": [{"id": vi.id, "name": vi.name, "graph": vi.graph.graph_dict(),
                         "connector_pane": {"inputs": [asdict(t) for t in vi.connector_inputs], "outputs": [asdict(t) for t in vi.connector_outputs]},
                         "front_panel": copy.deepcopy(vi.front_panel)} for vi in self.vis.values()]}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Project":
        try:
            if not isinstance(data, dict):
                raise ValueError("project must be an object")
            required = {"format", "version", "name", "main_vi", "vis"}
            if set(data) != required:
                raise ValueError("invalid project v2 schema")
            if data["format"] != "pylabview-project" or type(data["version"]) is not int or data["version"] != 2:
                raise ValueError("unsupported project format version")
            if (not isinstance(data["name"], str) or not isinstance(data["main_vi"], str) or not data["main_vi"]
                    or not isinstance(data["vis"], list) or not data["vis"]):
                raise ValueError("invalid project fields")
            project = cls.__new__(cls)
            project.name, project.main_vi, project.vis = data["name"], data["main_vi"], {}
            vi_names: set[str] = set()
            terminal_fields = {"name", "node_id", "port", "data_type"}
            for item in data["vis"]:
                if not isinstance(item, dict) or set(item) != {"id", "name", "graph", "connector_pane", "front_panel"}:
                    raise ValueError("invalid VI schema")
                if (not isinstance(item["id"], str) or not item["id"] or item["id"] in project.vis
                        or not isinstance(item["name"], str) or not item["name"]
                        or item["name"] in vi_names
                        or not isinstance(item["front_panel"], dict)):
                    raise ValueError("invalid or duplicate VI")
                vi_names.add(item["name"])
                pane = item["connector_pane"]
                if (not isinstance(pane, dict) or set(pane) != {"inputs", "outputs"}
                        or not isinstance(pane["inputs"], list) or not isinstance(pane["outputs"], list)):
                    raise ValueError("invalid connector pane")
                terminals: list[list[ConnectorTerminal]] = []
                for entries in (pane["inputs"], pane["outputs"]):
                    parsed: list[ConnectorTerminal] = []
                    for terminal in entries:
                        if (not isinstance(terminal, dict) or set(terminal) != terminal_fields
                                or any(not isinstance(terminal[key], str) or not terminal[key]
                                       for key in ("name", "node_id", "port"))
                                or terminal["data_type"] not in DATA_TYPES):
                            raise ValueError("invalid connector terminal schema")
                        parsed.append(ConnectorTerminal(**terminal))
                    terminals.append(parsed)
                graph = Graph.from_dict(item["graph"])
                project.vis[item["id"]] = VirtualInstrument(
                    item["id"], item["name"], graph, terminals[0], terminals[1], copy.deepcopy(item["front_panel"])
                )
            if project.main_vi not in project.vis:
                raise ValueError("main_vi references a missing VI")
            project._bind_graphs()
            for vi in project.vis.values():
                wires, vi.graph.wires = vi.graph.wires, []
                for wire in wires:
                    vi.graph.connect(wire.source_node, wire.source_port, wire.target_node, wire.target_port)
            project.validate_connectors()
            return project
        except ValueError:
            raise
        except (AttributeError, KeyError, StopIteration, TypeError) as exc:
            raise ValueError("invalid project v2 schema") from exc

    @classmethod
    def migrate_v1(cls, data: dict[str, Any]) -> "Project":
        graph = Graph.from_dict(data)
        project = cls(str(data.get("name", "Migrated Project")))
        vi = project.main
        vi.name, vi.graph = graph.name, graph
        project._bind_graphs()
        return project

    def validate_connectors(self) -> None:
        for vi in self.vis.values():
            names: set[str] = set()
            input_nodes: set[str] = set()
            for is_input, terms in ((True, vi.connector_inputs), (False, vi.connector_outputs)):
                for term in terms:
                    if (not isinstance(term, ConnectorTerminal) or not isinstance(term.name, str) or not term.name
                            or not isinstance(term.node_id, str) or not isinstance(term.port, str)
                            or term.name in names or term.node_id not in vi.graph.nodes or term.data_type not in DATA_TYPES):
                        raise ValueError(f"invalid connector terminal in {vi.name}")
                    names.add(term.name)
                    node = vi.graph.nodes[term.node_id]
                    if is_input:
                        if term.node_id in input_nodes or NODE_DEFINITIONS[node.type].front_panel != "control":
                            raise ValueError(f"connector input must reference a unique control output: {term.name}")
                        input_nodes.add(term.node_id)
                    if term.port not in vi.graph.ports(node, "out"):
                        raise ValueError(f"connector references missing port: {term.port}")
                    if not compatible(vi.graph.port_type(node, "out", term.port), term.data_type):
                        raise ValueError(f"connector type mismatch: {term.name}")

    def _bind_graphs(self) -> None:
        for vi in self.vis.values():
            vi.graph.project = self


def project_snapshot(project: Project, current_vi_id: str) -> dict[str, Any]:
    if current_vi_id not in project.vis:
        raise ValueError("current VI is not in project")
    return {"project": copy.deepcopy(project.to_dict()), "current_vi_id": current_vi_id}


def restore_project_snapshot(snapshot: dict[str, Any]) -> tuple[Project, str]:
    if not isinstance(snapshot, dict) or set(snapshot) != {"project", "current_vi_id"}:
        raise ValueError("invalid project snapshot")
    project = Project.from_dict(copy.deepcopy(snapshot["project"]))
    current_vi_id = snapshot["current_vi_id"]
    if not isinstance(current_vi_id, str) or current_vi_id not in project.vis:
        raise ValueError("snapshot references a missing current VI")
    return project, current_vi_id
