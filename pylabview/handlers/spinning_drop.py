from __future__ import annotations

import math
import re

from ..execution import CancelledError
from ..typesystem import ErrorCluster
from .api import HandlerContext
from .registry import BUILTIN_HANDLERS as registry


_ACK_PWM = re.compile(r"ACK_PWM:(\d{1,3})")
_RPM_OK = re.compile(r"RPM:([0-9]+(?:\.[0-9]+)?):SENSOR_OK")
_RPM_NO_SENSOR = re.compile(r"RPM:0:NO_SENSOR:PWM=(\d{1,3})")


def _finite_positive(value: object, name: str) -> float:
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        from ..runtime import DataflowError
        raise DataflowError(f"{name} must be finite and greater than zero")
    return number


def _ift_error(message: str, code: int = 64) -> dict[str, object]:
    return {"omega_squared": 0.0, "radius_cubed": 0.0, "ift_N_m": 0.0,
            "ift_mN_m": 0.0, "error": ErrorCluster(True, code, message)}


@registry.register("arduino_motor_rpm")
def arduino_motor_rpm(context: HandlerContext):
    connection = None
    try:
        pwm_number = float(context.inputs["pwm"])
        pwm = int(pwm_number)
        if not math.isfinite(pwm_number) or pwm_number != pwm or not 0 <= pwm <= 255:
            raise ValueError("PWM must be an integer between 0 and 255")
        maximum = int(context.node.properties.get("response_bytes", 256))
        if maximum < 32 or maximum > 4096:
            raise ValueError("Arduino response_bytes must be between 32 and 4096")
        connection_ref = context.runtime._session_resource(
            context.session, context.caller_vi, context.node, "serial", context.graph_scope,
            lambda: context.session.resources.add("serial", context.runtime.serial.open(
                str(context.inputs["port"]), int(context.node.properties.get("baudrate", 115200)),
                float(context.node.properties.get("timeout", 1)), close_command=b"SET_PWM:0\n")))
        connection = context.session.resources.get(connection_ref, "serial")
        cancel_key = f"arduino-safe-stop:{context.caller_vi or 'graph'}:{context.graph_scope}:{context.node.id}"
        if not context.session.state.get(cancel_key):
            context.session.token.add_cancel_callback(connection.safe_stop)
            context.session.state[cancel_key] = True
        context.session.token.check()
        replies = connection.query_lines(f"SET_PWM:{pwm}\n".encode("ascii"), 2, maximum)
        context.session.token.check()
        ack_text, rpm_text = (reply.decode("ascii").strip() for reply in replies)
        ack = _ACK_PWM.fullmatch(ack_text)
        if not ack:
            raise ValueError("invalid Arduino ACK_PWM response")
        pwm_actual = int(ack.group(1))
        if not 0 <= pwm_actual <= 255:
            raise ValueError("Arduino ACK_PWM value is outside 0..255")
        if pwm_actual != pwm:
            raise ValueError("Arduino ACK_PWM does not match requested PWM")
        match = _RPM_OK.fullmatch(rpm_text)
        if match:
            rpm = float(match.group(1))
            if not math.isfinite(rpm) or rpm < 0:
                raise ValueError("Arduino RPM value is invalid")
            return {"rpm": rpm, "pwm_actual": pwm_actual, "sensor_status": "OK", "error": ErrorCluster()}
        match = _RPM_NO_SENSOR.fullmatch(rpm_text)
        if match:
            reported_pwm = int(match.group(1))
            if reported_pwm != pwm_actual or reported_pwm != pwm:
                raise ValueError("Arduino PWM values disagree")
            connection.safe_stop()
            return {"rpm": 0.0, "pwm_actual": pwm_actual, "sensor_status": "NO_SENSOR",
                    "error": ErrorCluster(True, 61, "RPM sensor did not provide verified feedback")}
        if rpm_text == "RPM:0:STOPPED":
            if pwm != 0:
                raise ValueError("Arduino reported STOPPED for a non-zero PWM request")
            return {"rpm": 0.0, "pwm_actual": pwm_actual, "sensor_status": "STOPPED", "error": ErrorCluster()}
        raise ValueError("invalid Arduino RPM response")
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
        return {"rpm": 0.0, "pwm_actual": 0, "sensor_status": "NO_SENSOR",
                "error": ErrorCluster(True, 60, str(exc))}


@registry.register("camera_capture_dual_mode")
def camera_capture_dual_mode(context: HandlerContext):
    context.session.token.check()
    image = context.runtime.vision.capture_source(
        context.inputs["mode"], context.inputs["device_index"], context.inputs["network_url"],
        context.inputs["timeout_seconds"])
    context.session.token.check()
    return image


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
    status = str(context.inputs["sensor_status"])
    if status != "OK":
        return _ift_error(f"verified RPM sensor status required; received {status}", 63)
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


@registry.register("spinning_drop_log_row")
def spinning_drop_log_row(context: HandlerContext):
    for name in ("motor_error", "ift_error"):
        error = context.inputs[name]
        if error.status:
            from ..runtime import DataflowError
            raise DataflowError(f"measurement rejected: {error.source}")
    ports = ("rpm", "diameter_px", "diameter_mm", "delta_rho", "omega_squared",
             "radius_cubed", "ift_N_m", "ift_mN_m")
    values = [float(context.inputs[port]) for port in ports]
    if not all(math.isfinite(value) for value in values):
        from ..runtime import DataflowError
        raise DataflowError("spinning-drop log values must be finite")
    headers = ["RPM", "Dia(px)", "Dia(mm)", "kg/m3", "w²", "r³", "IFT N/m", "IFT mN/m"]
    maximum = context.runtime._bounded_int(context.node, "max_rows", 1000)
    if maximum < 1 or maximum > 100_000:
        from ..runtime import DataflowError
        raise DataflowError("spinning-drop log max_rows is outside 1..100000")
    key = f"spinning-drop-log:{context.caller_vi or 'graph'}:{context.graph_scope}:{context.node.id}"
    rows = context.session.state.setdefault(key, [])
    rows.append(values)
    del rows[:-maximum]
    return [headers, *rows]


@registry.register("spinning_drop_sequencer")
def spinning_drop_sequencer(context: HandlerContext):
    state_key = f"sd-seq:{context.node.id}"
    state = context.session.state.setdefault(state_key, {
        "s": "IDLE", "idx": 0, "start": 0.0, "rows": [], "pwm": 0.0
    })
    
    start = context.inputs["start"]
    rpm_list = context.node.properties.get("rpm_list", [1000, 2000, 3000, 4000, 5000, 6000])
    dur = float(context.node.properties.get("stage_duration", 180.0))
    
    if not start and state["s"] != "IDLE":
        state.update({"s": "IDLE", "idx": 0, "rows": []})
        return {"target_pwm": 0.0, "trigger_capture": False, "state": "IDLE", "countdown": 0.0, "table_data": [], "error": ErrorCluster()}
    
    if start and state["s"] == "IDLE":
        state.update({"s": "RUNNING", "idx": 0, "start": context.runtime.clock(), "rows": []})
    
    if state["s"] == "RUNNING":
        if context.inputs["sensor_status"] != "OK" or context.inputs["motor_error"].status or context.inputs["capture_error"].status:
            state["s"] = "ERROR"
            return {"target_pwm": 0.0, "trigger_capture": False, "state": "ERROR", "countdown": 0.0, "table_data": [], 
                    "error": ErrorCluster(True, 62, "Hardware error: sequencer halted")}

        now = context.runtime.clock()
        elapsed = now - state["start"]
        target_rpm = rpm_list[state["idx"]]
        target_pwm = target_rpm * 255.0 / 6000.0
        
        if elapsed >= dur:
            ports = ("rpm_measured", "diameter_px", "diameter_mm", "delta_rho", "omega_squared", "radius_cubed", "ift_N_m", "ift_mN_m")
            state["rows"].append([float(context.inputs[p]) for p in ports])
            
            if state["idx"] < len(rpm_list) - 1:
                state.update({"idx": state["idx"] + 1, "start": now})
                return {"target_pwm": target_pwm, "trigger_capture": True, "state": f"STAGE_{state['idx']}", "countdown": dur, "table_data": state["rows"], "error": ErrorCluster()}
            else:
                state["s"] = "AWAITING_STOP"
                return {"target_pwm": 0.0, "trigger_capture": True, "state": "AWAITING_STOP", "countdown": 0.0, "table_data": state["rows"], "error": ErrorCluster()}
        
        return {"target_pwm": target_pwm, "trigger_capture": False, "state": f"STAGE_{state['idx']}", "countdown": max(0.0, dur - elapsed), "table_data": state["rows"], "error": ErrorCluster()}

    if state["s"] == "AWAITING_STOP":
        return {"target_pwm": 0.0, "trigger_capture": False, "state": "AWAITING_STOP", "countdown": 0.0, "table_data": state["rows"], "error": ErrorCluster()}
        
    return {"target_pwm": 0.0, "trigger_capture": False, "state": state["s"], "countdown": 0.0, "table_data": state["rows"], "error": ErrorCluster()}
