"""One-shot generator v3: separate captures for Picture Oil and Picture
Comparison in examples/spinning_drop_ift.json.

Root cause of the identical images: oil_camera and wire_camera both read from
the same constants (wifi / oil_source / oil_mode) and both grabbed a frame in
the same runtime tick with no per-node state, so the comparison picture was a
silent same-instant re-grab of the oil picture.

Fix (architecture trigger separation): give camera_capture_dual_mode a
capture_trigger gate plus a held frame per node. The oil node stays live
(bound to a True constant); the wire node is bound to an operator button and
only captures when pressed, holding the last reference frame otherwise.

This never hand-edits JSON text: json.load -> dict/list manipulation ->
json.dump. Writes to examples/spinning_drop_ift_new.json; the caller must
validate (round-trip, load_project+validate, injected-backend run) before
overwriting examples/spinning_drop_ift.json.
"""
from __future__ import annotations

import json
from pathlib import Path

SRC = Path("examples/spinning_drop_ift.json")
DST = Path("examples/spinning_drop_ift_new.json")

data = json.loads(SRC.read_text(encoding="utf-8"))
vi = data["vis"][0]
graph = vi["graph"]
nodes: list[dict] = graph["nodes"]
panel_items: list[dict] = vi["front_panel"]["items"]
ids = {node["id"] for node in nodes}

for required in ("oil_camera", "wire_camera"):
    if required not in ids:
        raise SystemExit(f"source file missing expected node: {required}")

def const(node_id: str, label: str, value: bool, x: float, y: float) -> dict:
    return {"id": node_id, "type": "boolean_constant", "x": x, "y": y,
            "label": label, "properties": {"value": value, "display_type": "boolean"}}

nodes.append(const("capture_oil", "Capture Oil (live)", True, 1200, 420))
nodes.append(const("capture_wire", "Capture Reference", False, 1200, 500))

def wire(src: str, sp: str, dst: str, dp: str, dtype: str) -> dict:
    return {"source_node": src, "source_port": sp,
            "target_node": dst, "target_port": dp, "data_type": dtype}

existing = {(w["source_node"], w["source_port"], w["target_node"], w["target_port"])
            for w in graph["wires"]}

def add_wire(w: dict) -> None:
    key = (w["source_node"], w["source_port"], w["target_node"], w["target_port"])
    if key not in existing:
        graph["wires"].append(w)
        existing.add(key)

add_wire(wire("capture_oil", "out", "oil_camera", "capture_trigger", "boolean"))
add_wire(wire("capture_wire", "out", "wire_camera", "capture_trigger", "boolean"))

panel_items.append({
    "id": "fp-wire-capture", "kind": "boolean_control", "terminal_node_id": "capture_wire",
    "bounds": {"x": 470, "y": 560, "width": 230, "height": 70}, "z_index": 22,
    "properties": {"label": "Capture Reference", "display_type": "push_button"},
    "extensions": {"role": "staged wire-comparison capture trigger"},
})

# structural sanity before serialization
ids = [node["id"] for node in nodes]
if len(ids) != len(set(ids)):
    raise SystemExit("duplicate node ids after mutation")
id_set = set(ids)
for item in graph["wires"]:
    if item["source_node"] not in id_set or item["target_node"] not in id_set:
        raise SystemExit(f"wire references missing node: {item}")
for item in panel_items:
    if item["terminal_node_id"] not in id_set:
        raise SystemExit(f"panel item references missing node: {item['terminal_node_id']}")
max_z = max(item["z_index"] for item in panel_items)
assert max_z == 22

DST.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print(f"wrote {DST}: {len(nodes)} nodes, {len(graph['wires'])} wires, {len(panel_items)} panel items")