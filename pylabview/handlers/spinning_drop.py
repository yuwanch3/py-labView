from __future__ import annotations

import math
import re

from ..execution import CancelledError
from ..typesystem import ErrorCluster
from .api import HandlerContext
from .registry import BUILTIN_HANDLERS as registry


# Ground truth: lab Arduino firmware source (found on the lab PC, 2026-08-21).
# The firmware runs the 6-stage RPM sequence itself (1000..6000, 3 min per
# stage, autostop after 3 min at 6000). The PC is a passive listener.
_TELEMETRY = re.compile(r"RPM:(\d+);PWM:(\d+);TIME:(\d+(?:\.\d+)?);TARGET:(\d+)")
_TARGET_EVENT = re.compile(r"TARGET_RPM:(\d+)")


def _finite_positive(value: object, name: str) -> float:
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        from ..runtime import DataflowError
        raise DataflowError(f"{name} must be finite and greater than zero")
    return number


def _ift_error(message: str, code: int = 64) -> dict[str, object]:
    return {"omega_squared": 0.0, "radius_cubed": 0.0, "ift_N_m": 0.0,
            "ift_mN_m": 0.0, "error": ErrorCluster(True, code, message)}


@registry.register("arduino_telemetry_reader")
def arduino_telemetry_reader(context: HandlerContext):
    """Passive serial listener for the spinning-drop firmware.

    Sends START once on the rising edge of `run` and STOP once on the falling
    edge; everything else is draining an unsolicited stream. Tolerant of
    garbage and partial lines: unrecognized lines are dropped, partial chunks
    stay buffered inside SerialConnection until their newline arrives.
    """
    connection = None
    state_key = f"telemetry:{context.caller_vi or 'graph'}:{context.graph_scope}:{context.node.id}"
    state = context.session.state.setdefault(state_key, {
        "running": False, "start_pending": False,
        "rpm": 0.0, "pwm": 0.0, "elapsed": 0.0, "target": 0.0})
    try:
        run = bool(context.inputs["run"])
        maximum = int(context.node.properties.get("response_bytes", 4096))
        if maximum < 32 or maximum > 65536:
            raise ValueError("Arduino response_bytes must be between 32 and 65536")
        max_lines = int(context.node.properties.get("max_lines", 32))
        if max_lines < 1 or max_lines > 256:
            raise ValueError("Arduino max_lines must be between 1 and 256")
        connection_ref = context.runtime._session_resource(
            context.session, context.caller_vi, context.node, "serial", context.graph_scope,
            lambda: context.session.resources.add("serial", context.runtime.serial.open(
                str(context.inputs["port"]), int(context.node.properties.get("baudrate", 115200)),
                float(context.node.properties.get("timeout", 0.2)), close_command=b"STOP\n")))
        connection = context.session.resources.get(connection_ref, "serial")
        cancel_key = f"arduino-safe-stop:{context.caller_vi or 'graph'}:{context.graph_scope}:{context.node.id}"
        if not context.session.state.get(cancel_key):
            context.session.token.add_cancel_callback(connection.safe_stop)
            context.session.state[cancel_key] = True
        context.session.token.check()

        if run and not state["running"] and not state["start_pending"]:
            if int(connection.write(b"START\n")) != len(b"START\n"):
                raise OSError("incomplete serial command write")
            state["start_pending"] = True
        if not run and (state["running"] or state["start_pending"]):
            if int(connection.write(b"STOP\n")) != len(b"STOP\n"):
                raise OSError("incomplete serial command write")
            state["running"] = False
            state["start_pending"] = False
        context.session.token.check()

        stage_changed = False
        autostop = False
        for raw in connection.read_incoming(max_lines, maximum):
            text = raw.decode("ascii", errors="replace").strip()
            if not text:
                continue
            match = _TELEMETRY.fullmatch(text)
            if match:
                state["rpm"] = float(match.group(1))
                state["pwm"] = float(match.group(2))
                state["elapsed"] = float(match.group(3))
                state["target"] = float(match.group(4))
                continue
            match = _TARGET_EVENT.fullmatch(text)
            if match:
                state["target"] = float(match.group(1))
                stage_changed = True
                continue
            if text == "ACK:START":
                state["start_pending"] = False
                state["running"] = True
                continue
            if text == "ACK:STOP":
                continue
            if text == "ACK:AUTOSTOP_6000":
                autostop = True
                continue
            # Garbage or unknown line: tolerated and ignored by design.
        context.session.token.check()
        return {"rpm": float(state["rpm"]), "pwm": float(state["pwm"]),
                "elapsed_time_s": float(state["elapsed"]),
                "current_target_rpm": float(state["target"]),
                "stage_changed": stage_changed, "autostop": autostop,
                "error": ErrorCluster()}
    except CancelledError:
        if connection is not None:
            try:
                connection.safe_stop()
            except Exception:
                pass
        raise
    except (KeyError, OSError, RuntimeError, TypeError, UnicodeError, ValueError) as exc:
        if connection is not None:
            try:
                connection.safe_stop()
            except Exception:
                pass
        return {"rpm": 0.0, "pwm": 0.0, "elapsed_time_s": 0.0, "current_target_rpm": 0.0,
                "stage_changed": False, "autostop": False,
                "error": ErrorCluster(True, 60, str(exc))}


@registry.register("rpm_stall_watchdog")
def rpm_stall_watchdog(context: HandlerContext):
    """PC-side safety net. The firmware reports no sensor status, so a dead
    sensor or motor is inferred locally: rpm staying at 0 while the target
    demands rotation. This is explicitly a PC-side inference, NOT data from
    the Arduino."""
    state_key = f"rpm-stall:{context.caller_vi or 'graph'}:{context.graph_scope}:{context.node.id}"
    state = context.session.state.setdefault(state_key, {"zero_since": None, "stalled": False})
    run = bool(context.inputs["run"])
    target = float(context.inputs["current_target_rpm"])
    rpm = float(context.inputs["rpm"])
    seconds = float(context.node.properties.get("stall_seconds", 10.0))
    if not math.isfinite(seconds) or not 1.0 <= seconds <= 600.0:
        from ..runtime import DataflowError
        raise DataflowError("stall_seconds must be between 1 and 600")
    if not run or target <= 0 or not math.isfinite(rpm) or not math.isfinite(target):
        state.update({"zero_since": None, "stalled": False})
        return False
    if rpm <= 0.0:
        now = context.runtime.clock()
        if state["zero_since"] is None:
            state["zero_since"] = now
        elif now - state["zero_since"] >= seconds:
            state["stalled"] = True
    else:
        state.update({"zero_since": None, "stalled": False})
    return bool(state["stalled"])


@registry.register("spinning_drop_stage_watcher")
def spinning_drop_stage_watcher(context: HandlerContext):
    """Event-driven table builder. All timing belongs to the Arduino firmware;
    this node NEVER measures stage duration itself. A row is appended exactly
    when the firmware reports the next TARGET_RPM (meaning the previous stage
    finished its hold) or when it announces ACK:AUTOSTOP_6000 (final 6000 RPM
    row). The firmware never announces its initial target: receiving START
    makes it ramp to a hardcoded 1000 RPM without any serial event, so the
    IDLE->RUNNING transition seeds last_target=1000 here. Full cycle yields
    exactly 6 rows: five TARGET_RPM events (2000..6000) complete stages
    1000..5000, and the autostop acknowledgement completes 6000."""
    headers = ["RPM", "Dia (px)", "Dia (mm)", "kg/m3", "w²", "r³", "IFT N/m", "IFT mN/m"]
    measured = ("diameter_px", "diameter_mm", "delta_rho", "omega_squared",
                "radius_cubed", "ift_N_m", "ift_mN_m")
    state_key = f"stage-watcher:{context.caller_vi or 'graph'}:{context.graph_scope}:{context.node.id}"
    state = context.session.state.setdefault(state_key, {"s": "IDLE", "rows": [], "last_target": None})

    def result(state_label: str | None = None, error: ErrorCluster | None = None) -> dict[str, object]:
        return {"table_data": [headers, *state["rows"]],
                "state": state_label or state["s"],
                "error": error if error is not None else ErrorCluster()}

    run = bool(context.inputs["run"])
    if not run:
        state.update({"s": "IDLE", "rows": [], "last_target": None})
        return result()

    if context.inputs["error"].status:
        state["s"] = "ERROR"
        return result("ERROR", ErrorCluster(True, 66, f"serial fault: watcher halted ({context.inputs['error'].source})"))
    if bool(context.inputs["stalled"]):
        state["s"] = "ERROR"
        return result("ERROR", ErrorCluster(True, 67, "RPM stall detected: watcher halted"))

    if state["s"] == "IDLE":
        state["s"] = "RUNNING"
        # The firmware hardcodes targetRPM=1000 when START is received and
        # never announces it on serial; TARGET_RPM events only fire on the
        # increments to 2000..6000. Seed the implicit initial target here so
        # the first TARGET_RPM:2000 event completes stage 1000 instead of
        # silently dropping it.
        state["last_target"] = 1000.0

    if state["s"] == "RUNNING":
        def snapshot(completed_rpm: float) -> list[float]:
            row = [float(completed_rpm)] + [float(context.inputs[port]) for port in measured]
            return row if all(math.isfinite(value) for value in row) else []

        if bool(context.inputs["stage_changed"]):
            new_target = float(context.inputs["current_target_rpm"])
            if state["last_target"] is not None:
                row = snapshot(float(state["last_target"]))
                if row:
                    state["rows"].append(row)
            state["last_target"] = new_target
        if bool(context.inputs["autostop"]):
            if state["last_target"] is not None:
                row = snapshot(float(state["last_target"]))
                if row:
                    state["rows"].append(row)
            state["s"] = "AWAITING_STOP"

    return result()


@registry.register("camera_capture_dual_mode")
def camera_capture_dual_mode(context: HandlerContext):
    """Capture source, decoupled per node so each camera is a distinct event.

    The oil and wire-comparison captures are separate trigger domains. A live
    node (capture_trigger held True) re-grabs the stream every tick; a staged
    wire node (capture_trigger False until the operator initiates) instead
    re-emits its last held frame and never silently re-grabs next to the oil
    node. Without this, the comparison capture fired in the same instant from
    the same source and returned an identical frame.
    """
    key = f"camera:{context.caller_vi or 'graph'}:{context.graph_scope}:{context.node.id}"
    state = context.session.state.setdefault(key, {"frame": None})
    if bool(context.inputs["capture_trigger"]):
        frame = context.runtime.vision.capture_source(
            context.inputs["mode"], context.inputs["device_index"],
            context.inputs["network_url"], context.inputs["timeout_seconds"])
        if frame is not None:
            state["frame"] = frame
    return state["frame"]


@registry.register("edge_intensity_profile")
def edge_intensity_profile(context: HandlerContext):
    context.session.token.check()
    result = context.runtime.vision.edge_intensity_profile(
        context.inputs["image"], context.inputs["scan_orientation"],
        context.node.properties.get("threshold", 127), context.node.properties.get("foreground", "dark"))
    context.session.token.check()
    return result


@registry.register("wire_calibration")
def wire_calibration(context: HandlerContext):
    pixels = _finite_positive(context.inputs["diameter_px"], "wire diameter_px")
    diameter_mm = _finite_positive(context.inputs["known_wire_diameter_mm"], "known wire diameter")
    return diameter_mm / pixels


@registry.register("pixel_to_mm")
def pixel_to_mm(context: HandlerContext):
    pixels = _finite_positive(context.inputs["diameter_px"], "drop diameter_px")
    scale = _finite_positive(context.inputs["scale_factor_mm_per_px"], "scale factor")
    return pixels * scale


@registry.register("vonnegut_ift")
def vonnegut_ift(context: HandlerContext):
    from ..runtime import DataflowError
    try:
        rpm = _finite_positive(context.inputs["rpm"], "rpm")
        diameter_mm = _finite_positive(context.inputs["diameter_mm"], "diameter_mm")
        delta_rho = _finite_positive(context.inputs["delta_rho"], "delta_rho")
    except (DataflowError, TypeError, ValueError) as exc:
        return _ift_error(str(exc))
    radius_m = diameter_mm / 1000.0 / 2.0
    omega = 2.0 * math.pi * rpm / 60.0
    omega_squared = omega ** 2
    radius_cubed = radius_m ** 3
    gamma_n_m = delta_rho * omega_squared * radius_cubed / 4.0
    return {"omega_squared": omega_squared, "radius_cubed": radius_cubed,
            "ift_N_m": gamma_n_m, "ift_mN_m": gamma_n_m * 1000.0, "error": ErrorCluster()}


@registry.register("pycnometer_density")
def pycnometer_density(context: HandlerContext):
    empty = float(context.inputs["bottle_weight_empty_g"])
    gross = float(context.inputs["bottle_weight_gross_g"])
    volume = _finite_positive(context.inputs["volume_ml"], "volume_ml")
    if not math.isfinite(empty) or not math.isfinite(gross) or gross <= empty:
        from ..runtime import DataflowError
        raise DataflowError("gross bottle weight must be finite and greater than empty bottle weight")
    density_g_ml = (gross - empty) / volume
    return {"density_g_ml": density_g_ml, "density_kg_m3": density_g_ml * 1000.0}


@registry.register("delta_density")
def delta_density(context: HandlerContext):
    first = float(context.inputs["density_1"])
    second = float(context.inputs["density_2"])
    if not math.isfinite(first) or not math.isfinite(second) or first <= 0 or second <= 0:
        from ..runtime import DataflowError
        raise DataflowError("densities must be finite and greater than zero")
    return abs(first - second)
