"""One-shot generator v2: rewrites examples/spinning_drop_ift.json for the real
firmware protocol (ground truth: lab Arduino source found 2026-08-21).

Replaces the assumption-based design (SET_PWM request-response, PC-side
sequencer timer, sensor_status interlock) with the actual architecture:
the Arduino firmware runs the 6-stage RPM sequence itself and streams
telemetry; PyLabView Studio listens passively.

Like v1 this NEVER hand-edits JSON text: json.load -> dict/list manipulation
-> json.dump. Output goes to a temporary file; the caller must validate it
(round-trip, load_project, DataflowRuntime.validate, injected-backend run)
before overwriting the original.
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

# --- 1. drop every node based on the disproven assumptions ------------------
REMOVE = {
    # manual PWM machinery (PC never sends PWM values now)
    "pwm_zero", "pwm_start", "pwm_select",
    # assumed TIME(s) controls (real TIME(s) are telemetry indicators)
    "time_duration", "time_interval",
    # pycnometer chain: original VI takes delta density as a manual input
    "outer_empty", "outer_gross", "outer_volume",
    "drop_empty", "drop_gross", "drop_volume",
    "outer_density", "drop_density", "density_delta",
    # per-row logger replaced by the event-driven stage watcher
    "log_row",
    # density difference is a manual input now; its old indicator is gone
    "delta_display",
    # old request-response motor node
    "arduino",
    # v4.3.0 PC-side sequencer experiment (duplicated firmware logic)
    "sequencer", "cam_err", "pwm_fb", "state_display", "count_display",
}
before = {node["id"] for node in nodes}
missing = REMOVE - before
if missing:
    raise SystemExit(f"source file missing expected nodes: {sorted(missing)}")
nodes[:] = [node for node in nodes if node["id"] not in REMOVE]

# --- 2. new nodes ------------------------------------------------------------
def const(node_id: str, label: str, value, y: float, **extra) -> dict:
    props = {"value": value, "display_type": "numeric"}
    props.update(extra)
    return {"id": node_id, "type": "numeric_constant", "x": 20, "y": y,
            "label": label, "properties": props}

nodes.extend([
    {"id": "reader", "type": "arduino_telemetry_reader", "x": 430, "y": 80,
     "label": "Arduino Telemetry Reader",
     "properties": {"baudrate": 115200, "timeout": 0.2, "max_lines": 32,
                    "response_bytes": 4096}},
    {"id": "stall_guard", "type": "rpm_stall_watchdog", "x": 870, "y": 80,
     "label": "RPM Stall Watchdog (PC-side inference)",
     "properties": {"stall_seconds": 10.0}},
    {"id": "watcher", "type": "spinning_drop_stage_watcher", "x": 1270, "y": 80,
     "label": "Spinning Drop Stage Watcher", "properties": {}},
    const("cam_timeout", "Camera Timeout (s)", 1.0, 500),
    const("density_input", "Selisih Densitas (Kg/m3)", 0.0, 580,
          requires_manual_entry="operator enters the measured density difference"),
    {"id": "global_stop", "type": "boolean_constant", "x": 20, "y": 900,
     "label": "STOP", "properties": {"value": False, "display_type": "boolean"}},
    {"id": "time_display_1", "type": "display", "x": 1700, "y": 20,
     "label": "TIME(s)", "properties": {"display_type": "numeric", "style": "default"}},
    {"id": "time_display_2", "type": "display", "x": 1700, "y": 100,
     "label": "TIME(s)", "properties": {"display_type": "numeric", "style": "default"}},
])

# known wire diameter stays a block-diagram constant (not present on the
# original front panel screenshot); default matches a real 0.8 mm pin
for node in nodes:
    if node["id"] == "wire_known":
        node["properties"]["value"] = 0.8

# --- 3. rebuild every wire from scratch --------------------------------------
def wire(src: str, sp: str, dst: str, dp: str, dtype: str) -> dict:
    return {"source_node": src, "source_port": sp,
            "target_node": dst, "target_port": dp, "data_type": dtype}

wires: list[dict] = [
    # serial lifecycle: COM port + Motor radio drives START/STOP
    wire("com", "out", "reader", "port", "string"),
    wire("motor", "out", "reader", "run", "boolean"),
    wire("motor", "out", "watcher", "run", "boolean"),
    wire("motor", "out", "stall_guard", "run", "boolean"),

    # camera pipeline (unchanged roles)
    wire("oil_mode", "out", "oil_camera", "mode", "string"),
    wire("oil_source", "out", "oil_camera", "device_index", "numeric"),
    wire("wifi", "out", "oil_camera", "network_url", "string"),
    wire("cam_timeout", "out", "oil_camera", "timeout_seconds", "numeric"),
    wire("oil_mode", "out", "wire_camera", "mode", "string"),
    wire("oil_source", "out", "wire_camera", "device_index", "numeric"),
    wire("wifi", "out", "wire_camera", "network_url", "string"),
    wire("cam_timeout", "out", "wire_camera", "timeout_seconds", "numeric"),
    wire("oil_camera", "image", "oil_edge", "image", "image"),
    wire("oil_orientation", "out", "oil_edge", "scan_orientation", "string"),
    wire("wire_camera", "image", "wire_edge", "image", "image"),
    wire("wire_orientation", "out", "wire_edge", "scan_orientation", "string"),
    wire("wire_edge", "diameter_px", "wire_cal", "diameter_px", "numeric"),
    wire("wire_known", "out", "wire_cal", "known_wire_diameter_mm", "numeric"),
    wire("oil_edge", "diameter_px", "drop_mm", "diameter_px", "numeric"),
    wire("wire_cal", "scale_factor_mm_per_px", "drop_mm", "scale_factor_mm_per_px", "numeric"),

    # measurement math
    wire("reader", "rpm", "ift", "rpm", "numeric"),
    wire("drop_mm", "diameter_mm", "ift", "diameter_mm", "numeric"),
    wire("density_input", "out", "ift", "delta_rho", "numeric"),

    # stage watcher: purely event-driven from firmware signals
    wire("reader", "rpm", "watcher", "rpm", "numeric"),
    wire("reader", "pwm", "watcher", "pwm", "numeric"),
    wire("reader", "elapsed_time_s", "watcher", "elapsed_time_s", "numeric"),
    wire("reader", "current_target_rpm", "watcher", "current_target_rpm", "numeric"),
    wire("reader", "stage_changed", "watcher", "stage_changed", "boolean"),
    wire("reader", "autostop", "watcher", "autostop", "boolean"),
    wire("reader", "error", "watcher", "error", "error"),
    wire("stall_guard", "stalled", "watcher", "stalled", "boolean"),
    wire("oil_edge", "diameter_px", "watcher", "diameter_px", "numeric"),
    wire("drop_mm", "diameter_mm", "watcher", "diameter_mm", "numeric"),
    wire("density_input", "out", "watcher", "delta_rho", "numeric"),
    wire("ift", "omega_squared", "watcher", "omega_squared", "numeric"),
    wire("ift", "radius_cubed", "watcher", "radius_cubed", "numeric"),
    wire("ift", "ift_N_m", "watcher", "ift_N_m", "numeric"),
    wire("ift", "ift_mN_m", "watcher", "ift_mN_m", "numeric"),

    # watchdog senses the same telemetry
    wire("reader", "rpm", "stall_guard", "rpm", "numeric"),
    wire("reader", "current_target_rpm", "stall_guard", "current_target_rpm", "numeric"),

    # canonical 6-row table feeds both the panel and the CSV report
    wire("watcher", "table_data", "table_display", "value", "array"),
    wire("watcher", "table_data", "csv_report", "data", "array"),

    # indicators
    wire("reader", "rpm", "rpm_display", "value", "numeric"),
    wire("reader", "pwm", "pwm_display", "value", "numeric"),
    wire("reader", "elapsed_time_s", "time_display_1", "value", "numeric"),
    wire("reader", "elapsed_time_s", "time_display_2", "value", "numeric"),
    wire("oil_camera", "image", "oil_picture", "image", "image"),
    wire("wire_camera", "image", "wire_picture", "image", "image"),
    wire("oil_edge", "intensity_profile", "oil_chart", "value", "array"),
    wire("wire_edge", "intensity_profile", "wire_chart", "value", "array"),
    wire("oil_edge", "diameter_px", "oil_px_display", "value", "numeric"),
    wire("drop_mm", "diameter_mm", "oil_mm_display", "value", "numeric"),
    wire("wire_edge", "diameter_px", "wire_px_display", "value", "numeric"),
    wire("wire_cal", "scale_factor_mm_per_px", "scale_display", "value", "numeric"),
    wire("ift", "omega_squared", "omega_display", "value", "numeric"),
    wire("ift", "radius_cubed", "radius_display", "value", "numeric"),
    wire("ift", "ift_N_m", "ift_n_display", "value", "numeric"),
    wire("ift", "ift_mN_m", "ift_mn_display", "value", "numeric"),
]
graph["wires"] = wires

# --- 4. front panel rebuilt to match the original LabVIEW screenshot --------
def indicator(item_id: str, terminal: str, label: str, x: float, y: float,
              w: float, h: float, z: int, **props) -> dict:
    base = {"label": label}
    base.update(props)
    return {"id": item_id, "kind": "indicator", "terminal_node_id": terminal,
            "bounds": {"x": x, "y": y, "width": w, "height": h}, "z_index": z,
            "properties": base, "extensions": {}}

front_panel = [
    # row 1
    {"id": "fp-motor", "kind": "boolean_control", "terminal_node_id": "motor",
     "bounds": {"x": 20, "y": 20, "width": 240, "height": 90}, "z_index": 0,
     "properties": {"label": "Motor", "display_type": "radio_start_stop",
                    "options": [{"label": "STOP", "value": 0}, {"label": "START", "value": 1}]},
     "extensions": {}},
    indicator("fp-rpm", "rpm_display", "RPM ACT", 280, 20, 240, 90, 1,
              display_type="gauge", minimum=0, maximum=6000, tick_interval=500),
    indicator("fp-pwm", "pwm_display", "PWM ACT", 540, 20, 240, 90, 2,
              display_type="gauge", minimum=0, maximum=255, style="half_circle",
              color_gradient=["#00b050", "#ffff00", "#ff0000"]),
    {"id": "fp-com", "kind": "string_control", "terminal_node_id": "com",
     "bounds": {"x": 800, "y": 20, "width": 220, "height": 90}, "z_index": 3,
     "properties": {"label": "COM Arduino", "display_type": "dropdown", "options": []},
     "extensions": {}},
    {"id": "fp-wifi", "kind": "string_control", "terminal_node_id": "wifi",
     "bounds": {"x": 1040, "y": 20, "width": 350, "height": 90}, "z_index": 4,
     "properties": {"label": "WIFI IP"}, "extensions": {}},
    # row 2: telemetry TIME(s) — elapsed time since the last TARGET_RPM change
    indicator("fp-time-1", "time_display_1", "TIME(s)", 1410, 20, 170, 65, 5,
              internal_role="elapsed time since last TARGET_RPM change"),
    indicator("fp-time-2", "time_display_2", "TIME(s)", 1410, 95, 170, 65, 6,
              internal_role="reserve duplicate of the elapsed display"),
    # middle left
    {"id": "fp-oil-picture", "kind": "image_indicator", "terminal_node_id": "oil_picture",
     "bounds": {"x": 20, "y": 200, "width": 430, "height": 250}, "z_index": 7,
     "properties": {"label": "Picture Oil"}, "extensions": {}},
    indicator("fp-oil-px", "oil_px_display", "Diameter (px)", 20, 460, 205, 70, 8),
    indicator("fp-oil-mm", "oil_mm_display", "Diameter (mm)", 245, 460, 205, 70, 9),
    {"id": "fp-density", "kind": "numeric_control", "terminal_node_id": "density_input",
     "bounds": {"x": 20, "y": 550, "width": 430, "height": 80}, "z_index": 10,
     "properties": {"label": "Selisih Densitas (Kg/m3)", "editor": "spinbox"},
     "extensions": {}},
    # middle right
    {"id": "fp-wire-picture", "kind": "image_indicator", "terminal_node_id": "wire_picture",
     "bounds": {"x": 470, "y": 200, "width": 430, "height": 250}, "z_index": 11,
     "properties": {"label": "Picture Comparison"}, "extensions": {}},
    indicator("fp-wire-px", "wire_px_display", "Diameter (px)", 470, 460, 205, 70, 12),
    indicator("fp-scale", "scale_display", "Scale factor (mm/pixel)", 695, 460, 205, 70, 13),
    indicator("fp-omega", "omega_display", "w²", 920, 460, 150, 70, 14, format="0.000E+0"),
    indicator("fp-radius", "radius_display", "r³", 1080, 460, 150, 70, 15, format="0.000E+0"),
    indicator("fp-ift-n", "ift_n_display", "IFT N/m", 1240, 460, 160, 70, 16, format="0.0000000"),
    indicator("fp-ift-mn", "ift_mn_display", "IFT mN/m", 1410, 460, 170, 70, 17),
    # charts (labels preserved verbatim from the original, including 'Thresold')
    {"id": "fp-oil-chart", "kind": "chart", "terminal_node_id": "oil_chart",
     "bounds": {"x": 920, "y": 140, "width": 320, "height": 250}, "z_index": 18,
     "properties": {"label": "Grafik Oil", "x_label": "Baris Pixel", "y_label": "Intensitas (Thresold)",
                    "x_min": 0, "x_max": 500, "y_min": 0, "y_max": 300, "plot_selector": "Plot 0"},
     "extensions": {}},
    {"id": "fp-wire-chart", "kind": "chart", "terminal_node_id": "wire_chart",
     "bounds": {"x": 1260, "y": 140, "width": 320, "height": 250}, "z_index": 19,
     "properties": {"label": "Grafik Kawat", "x_label": "Baris Pixel", "y_label": "Intensitas (Thresold)",
                    "x_min": 0, "x_max": 500, "y_min": 0, "y_max": 250, "plot_selector": "Plot 0"},
     "extensions": {}},
    # results table: exactly the original 8 columns
    {"id": "fp-table", "kind": "indicator", "terminal_node_id": "table_display",
     "bounds": {"x": 20, "y": 650, "width": 1540, "height": 220}, "z_index": 20,
     "properties": {"label": "RPM | Dia (px) | Dia (mm) | kg/m3 | w² | r³ | IFT N/m | IFT mN/m",
                    "display_type": "table", "background": "#ffff99",
                    "visible_rows": 6, "horizontal_scrollbar": True},
     "extensions": {}},
    # bottom-left global abort button (visual parity; engine binding pending)
    {"id": "fp-global-stop", "kind": "boolean_control", "terminal_node_id": "global_stop",
     "bounds": {"x": 20, "y": 890, "width": 120, "height": 80}, "z_index": 21,
     "properties": {"label": "STOP", "display_type": "push_button", "color": "#ff0000"},
     "extensions": {"role": "global_abort",
                    "binding_status": "visual parity only; RunController abort binding not implemented"}},
]
vi["front_panel"]["items"] = front_panel

# --- 5. honest provenance -----------------------------------------------------
vi["front_panel"]["extensions"] = {
    "hardware_basis": "TZ20002MG, 60W 12V 5A DC motor, BTS7960 HW-039, Arduino Uno clone, optical/IR pulse sensor disc (4 holes/rev)",
    "serial_protocol_status": "Ground truth from lab Arduino firmware source (found on lab PC, 2026-08-21): "
                              "PC sends START/STOP text commands; firmware replies ACK:START, ACK:STOP, "
                              "ACK:AUTOSTOP_6000; streams RPM:<int>;PWM:<int>;TIME:<float>;TARGET:<int> every "
                              "~100ms and TARGET_RPM:<int> once per stage change. RPM is computed by the "
                              "firmware (4 holes/revolution); the PC never computes RPM from raw pulses.",
    "architecture_status": "The 6-stage RPM sequence (1000..6000, 3 min per stage, autostop after 3 min at "
                           "6000 RPM) runs entirely in the Arduino firmware. PyLabView Studio is a passive "
                           "event listener: spinning_drop_stage_watcher appends one table row per firmware "
                           "stage-completion event (5x TARGET_RPM + 1x ACK:AUTOSTOP_6000) and never times "
                           "anything itself.",
    "time_fields_status": "TIME(s) displays show the firmware telemetry field TIME (seconds since the last "
                          "TARGET_RPM change); the second display is a reserved duplicate.",
    "stop_button_binding": "The red STOP button mirrors the original front panel visually; binding it to the "
                           "application-level RunController abort is not implemented yet.",
    "physical_validation": "not performed",
}

# --- 6. structural sanity before serialization --------------------------------
ids = [node["id"] for node in nodes]
if len(ids) != len(set(ids)):
    raise SystemExit("duplicate node ids after mutation")
id_set = set(ids)
for item in wires:
    if item["source_node"] not in id_set or item["target_node"] not in id_set:
        raise SystemExit(f"wire references missing node: {item}")
for item in front_panel:
    if item["terminal_node_id"] not in id_set:
        raise SystemExit(f"panel item references missing node: {item['terminal_node_id']}")

DST.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print(f"wrote {DST}: {len(nodes)} nodes, {len(wires)} wires, {len(front_panel)} panel items")
