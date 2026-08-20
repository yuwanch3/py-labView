"""Restricted combinational graph to synthesizable Verilog exporter."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from shutil import which
from subprocess import run
from tempfile import TemporaryDirectory
from typing import Any
import re

from .model import Graph
from .typesystem import BOOLEAN


SUPPORTED = {"numeric_constant", "boolean_constant", "structure_input", "add", "subtract", "multiply",
             "compare", "boolean_and", "boolean_or", "boolean_not", "select", "structure_output", "display"}

VERILOG_KEYWORDS = {
    "always", "and", "assign", "begin", "case", "else", "end", "endcase", "endmodule", "function",
    "if", "inout", "input", "integer", "module", "not", "or", "output", "parameter", "reg", "wire",
}


class HdlExportError(ValueError): pass


def _identifier(value: str, prefix: str) -> str:
    result = re.sub(r"[^A-Za-z0-9_]", "_", value)
    if not result: result = "unnamed"
    result = f"{prefix}_{result}"
    if result.lower() in VERILOG_KEYWORDS: result = f"{prefix}_{result}"
    return result


def _unique(value: str, used: set[str]) -> str:
    candidate, index = value, 2
    while candidate in used:
        candidate = f"{value}_{index}"; index += 1
    used.add(candidate)
    return candidate


def export_verilog(graph: Graph, module_name: str = "pylabview_graph") -> str:
    unsupported = sorted({node.type for node in graph.nodes.values()} - SUPPORTED)
    if unsupported: raise HdlExportError("unsupported HDL node(s): " + ", ".join(unsupported))
    order = _order(graph); signals: dict[tuple[str, str], str] = {}; inputs: list[tuple[str, bool]] = []; outputs: list[tuple[str, str, bool]] = []; lines: list[str] = []
    used_ports: set[str] = set(); signal_index = 0
    for node_id in order:
        node = graph.nodes[node_id]; incoming = graph.incoming(node_id); signal = f"w_{signal_index}"; signal_index += 1
        if node.type == "structure_input":
            name = _unique(_identifier(str(node.properties.get("name", node.label)), "p_in"), used_ports)
            boolean = bool(node.properties.get("data_type") == BOOLEAN)
            inputs.append((name, boolean)); signals[(node_id, "out")] = name; continue
        if node.type in ("structure_output", "display"):
            if "value" not in incoming: raise HdlExportError(f"{node.label}: output is not wired")
            source = incoming["value"]; source_signal = signals.get((source.source_node, source.source_port))
            if not source_signal: raise HdlExportError(f"{node.label}: unresolved output")
            name = _unique(_identifier(node.label, "p_out"), used_ports)
            outputs.append((name, source_signal, graph.port_type(graph.nodes[source.source_node], "out", source.source_port) == BOOLEAN)); continue
        if node.type == "numeric_constant":
            value = node.properties.get("value", 0)
            if isinstance(value, bool) or not isinstance(value, int) or not -(2 ** 31) <= value < 2 ** 31:
                raise HdlExportError("HDL numeric constants must be signed 32-bit integers")
            expression = str(value)
        elif node.type == "boolean_constant":
            value = node.properties.get("value")
            if not isinstance(value, bool): raise HdlExportError("HDL boolean constant is invalid")
            expression = "1'b1" if value else "1'b0"
        else:
            required = graph.ports(node, "in")
            if any(port not in incoming for port in required): raise HdlExportError(f"{node.label}: missing HDL input")
            args = [signals.get((incoming[port].source_node, incoming[port].source_port)) for port in required]
            if any(arg is None for arg in args): raise HdlExportError(f"{node.label}: unresolved HDL input")
            if node.type == "boolean_not": expression = f"~{args[0]}"
            elif node.type == "select": expression = f"{args[0]} ? {args[1]} : {args[2]}"
            else:
                operator = {"add": "+", "subtract": "-", "multiply": "*", "boolean_and": "&", "boolean_or": "|"}.get(node.type)
                if node.type == "compare":
                    operator = str(node.properties.get("operator", ">"))
                    if operator not in (">", "<", "==", ">=", "<=", "!="): raise HdlExportError("unsupported HDL comparison")
                expression = f"{args[0]} {operator} {args[1]}"
        boolean = graph.port_type(node, "out", "out") == BOOLEAN
        lines.append(f"  wire{' ' if boolean else ' signed [31:0] '}{signal};")
        lines.append(f"  assign {signal} = {expression};")
        signals[(node_id, "out")] = signal
    if not outputs: raise HdlExportError("graph has no structure_output/display")
    port_names = [name for name, _ in inputs] + [name for name, _, _ in outputs]
    declarations = [f"  input {'wire' if boolean else 'wire signed [31:0]'} {name};" for name, boolean in inputs]
    declarations += [f"  output {'wire' if boolean else 'wire signed [31:0]'} {name};" for name, _, boolean in outputs]
    assignments = [f"  assign {name} = {source};" for name, source, _ in outputs]
    return "\n".join([f"module {_identifier(module_name, 'm')}({', '.join(port_names)});", *declarations, *lines, *assignments, "endmodule", ""])


def _order(graph: Graph) -> list[str]:
    indegree = {node_id: 0 for node_id in graph.nodes}; following = {node_id: [] for node_id in graph.nodes}
    for wire in graph.wires: indegree[wire.target_node] += 1; following[wire.source_node].append(wire.target_node)
    ready = [node_id for node_id, degree in indegree.items() if degree == 0]; result: list[str] = []
    while ready:
        node_id = ready.pop(0); result.append(node_id)
        for target in following[node_id]:
            indegree[target] -= 1
            if indegree[target] == 0: ready.append(target)
    if len(result) != len(graph.nodes): raise HdlExportError("HDL graph must be combinational and acyclic")
    return result


@dataclass(frozen=True)
class ToolResult:
    available: bool
    succeeded: bool
    output: str


def yosys_syntax_check(verilog: str, timeout: float = 10, executable: str | None = None) -> ToolResult:
    executable = executable or which("yosys")
    if not executable: return ToolResult(False, False, "yosys command not found")
    if timeout <= 0 or timeout > 60: raise ValueError("Yosys timeout must be between 0 and 60 seconds")
    with TemporaryDirectory(prefix="pylabview-yosys-") as directory:
        source = Path(directory) / "graph.v"; source.write_text(verilog, encoding="ascii")
        completed = run([executable, "-q", "-p", f"read_verilog {source}"], capture_output=True, text=True, timeout=timeout, check=False)
        output = (completed.stdout + completed.stderr)[-16_384:]
        return ToolResult(True, completed.returncode == 0, output)
