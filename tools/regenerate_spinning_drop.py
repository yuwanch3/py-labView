"""One-shot generator: adds spinning_drop_sequencer to examples/spinning_drop_ift.json.

Deliberately does NOT hand-edit JSON text. It loads the known-good project
(commit aee3c7a state) with json.load, appends nodes/wires/panel items as
plain Python dicts/lists, and serializes with json.dump so syntax validity
is guaranteed by construction.

Output goes to a temporary file; caller must validate it (json round-trip,
load_project, DataflowRuntime.validate, injected-backend run) before
overwriting the original.
"""
from __future__ import annotations

import json
from pathlib import Path

SRC = Path("examples/spinning_drop_ift.json")
DST = Path("examples/spinning_drop_ift_new.json")

data = json.loads(SRC.read_text(encoding="utf-8"))
graph = data["vis"][0]["graph"]
nodes: list[dict] = graph["nodes"]
wires: list[dict] = graph["wires"]
panel_items: list[dict] = data["vis"][0]["front_panel"]["items"]

# --- sanity: refuse to run against an already-mutated file -----------------
existing_ids = {node["id"] for node in nodes}
for required in ("motor", "arduino", "ift", "oil_edge", "drop_mm",
                 "density_delta", "table_display"):
    if required not in existing_ids:
        raise SystemExit(f"source file missing expected node: {required}")
for fresh in ("sequencer", "cam_err", "pwm_fb", "state_display", "count_display"):
    if fresh in existing_ids:
        raise SystemExit(f"source file already contains '{fresh}'; revert it first")

# --- 1. drop the manual pwm_select feed; sequencer drives PWM now ----------
before = len(wires)
wires[:] = [w for w in wires
            if not (w["source_node"] == "pwm_select" and w["target_node"] == "arduino")]
if len(wires) != before - 1:
    raise SystemExit("expected exactly one pwm_select->arduino wire")

# --- 2. new nodes -----------------------------------------------------------
nodes.extend([
    {"id": "cam_err", "type": "error_constant", "x": 220, "y": 900,
     "label": "Camera Error Status",
     "properties": {"status": False, "code": 0, "source": ""}},
    {"id": "sequencer", "type": "spinning_drop_sequencer", "x": 430, "y": 900,
     "label": "Spinning Drop Sequencer",
     "properties": {"rpm_list": [1000, 2000, 3000, 4000, 5000, 6000],
                    "stage_duration": 180.0}},
    {"id": "pwm_fb", "type": "feedback", "x": 530, "y": 160,
     "label": "PWM Feedback (1 pass delay)",
     "properties": {"initial": 0.0}},
    {"id": "state_display", "type": "display", "x": 1700, "y": 20,
     "label": "Sequencer State",
     "properties": {"display_type": "auto", "style": "default"}},
    {"id": "count_display", "type": "display", "x": 1700, "y": 100,
     "label": "Stage Countdown (s)",
     "properties": {"display_type": "numeric", "style": "default"}},
])

# --- 3. new wires ------------------------------------------------------------
def wire(src: str, sp: str, dst: str, dp: str, dtype: str) -> dict:
    return {"source_node": src, "source_port": sp,
            "target_node": dst, "target_port": dp, "data_type": dtype}

wires.extend([
    # sequencer inputs: start command + live measurement sampling
    wire("motor", "out", "sequencer", "start", "boolean"),
    wire("arduino", "rpm", "sequencer", "rpm_measured", "numeric"),
    wire("arduino", "sensor_status", "sequencer", "sensor_status", "string"),
    wire("arduino", "error", "sequencer", "motor_error", "error"),
    wire("cam_err", "error", "sequencer", "capture_error", "error"),
    wire("ift", "ift_mN_m", "sequencer", "ift_mN_m", "numeric"),
    wire("oil_edge", "diameter_px", "sequencer", "diameter_px", "numeric"),
    wire("drop_mm", "diameter_mm", "sequencer", "diameter_mm", "numeric"),
    wire("density_delta", "delta_rho", "sequencer", "delta_rho", "numeric"),
    wire("ift", "omega_squared", "sequencer", "omega_squared", "numeric"),
    wire("ift", "radius_cubed", "sequencer", "radius_cubed", "numeric"),
    wire("ift", "ift_N_m", "sequencer", "ift_N_m", "numeric"),
    # closed PWM loop through a 1-pass feedback node (breaks the dataflow cycle)
    wire("sequencer", "target_pwm", "pwm_fb", "value", "numeric"),
    wire("pwm_fb", "out", "arduino", "pwm", "variant"),
    # operator-facing state indicators + canonical 6-row table
    wire("sequencer", "state", "state_display", "value", "string"),
    wire("sequencer", "countdown", "count_display", "value", "numeric"),
    wire("sequencer", "table_data", "table_display", "value", "array"),
])

# --- 4. front panel items for the new indicators -----------------------------
panel_items.extend([
    {"id": "fp-seq-state", "kind": "indicator", "terminal_node_id": "state_display",
     "bounds": {"x": 1410, "y": 220, "width": 170, "height": 65}, "z_index": 33,
     "properties": {"label": "Sequencer State"}, "extensions": {}},
    {"id": "fp-seq-count", "kind": "indicator", "terminal_node_id": "count_display",
     "bounds": {"x": 1410, "y": 300, "width": 170, "height": 65}, "z_index": 34,
     "properties": {"label": "Stage Countdown (s)"}, "extensions": {}},
])

# --- 5. honest provenance note ------------------------------------------------
data["vis"][0]["front_panel"]["extensions"]["sequencer_status"] = (
    "6-stage RPM sequence implemented; automated fast-forwarded timer tests only, "
    "physical 18-minute cycle validation not performed")

DST.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print(f"wrote {DST}: {len(nodes)} nodes, {len(wires)} wires, {len(panel_items)} panel items")
