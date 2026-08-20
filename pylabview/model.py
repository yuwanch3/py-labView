from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any
import copy
import math
import uuid

from .typesystem import ARRAY, BOOLEAN, CLUSTER, DATA_TYPES, ERROR, IMAGE, NUMERIC, STRING, VARIANT, WAVEFORM, compatible


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
    "case": _d("Legacy Functional Case", "Legacy Structures", ("selector", "true", "false"), input_types=(BOOLEAN, VARIANT, VARIANT)),
    "sequence": _d("Legacy Functional Sequence", "Legacy Structures", ("first", "second"), input_types=(VARIANT, VARIANT)),
    "for_loop": _d("Legacy Functional For Loop", "Legacy Structures", ("array",), defaults={"max_iterations": 1000, "operation": "identity", "scale": 1.0}, input_types=(ARRAY,), output_types=(ARRAY,)),
    "while_loop": _d("Legacy Functional While Loop", "Legacy Structures", ("initial",), defaults={"max_iterations": 100, "condition": "less_than", "limit": 10.0, "step": 1.0}, input_types=(NUMERIC,), output_types=(NUMERIC,)),
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
    "analog_input": _d("Analog Input", "DAQ", defaults={"driver": "simulated", "channel": "AI0", "minimum": -10.0, "maximum": 10.0, "samples": 1, "rate": 1000.0, "timeout": 2.0}, output_types=(NUMERIC,)),
    "daq_finite_input": _d("Finite Analog Input", "DAQ", defaults={"driver": "nidaqmx", "channel": "Dev1/ai0", "minimum": -10.0, "maximum": 10.0, "samples": 100, "rate": 1000.0, "timeout": 2.0}, output_types=(ARRAY,)),
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
    "feedback": _d("Feedback Node", "Structures", ("value",), defaults={"initial": 0.0}),
    "visual_case": _d("Case Structure", "Structures", ("selector", "value"), defaults={"true_diagram": "", "false_diagram": ""}, input_types=(BOOLEAN, VARIANT)),
    "visual_for": _d("For Loop Structure", "Structures", ("array",), defaults={"body_diagram": "", "max_iterations": 1000}, output_types=(ARRAY,)),
    "structure_input": _d("Structure Input Tunnel", "Structure Internals", defaults={"name": "value"}),
    "iteration_terminal": _d("Iteration Terminal", "Structure Internals", output_types=(NUMERIC,)),
    "structure_output": _d("Structure Output Tunnel", "Structure Internals", ("value",)),
    "queue_create": _d("Create Queue", "Synchronization", defaults={"capacity": 100, "type_name": "variant"}),
    "queue_put": _d("Queue Put", "Synchronization", ("queue", "value"), defaults={"timeout": 1.0}),
    "queue_get": _d("Queue Get", "Synchronization", ("queue",), defaults={"timeout": 1.0}),
    "notifier_create": _d("Create Notifier", "Synchronization"),
    "notifier_set": _d("Set Notifier", "Synchronization", ("notifier", "value")),
    "notifier_wait": _d("Wait Notifier", "Synchronization", ("notifier", "generation"), ("value", "generation"), {"timeout": 1.0}),
    "event_create": _d("Create Named Event", "Synchronization", defaults={"name": "event"}),
    "event_fire": _d("Fire Event", "Synchronization", ("event", "value")),
    "event_wait": _d("Wait Event", "Synchronization", ("event", "generation"), ("value", "generation"), {"timeout": 1.0}),
    "channel_create": _d("Create Message Channel", "Synchronization", defaults={"capacity": 100, "type_name": "variant"}),
    "channel_send": _d("Channel Send", "Synchronization", ("channel", "value"), defaults={"timeout": 1.0}),
    "channel_receive": _d("Channel Receive", "Synchronization", ("channel",), defaults={"timeout": 1.0}),
    "resource_close": _d("Close Resource", "Synchronization", ("resource",), outputs=()),
    "bytes_constant": _d("Bytes", "Constants", defaults={"hex": ""}),
    "tcp_connect": _d("TCP Connect", "Network", defaults={"host": "127.0.0.1", "port": 502, "timeout": 2.0}),
    "tcp_read": _d("TCP Read", "Network", ("connection",), defaults={"size": 1024, "timeout": 2.0, "mode": "up_to", "delimiter_hex": "0a"}),
    "tcp_write": _d("TCP Write", "Network", ("connection", "data"), defaults={"timeout": 2.0}, output_types=(NUMERIC,)),
    "udp_open": _d("UDP Open", "Network", defaults={"host": "127.0.0.1", "port": 0, "timeout": 2.0}),
    "udp_send": _d("UDP Send To", "Network", ("endpoint", "data"), defaults={"host": "127.0.0.1", "port": 9999, "timeout": 2.0}, output_types=(NUMERIC,)),
    "udp_receive": _d("UDP Receive From", "Network", ("endpoint",), ("data", "host", "port"), {"max_bytes": 65535, "timeout": 2.0}),
    "modbus_connect": _d("Modbus TCP Connect", "Network", defaults={"host": "127.0.0.1", "port": 502, "unit_id": 1, "timeout": 2.0}),
    "modbus_read_holding": _d("Modbus Read Holding Registers (FC03)", "Network", ("client",), defaults={"address": 0, "quantity": 1, "timeout": 2.0}, output_types=(ARRAY,)),
    "modbus_write_register": _d("Modbus Write Single Register (FC06)", "Network", ("client", "value"), defaults={"address": 0, "timeout": 2.0}, output_types=(NUMERIC,)),
    "modbus_read_coils": _d("Modbus Read Coils (FC01)", "Network", ("client",), defaults={"address": 0, "quantity": 1, "timeout": 2.0}, output_types=(ARRAY,)),
    "modbus_read_discrete": _d("Modbus Read Discrete Inputs (FC02)", "Network", ("client",), defaults={"address": 0, "quantity": 1, "timeout": 2.0}, output_types=(ARRAY,)),
    "modbus_read_input": _d("Modbus Read Input Registers (FC04)", "Network", ("client",), defaults={"address": 0, "quantity": 1, "timeout": 2.0}, output_types=(ARRAY,)),
    "modbus_write_coil": _d("Modbus Write Single Coil (FC05)", "Network", ("client", "value"), defaults={"address": 0, "timeout": 2.0}, input_types=(VARIANT, BOOLEAN), output_types=(BOOLEAN,)),
    "modbus_write_coils": _d("Modbus Write Multiple Coils (FC15)", "Network", ("client", "values"), defaults={"address": 0, "timeout": 2.0}, input_types=(VARIANT, ARRAY), output_types=(NUMERIC,)),
    "modbus_write_registers": _d("Modbus Write Multiple Registers (FC16)", "Network", ("client", "values"), defaults={"address": 0, "timeout": 2.0}, input_types=(VARIANT, ARRAY), output_types=(NUMERIC,)),
    "serial_open": _d("Serial Open (pyserial required)", "Optional Adapters", defaults={"port": "COM1", "baudrate": 9600, "timeout": 1.0}),
    "serial_read": _d("Serial Read", "Optional Adapters", ("connection",), defaults={"size": 1024, "mode": "bytes", "encoding": "utf-8"}),
    "serial_write": _d("Serial Write", "Optional Adapters", ("connection", "data"), defaults={"mode": "bytes", "encoding": "utf-8"}, output_types=(NUMERIC,)),
    "serial_close": _d("Serial Close", "Optional Adapters", ("connection",), outputs=()),
    "visa_open": _d("VISA Open", "Instrumentation/VISA", defaults={"resource": "TCPIP0::127.0.0.1::INSTR", "timeout": 2.0, "max_bytes": 1048576}),
    "visa_write": _d("VISA Write", "Instrumentation/VISA", ("instrument", "text"), input_types=(VARIANT, STRING), output_types=(NUMERIC,)),
    "visa_query": _d("VISA Query", "Instrumentation/VISA", ("instrument", "text"), input_types=(VARIANT, STRING), output_types=(STRING,)),
    "visa_read_raw": _d("VISA Read Raw", "Instrumentation/VISA", ("instrument",)),
    "visa_write_raw": _d("VISA Write Raw", "Instrumentation/VISA", ("instrument", "data"), output_types=(NUMERIC,)),
    "visa_close": _d("VISA Close", "Instrumentation/VISA", ("instrument",), outputs=()),
    "opcua_connect": _d("OPC UA Connect", "Instrumentation/OPC UA", defaults={"endpoint": "opc.tcp://127.0.0.1:4840", "timeout": 2.0, "security_note": "Configure certificates/security policy in deployment"}),
    "opcua_read": _d("OPC UA Read Value", "Instrumentation/OPC UA", ("connection",), defaults={"node_id": "ns=2;s=Value"}),
    "opcua_write": _d("OPC UA Write Value", "Instrumentation/OPC UA", ("connection", "value"), outputs=(), defaults={"node_id": "ns=2;s=Value"}),
    "opcua_disconnect": _d("OPC UA Disconnect", "Instrumentation/OPC UA", ("connection",), outputs=()),
    "image_read": _d("Read Image", "Vision", defaults={"path": "input.png"}, output_types=(IMAGE,)),
    "camera_capture": _d("Capture Camera Frame", "Vision", defaults={"camera_index": 0}, output_types=(IMAGE,)),
    "image_grayscale": _d("Grayscale", "Vision", ("image",), input_types=(IMAGE,), output_types=(IMAGE,)),
    "image_blur": _d("Gaussian Blur", "Vision", ("image",), defaults={"kernel": 5}, input_types=(IMAGE,), output_types=(IMAGE,)),
    "image_threshold": _d("Threshold", "Vision", ("image",), defaults={"threshold": 127.0, "maximum": 255.0}, input_types=(IMAGE,), output_types=(IMAGE,)),
    "image_canny": _d("Canny", "Vision", ("image",), defaults={"low": 50.0, "high": 150.0}, input_types=(IMAGE,), output_types=(IMAGE,)),
    "image_resize": _d("Resize Image", "Vision", ("image",), defaults={"width": 640, "height": 480}, input_types=(IMAGE,), output_types=(IMAGE,)),
    "template_match": _d("Template Match", "Vision", ("image", "template"), input_types=(IMAGE, IMAGE), output_types=(CLUSTER,)),
    "image_save": _d("Save Image", "Vision", ("image",), ("error",), {"path": "output.png"}, input_types=(IMAGE,), output_types=(ERROR,)),
    "image_display": _d("Image Indicator", "Outputs", ("image",), (), {"display_type": "image"}, "indicator", input_types=(IMAGE,)),
    "report_generate": _d("Generate Report", "Reports", ("data",), ("path", "error"), {"path": "report.html", "format": "html", "title": "PyLabView Report"}, output_types=(STRING, ERROR)),
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
    subdiagrams: dict[str, Graph] = field(default_factory=dict)

    @classmethod
    def create(cls, name: str) -> "VirtualInstrument":
        return cls(uuid.uuid4().hex[:10], name, Graph(name))


class Project:
    def __init__(self, name: str = "Untitled Project") -> None:
        self.name = name
        vi = VirtualInstrument.create("Main VI")
        self.vis: dict[str, VirtualInstrument] = {vi.id: vi}
        self.main_vi = vi.id
        self.extensions: dict[str, Any] = {}
        self.migration_report: list[str] = []
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
        if any(n.type == "subvi" and n.properties.get("vi_id") == vi_id
               for vi in self.vis.values() for graph in _vi_graphs(vi) for n in graph.nodes.values()):
            raise ValueError("VI is referenced by a SubVI node")
        del self.vis[vi_id]

    def set_main(self, vi_id: str) -> None:
        if vi_id not in self.vis:
            raise ValueError("unknown VI")
        self.main_vi = vi_id

    def to_dict(self) -> dict[str, Any]:
        return {"format": "pylabview-project", "version": 3, "name": self.name, "main_vi": self.main_vi,
                "vis": [{"id": vi.id, "name": vi.name, "graph": vi.graph.graph_dict(),
                          "connector_pane": {"inputs": [asdict(t) for t in vi.connector_inputs], "outputs": [asdict(t) for t in vi.connector_outputs]},
                          "front_panel": copy.deepcopy(_normalized_panel(vi.front_panel, vi.graph)),
                          "subdiagrams": {diagram_id: graph.graph_dict() for diagram_id, graph in vi.subdiagrams.items()}}
                         for vi in self.vis.values()], "extensions": copy.deepcopy(self.extensions)}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Project":
        try:
            if not isinstance(data, dict):
                raise ValueError("project must be an object")
            version = data.get("version")
            required = {"format", "version", "name", "main_vi", "vis"} | ({"extensions"} if version == 3 else set())
            if set(data) != required:
                raise ValueError(f"invalid project v{version} schema")
            if data["format"] != "pylabview-project" or type(version) is not int or version not in (2, 3):
                raise ValueError("unsupported project format version")
            if (not isinstance(data["name"], str) or not isinstance(data["main_vi"], str) or not data["main_vi"]
                    or not isinstance(data["vis"], list) or not data["vis"]):
                raise ValueError("invalid project fields")
            project = cls.__new__(cls)
            project.name, project.main_vi, project.vis = data["name"], data["main_vi"], {}
            project.extensions = copy.deepcopy(data.get("extensions", {}))
            project.migration_report = []
            if not isinstance(project.extensions, dict):
                raise ValueError("project extensions must be an object")
            vi_names: set[str] = set()
            terminal_fields = {"name", "node_id", "port", "data_type"}
            for item in data["vis"]:
                vi_fields = {"id", "name", "graph", "connector_pane", "front_panel"} | ({"subdiagrams"} if version == 3 else set())
                if not isinstance(item, dict) or set(item) != vi_fields:
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
                subdiagrams: dict[str, Graph] = {}
                raw_subdiagrams = item.get("subdiagrams", {})
                if not isinstance(raw_subdiagrams, dict) or any(not isinstance(key, str) or not key for key in raw_subdiagrams):
                    raise ValueError("invalid subdiagram schema")
                for diagram_id, diagram_data in raw_subdiagrams.items():
                    subdiagrams[diagram_id] = Graph.from_dict(diagram_data)
                panel = _validate_panel(item["front_panel"], graph) if version == 3 else _normalized_panel(item["front_panel"], graph)
                project.vis[item["id"]] = VirtualInstrument(
                    item["id"], item["name"], graph, terminals[0], terminals[1], panel, subdiagrams
                )
            if project.main_vi not in project.vis:
                raise ValueError("main_vi references a missing VI")
            project._bind_graphs()
            for vi in project.vis.values():
                for graph in _vi_graphs(vi):
                    wires, graph.wires = graph.wires, []
                    for wire in wires:
                        graph.connect(wire.source_node, wire.source_port, wire.target_node, wire.target_port)
            project.validate_structures()
            project.validate_connectors()
            if version == 2:
                project.migration_report = ["Migrated project v2 to v3", "Generated free-layout Front Panel bounds"]
            return project
        except ValueError:
            raise
        except (AttributeError, KeyError, StopIteration, TypeError) as exc:
            raise ValueError("invalid project schema") from exc

    @classmethod
    def migrate_v1(cls, data: dict[str, Any]) -> "Project":
        graph = Graph.from_dict(data)
        project = cls(str(data.get("name", "Migrated Project")))
        vi = project.main
        vi.name, vi.graph = graph.name, graph
        project._bind_graphs()
        project.migration_report = ["Migrated legacy graph v1 to project v3", "Generated free-layout Front Panel bounds"]
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

    def validate_structures(self) -> None:
        for vi in self.vis.values():
            dependencies: dict[str, set[str]] = {diagram_id: set() for diagram_id in vi.subdiagrams}
            for graph in _vi_graphs(vi):
                for node in graph.nodes.values():
                    keys = (("true_diagram", "false_diagram") if node.type == "visual_case" else
                            ("body_diagram",) if node.type == "visual_for" else ())
                    for key in keys:
                        diagram_id = node.properties.get(key)
                        if not isinstance(diagram_id, str) or not diagram_id or diagram_id not in vi.subdiagrams:
                            raise ValueError(f"{node.label}: invalid structure subdiagram reference '{key}'")
                        for owner_id, owner_graph in vi.subdiagrams.items():
                            if graph is owner_graph:
                                dependencies[owner_id].add(diagram_id)
                                break
            visiting: set[str] = set()
            visited: set[str] = set()

            def visit(diagram_id: str) -> None:
                if diagram_id in visiting:
                    raise ValueError("recursive visual structure subdiagram")
                if diagram_id in visited:
                    return
                visiting.add(diagram_id)
                for child_id in dependencies[diagram_id]:
                    visit(child_id)
                visiting.remove(diagram_id)
                visited.add(diagram_id)

            for diagram_id in dependencies:
                visit(diagram_id)

    def _bind_graphs(self) -> None:
        for vi in self.vis.values():
            vi.graph.project = self
            for graph in vi.subdiagrams.values():
                graph.project = self


def _normalized_panel(panel: dict[str, Any], graph: Graph) -> dict[str, Any]:
    if isinstance(panel, dict) and set(panel) == {"title", "canvas", "items", "extensions"}:
        normalized = copy.deepcopy(panel)
        normalized["items"] = [item for item in normalized["items"] if item.get("terminal_node_id") in graph.nodes]
        existing = {item["terminal_node_id"] for item in normalized["items"]}
        candidates = [node for node in graph.nodes.values()
                      if node.id not in existing and node.type in {"numeric_constant", "string_constant", "boolean_constant",
                                                                    "array_constant", "display", "chart", "image_display"}]
        for node in candidates:
            index = len(normalized["items"]); column, row = index % 3, index // 3
            kind = {"numeric_constant": "numeric_control", "string_constant": "string_control",
                    "boolean_constant": "boolean_control", "array_constant": "array_control",
                    "display": "indicator", "chart": "chart", "image_display": "image_indicator"}[node.type]
            normalized["items"].append({"id": f"panel-{node.id}", "kind": kind, "terminal_node_id": node.id,
                                        "bounds": {"x": 24 + column * 240, "y": 24 + row * 150, "width": 210, "height": 120},
                                        "z_index": index, "properties": {"label": node.label}, "extensions": {}})
        return _validate_panel(normalized, graph)
    title = str(panel.get("title", "")) if isinstance(panel, dict) else ""
    items: list[dict[str, Any]] = []
    index = 0
    kind_map = {
        "numeric_constant": "numeric_control", "string_constant": "string_control",
        "boolean_constant": "boolean_control", "array_constant": "array_control",
        "display": "indicator", "chart": "chart", "image_display": "image_indicator",
    }
    for node in graph.nodes.values():
        if node.type not in kind_map:
            continue
        column, row = index % 3, index // 3
        items.append({
            "id": f"panel-{node.id}", "kind": kind_map[node.type], "terminal_node_id": node.id,
            "bounds": {"x": 24 + column * 240, "y": 24 + row * 150, "width": 210, "height": 120},
            "z_index": index, "properties": {"label": node.label}, "extensions": {},
        })
        index += 1
    return {"title": title, "canvas": {"width": 960, "height": 640, "background": "#e8e8e8"},
            "items": items, "extensions": {}}


def _validate_panel(panel: Any, graph: Graph) -> dict[str, Any]:
    if not isinstance(panel, dict) or set(panel) != {"title", "canvas", "items", "extensions"}:
        raise ValueError("invalid Front Panel schema")
    canvas = panel["canvas"]
    if (not isinstance(panel["title"], str) or not isinstance(canvas, dict)
            or set(canvas) != {"width", "height", "background"}
            or any(isinstance(canvas[key], bool) or not isinstance(canvas[key], (int, float))
                   or not math.isfinite(canvas[key]) or canvas[key] <= 0
                   for key in ("width", "height"))
            or not isinstance(canvas["background"], str)
            or not isinstance(panel["items"], list) or not isinstance(panel["extensions"], dict)):
        raise ValueError("invalid Front Panel fields")
    seen: set[str] = set()
    bound_terminals: set[str] = set()
    expected_kinds = {
        "numeric_constant": "numeric_control", "string_constant": "string_control",
        "boolean_constant": "boolean_control", "array_constant": "array_control",
        "display": "indicator", "chart": "chart", "image_display": "image_indicator",
    }
    for item in panel["items"]:
        fields = {"id", "kind", "terminal_node_id", "bounds", "z_index", "properties", "extensions"}
        if (not isinstance(item, dict) or set(item) != fields or not isinstance(item["id"], str)
                or not item["id"] or item["id"] in seen or not isinstance(item["kind"], str)
                or item["terminal_node_id"] not in graph.nodes
                or item["terminal_node_id"] in bound_terminals
                or isinstance(item["z_index"], bool) or not isinstance(item["z_index"], int)
                or not isinstance(item["properties"], dict) or not isinstance(item["extensions"], dict)):
            raise ValueError("invalid Front Panel item")
        node = graph.nodes[item["terminal_node_id"]]
        if expected_kinds.get(node.type) != item["kind"]:
            raise ValueError("Front Panel item kind does not match its terminal")
        seen.add(item["id"])
        bound_terminals.add(item["terminal_node_id"])
        bounds = item["bounds"]
        if not isinstance(bounds, dict) or set(bounds) != {"x", "y", "width", "height"}:
            raise ValueError("invalid Front Panel item bounds")
        if any(isinstance(bounds[key], bool) or not isinstance(bounds[key], (int, float)) or not math.isfinite(bounds[key])
               for key in bounds):
            raise ValueError("invalid Front Panel item bounds")
        if bounds["width"] < 40 or bounds["height"] < 30:
            raise ValueError("Front Panel item is too small")
    return copy.deepcopy(panel)


def _vi_graphs(vi: VirtualInstrument) -> tuple[Graph, ...]:
    return (vi.graph, *vi.subdiagrams.values())


def clone_structure_properties(project: Project, vi_id: str, node_type: str,
                               properties: dict[str, Any]) -> dict[str, Any]:
    vi = project.vis[vi_id]
    cloned_ids: dict[str, str] = {}

    def clone_diagram(diagram_id: str) -> str:
        if diagram_id in cloned_ids:
            return cloned_ids[diagram_id]
        source = vi.subdiagrams.get(diagram_id)
        if source is None:
            raise ValueError(f"structure subdiagram does not exist: {diagram_id}")
        new_id = f"{diagram_id}-copy-{uuid.uuid4().hex[:8]}"
        cloned_ids[diagram_id] = new_id
        graph = Graph.from_dict(copy.deepcopy(source.graph_dict()))
        id_map = {old_id: uuid.uuid4().hex[:10] for old_id in graph.nodes}
        for old_id, child in list(graph.nodes.items()):
            child.id = id_map[old_id]
        graph.nodes = {child.id: child for child in graph.nodes.values()}
        for wire in graph.wires:
            wire.source_node = id_map[wire.source_node]
            wire.target_node = id_map[wire.target_node]
        graph.project = project
        vi.subdiagrams[new_id] = graph
        for child in graph.nodes.values():
            if child.type in ("visual_case", "visual_for"):
                child.properties = clone_properties(child.type, child.properties)
        return new_id

    def clone_properties(kind: str, raw: dict[str, Any]) -> dict[str, Any]:
        result = copy.deepcopy(raw)
        keys = ("true_diagram", "false_diagram") if kind == "visual_case" else ("body_diagram",)
        for key in keys:
            result[key] = clone_diagram(str(raw.get(key, "")))
        return result

    return clone_properties(node_type, properties)


def delete_owned_structure_diagrams(project: Project, vi_id: str, node: Node) -> None:
    if node.type not in ("visual_case", "visual_for"):
        return
    vi = project.vis[vi_id]
    keys = ("true_diagram", "false_diagram") if node.type == "visual_case" else ("body_diagram",)

    def referenced(diagram_id: str, ignored: Node | None = None) -> bool:
        for graph in _vi_graphs(vi):
            for candidate in graph.nodes.values():
                if candidate is ignored:
                    continue
                candidate_keys = (("true_diagram", "false_diagram") if candidate.type == "visual_case" else
                                  ("body_diagram",) if candidate.type == "visual_for" else ())
                if any(candidate.properties.get(key) == diagram_id for key in candidate_keys):
                    return True
        return False

    def remove_owned(diagram_id: str, ignored: Node | None = None) -> None:
        if referenced(diagram_id, ignored):
            return
        graph = vi.subdiagrams.pop(diagram_id, None)
        if graph is None:
            return
        for child in graph.nodes.values():
            child_keys = (("true_diagram", "false_diagram") if child.type == "visual_case" else
                          ("body_diagram",) if child.type == "visual_for" else ())
            for key in child_keys:
                remove_owned(str(child.properties.get(key, "")))

    for key in keys:
        remove_owned(str(node.properties.get(key, "")), node)


def update_chart_history(history: list[float], value: Any, limit: int) -> list[float]:
    limit = max(2, limit)
    samples = value.y if hasattr(value, "y") else value if isinstance(value, (list, tuple)) else [value]
    try:
        updated = [*history, *(float(sample) for sample in samples)]
    except (TypeError, ValueError):
        return list(history)
    return updated[-limit:]


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
