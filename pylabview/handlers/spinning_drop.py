

import math
import re

from datetime import datetime

from ..execution import CancelledError
from ..paths import (
    captures_dir,
    session_reference_dir,
    session_stage_dir,
)
from ..typesystem import ErrorCluster
from .api import HandlerContext
from .registry import BUILTIN_HANDLERS as registry


# ================================================================
# ARDUINO TELEMETRY
# ================================================================

# Ground truth: lab Arduino firmware source (found on the lab PC, 2026-08-21).
# The firmware runs the 6-stage RPM sequence itself (1000..6000, 3 min per
# stage, autostop after 3 min at 6000). The PC is a passive listener.

_TELEMETRY = re.compile(
    r"RPM:(\d+);PWM:(\d+);TIME:(\d+(?:\.\d+)?);TARGET:(\d+)"
)

_TARGET_EVENT = re.compile(
    r"TARGET_RPM:(\d+)"
)

_GRADUAL_STOP_REQUEST_KEY = "spinning-drop-gradual-stop-requested"
_GRADUAL_STOP_COMPLETE_KEY = "spinning-drop-gradual-stop-complete"


def _hold_state_key(
    context: HandlerContext,
) -> str:

    return (
        f"spinning-drop-hold:"
        f"{context.caller_vi or 'graph'}:"
        f"{context.graph_scope}"
    )


def _stage_capture_key(
    context: HandlerContext,
) -> str:

    return (
        f"spinning-drop-stage-capture:"
        f"{context.caller_vi or 'graph'}:"
        f"{context.graph_scope}"
    )


def _stage_snapshot_frame_key(
    context: HandlerContext,
) -> str:

    return (
        f"spinning-drop-stage-snapshot-frame:"
        f"{context.caller_vi or 'graph'}:"
        f"{context.graph_scope}"
    )


def _stage_sample_event_key(
    context: HandlerContext,
) -> str:

    return (
        f"spinning-drop-stage-sample-event:"
        f"{context.caller_vi or 'graph'}:"
        f"{context.graph_scope}"
    )


def _stage_measurements_key(
    context: HandlerContext,
) -> str:

    return (
        f"spinning-drop-stage-measurements:"
        f"{context.caller_vi or 'graph'}:"
        f"{context.graph_scope}"
    )


def _stage_summary_from_samples(
    rpm: float,
    samples: list[dict[str, object]],
) -> tuple[list[float], dict[str, float]] | None:

    if len(samples) != 10:
        return None

    try:
        diameters_px = [float(sample["diameter_px"]) for sample in samples]
        diameters_mm = [float(sample["diameter_mm"]) for sample in samples]
        delta_rhos = [float(sample["delta_rho"]) for sample in samples]
    except (KeyError, TypeError, ValueError):
        return None

    values = [*diameters_px, *diameters_mm, *delta_rhos, float(rpm)]
    if not all(math.isfinite(value) and value > 0.0 for value in values):
        return None

    n = len(diameters_px)
    mean_px = sum(diameters_px) / n
    mean_mm = sum(diameters_mm) / n
    minimum_px = min(diameters_px)
    maximum_px = max(diameters_px)
    variance_px = sum((value - mean_px) ** 2 for value in diameters_px) / (n - 1)
    std_dev_px = math.sqrt(variance_px)
    cv_percent = std_dev_px / mean_px * 100.0
    delta_rho = sum(delta_rhos) / len(delta_rhos)
    omega = 2.0 * math.pi * float(rpm) / 60.0
    omega_squared = omega ** 2
    radius_m = mean_mm / 1000.0 / 2.0
    radius_cubed = radius_m ** 3
    ift_n_m = delta_rho * omega_squared * radius_cubed / 4.0
    ift_mn_m = ift_n_m * 1000.0

    row = [
        float(rpm),
        mean_px,
        mean_mm,
        delta_rho,
        omega_squared,
        radius_cubed,
        ift_n_m,
        ift_mn_m,
    ]

    statistics = {
        "n": float(n),
        "mean_diameter_px": mean_px,
        "min_diameter_px": minimum_px,
        "max_diameter_px": maximum_px,
        "std_dev_diameter_px": std_dev_px,
        "cv_percent": cv_percent,
    }

    return row, statistics


def _telemetry_snapshot_key(
    context: HandlerContext,
) -> str:

    return (
        f"spinning-drop-telemetry-snapshot:"
        f"{context.caller_vi or 'graph'}:"
        f"{context.graph_scope}"
    )


def _max_rpm_reached_key(
    context: HandlerContext,
) -> str:

    return (
        f"spinning-drop-max-rpm-reached:"
        f"{context.caller_vi or 'graph'}:"
        f"{context.graph_scope}"
    )


def _active_session_root(
    context: HandlerContext,
):
    """
    Return the application-owned active session root when available.

    The app owns session lifecycle and exposes the current session through
    DataflowRuntime. If unavailable, existing legacy capture behaviour is
    preserved.
    """

    return getattr(
        context.runtime,
        "gmj_session_root",
        None,
    )


def _manual_mode_active(
    context: HandlerContext,
) -> bool:
    """
    Detect the active Manual-RPM runtime from its existing session state.

    Manual telemetry must already exist before telemetry_run can be True,
    so this safely prevents the shared camera handler from applying the
    Standard-only initial 1000-RPM auto-capture rule in Manual mode.
    """

    return any(
        str(key).startswith(
            (
                "manual-telemetry:",
                "manual-stage-watcher:",
                "spinning-drop-manual-run-generation:",
            )
        )
        for key in context.session.state
    )


def _capture_path_with_daily_sequence(
    capture_folder,
    prefix: str,
):
    """
    Build one capture path using a per-prefix daily sequence.

    New format:
        <prefix>_YYYYMMDD_HHMMSS_001.jpg
        <prefix>_YYYYMMDD_HHMMSS_002.jpg

    The sequence resets automatically when the date changes.
    Older microsecond-style filenames are ignored.
    """

    now = datetime.now()

    date_text = now.strftime(
        "%Y%m%d"
    )

    time_text = now.strftime(
        "%H%M%S"
    )

    # IMPORTANT:
    # This regex uses real digit tokens (\d), not escaped literal "\\d".
    pattern = re.compile(
        rf"^{re.escape(prefix)}_{date_text}_\d{{6}}_(\d{{3}})\.jpg$"
    )

    last_sequence = 0

    for existing_path in capture_folder.glob(
        f"{prefix}_{date_text}_*.jpg"
    ):
        match = pattern.fullmatch(
            existing_path.name
        )

        if match:
            last_sequence = max(
                last_sequence,
                int(
                    match.group(1)
                ),
            )

    sequence = (
        last_sequence
        + 1
    )

    return (
        capture_folder
        / (
            f"{prefix}_"
            f"{date_text}_"
            f"{time_text}_"
            f"{sequence:03d}.jpg"
        )
    )


def _finite_positive(
    value: object,
    name: str,
) -> float:

    number = float(value)

    if (
        not math.isfinite(number)
        or number <= 0
    ):
        from ..runtime import DataflowError

        raise DataflowError(
            f"{name} must be finite and greater than zero"
        )

    return number


def _ift_error(
    message: str,
    code: int = 64,
) -> dict[str, object]:

    return {
        "omega_squared": 0.0,
        "radius_cubed": 0.0,
        "ift_N_m": 0.0,
        "ift_mN_m": 0.0,
        "error": ErrorCluster(
            True,
            code,
            message,
        ),
    }


# ================================================================
# ARDUINO TELEMETRY READER
# ================================================================

@registry.register("arduino_telemetry_reader")
def arduino_telemetry_reader(
    context: HandlerContext,
):

    """
    Passive serial listener for the spinning-drop firmware.

    Sends START once on the rising edge of `run` and STOP once on
    the falling edge.

    Everything else is draining an unsolicited serial stream.
    """

    connection = None

    state_key = (
        f"telemetry:"
        f"{context.caller_vi or 'graph'}:"
        f"{context.graph_scope}:"
        f"{context.node.id}"
    )

    state = context.session.state.setdefault(
        state_key,
        {
            "running": False,
            "start_pending": False,
            "rpm": 0.0,
            "pwm": 0.0,
            "elapsed": 0.0,
            "target": 0.0,
            "soft_stop_acknowledged": False,
            "soft_stop_last_sent": None,
        },
    )

    try:

        run = bool(
            context.inputs["run"]
        )

        soft_stop_requested = bool(
            context.session.state.get(
                _GRADUAL_STOP_REQUEST_KEY,
                False,
            )
        )

        max_rpm_reached = bool(
            context.session.state.get(
                _max_rpm_reached_key(context),
                False,
            )
        )

        # Selecting Motor STOP acknowledges a completed 6000-RPM run
        # and arms the system for a future new START.
        if not run and max_rpm_reached:
            context.session.state[
                _max_rpm_reached_key(context)
            ] = False
            max_rpm_reached = False

        # Keep the last displayed measurement values after either
        # operator STOP or automatic completion at 6000 RPM.
        context.session.state[
            _hold_state_key(context)
        ] = (
            not run
            or max_rpm_reached
        )

        maximum = int(
            context.node.properties.get(
                "response_bytes",
                4096,
            )
        )

        if (
            maximum < 32
            or maximum > 65536
        ):
            raise ValueError(
                "Arduino response_bytes must be "
                "between 32 and 65536"
            )

        max_lines = int(
            context.node.properties.get(
                "max_lines",
                32,
            )
        )

        if (
            max_lines < 1
            or max_lines > 256
        ):
            raise ValueError(
                "Arduino max_lines must be "
                "between 1 and 256"
            )

        connection_ref = (
            context.runtime._session_resource(
                context.session,
                context.caller_vi,
                context.node,
                "serial",
                context.graph_scope,
                lambda: context.session.resources.add(
                    "serial",
                    context.runtime.serial.open(
                        str(
                            context.inputs["port"]
                        ),
                        int(
                            context.node.properties.get(
                                "baudrate",
                                115200,
                            )
                        ),
                        float(
                            context.node.properties.get(
                                "timeout",
                                0.2,
                            )
                        ),
                        close_command=b"STOP\n",
                    ),
                ),
            )
        )

        connection = (
            context.session.resources.get(
                connection_ref,
                "serial",
            )
        )

        cancel_key = (
            f"arduino-safe-stop:"
            f"{context.caller_vi or 'graph'}:"
            f"{context.graph_scope}:"
            f"{context.node.id}"
        )

        if not context.session.state.get(
            cancel_key
        ):

            context.session.token.add_cancel_callback(
                connection.safe_stop
            )

            context.session.state[
                cancel_key
            ] = True

        context.session.token.check()

        # ========================================================
        # START
        # ========================================================

        if (
            run
            and not soft_stop_requested
            and not max_rpm_reached
            and not state["running"]
            and not state["start_pending"]
        ):

            # New run: restart target-change tracking only.
            state["target"] = 0.0

            if (
                int(
                    connection.write(
                        b"START\n"
                    )
                )
                != len(
                    b"START\n"
                )
            ):
                raise OSError(
                    "incomplete serial command write"
                )

            state[
                "start_pending"
            ] = True

        # ========================================================
        # SOFT / GRADUAL STOP
        # ========================================================
        # Arduino owns the ramp-down. Retry until ACK so this remains
        # robust to a transiently missed command without changing serial
        # adapter behavior.
        if (
            soft_stop_requested
            and run
            and not bool(
                context.session.state.get(
                    _GRADUAL_STOP_COMPLETE_KEY,
                    False,
                )
            )
        ):
            now = context.runtime.clock()
            last_sent = state["soft_stop_last_sent"]

            if (
                not state["soft_stop_acknowledged"]
                and (
                    last_sent is None
                    or now - float(last_sent) >= 1.0
                )
            ):
                command = b"SOFT_STOP\n"

                if int(
                    connection.write(
                        command
                    )
                ) != len(command):
                    raise OSError(
                        "incomplete SOFT_STOP command write"
                    )

                state["soft_stop_last_sent"] = now

        # ========================================================
        # STOP
        # ========================================================

        if (
            not run
            and (
                state["running"]
                or state["start_pending"]
            )
        ):

            if (
                int(
                    connection.write(
                        b"STOP\n"
                    )
                )
                != len(
                    b"STOP\n"
                )
            ):
                raise OSError(
                    "incomplete serial command write"
                )

            state["running"] = False
            state["start_pending"] = False

        context.session.token.check()

        stage_changed = False
        autostop = False

        for raw in connection.read_incoming(
            max_lines,
            maximum,
        ):

            text = raw.decode(
                "ascii",
                errors="replace",
            ).strip()

            if not text:
                continue

            # ====================================================
            # TELEMETRY
            # ====================================================

            match = _TELEMETRY.fullmatch(
                text
            )

            if match:

                # Arduino keeps reporting zero packets after STOP or
                # after automatic completion. Ignore them so the UI
                # holds the final valid measurement values.
                if (
                    not run
                    or bool(
                        context.session.state.get(
                            _max_rpm_reached_key(context),
                            False,
                        )
                    )
                ):
                    continue

                new_rpm = float(
                    match.group(1)
                )

                new_pwm = float(
                    match.group(2)
                )

                new_elapsed = float(
                    match.group(3)
                )

                new_target = float(
                    match.group(4)
                )

                previous_target = float(
                    state["target"]
                )

                # Robust autostop fallback:
                # TARGET 6000 -> 0 marks normal completion. Latch the
                # completed state BEFORE accepting the zero packet so
                # the last valid 6000-RPM telemetry remains visible.
                if (
                    not soft_stop_requested
                    and previous_target >= 6000.0
                    and new_target == 0.0
                ):
                    autostop = True
                    state["running"] = False
                    state["start_pending"] = False

                    context.session.state[
                        _max_rpm_reached_key(context)
                    ] = True

                    context.session.state[
                        _hold_state_key(context)
                    ] = True

                    continue

                state["rpm"] = new_rpm
                state["pwm"] = new_pwm
                state["elapsed"] = new_elapsed

                # Fallback stage detection:
                # Only official Standard stages may create a
                # measurement-stage event.
                #
                # Internal firmware ramp targets such as
                # 1250, 1500, 1750, 2250, etc. are NOT
                # measurement stages.

                official_standard_stages = (
                    1000,
                    2000,
                    3000,
                    4000,
                    5000,
                    6000,
                )

                if (
                    not soft_stop_requested
                    and previous_target > 0.0
                    and new_target > 0.0
                    and new_target != previous_target
                    and int(round(new_target)) in official_standard_stages
                ):
                    stage_changed = True

                state["target"] = new_target

                continue

            # ====================================================
            # TARGET EVENT
            # ====================================================

            match = (
                _TARGET_EVENT.fullmatch(
                    text
                )
            )

            if match:

                state["target"] = float(
                    match.group(1)
                )

                if not soft_stop_requested:
                    stage_changed = True

                continue

            if text == "ACK:START":

                state["start_pending"] = False
                state["running"] = True

                continue

            if text == "ACK:SOFT_STOP":
                state["soft_stop_acknowledged"] = True
                continue

            if text == "ACK:SOFT_STOP_COMPLETE":
                state["running"] = False
                state["start_pending"] = False
                state["soft_stop_acknowledged"] = True

                context.session.state[
                    _GRADUAL_STOP_COMPLETE_KEY
                ] = True

                context.session.state[
                    _hold_state_key(context)
                ] = True

                continue

            if text == "ACK:STOP":
                continue

            if text == "ACK:AUTOSTOP_6000":

                autostop = True
                state["running"] = False
                state["start_pending"] = False

                context.session.state[
                    _max_rpm_reached_key(context)
                ] = True

                context.session.state[
                    _hold_state_key(context)
                ] = True

                continue

            # Unknown / garbage line intentionally ignored.

        context.session.token.check()

        context.session.state[
            _telemetry_snapshot_key(context)
        ] = {
            "run": run,
            "rpm": float(
                state["rpm"]
            ),
            "target": float(
                state["target"]
            ),
        }

        return {
            "rpm": float(
                state["rpm"]
            ),
            "pwm": float(
                state["pwm"]
            ),
            "elapsed_time_s": float(
                state["elapsed"]
            ),
            "current_target_rpm": float(
                state["target"]
            ),
            "stage_changed": stage_changed,
            "autostop": autostop,
            "error": ErrorCluster(),
        }

    except CancelledError:

        if connection is not None:

            try:
                connection.safe_stop()
            except Exception:
                pass

        raise

    except (
        KeyError,
        OSError,
        RuntimeError,
        TypeError,
        UnicodeError,
        ValueError,
    ) as exc:

        if connection is not None:

            try:
                connection.safe_stop()
            except Exception:
                pass

        return {
            "rpm": 0.0,
            "pwm": 0.0,
            "elapsed_time_s": 0.0,
            "current_target_rpm": 0.0,
            "stage_changed": False,
            "autostop": False,
            "error": ErrorCluster(
                True,
                60,
                str(exc),
            ),
        }


# ================================================================
# RPM STALL WATCHDOG
# ================================================================

@registry.register("rpm_stall_watchdog")
def rpm_stall_watchdog(
    context: HandlerContext,
):

    """
    PC-side safety net.

    A dead RPM sensor / motor is inferred when actual RPM stays zero
    while Arduino is requesting a positive target RPM.
    """

    state_key = (
        f"rpm-stall:"
        f"{context.caller_vi or 'graph'}:"
        f"{context.graph_scope}:"
        f"{context.node.id}"
    )

    state = context.session.state.setdefault(
        state_key,
        {
            "zero_since": None,
            "stalled": False,
        },
    )

    run = bool(
        context.inputs["run"]
    )

    target = float(
        context.inputs[
            "current_target_rpm"
        ]
    )

    rpm = float(
        context.inputs["rpm"]
    )

    seconds = float(
        context.node.properties.get(
            "stall_seconds",
            10.0,
        )
    )

    if (
        not math.isfinite(seconds)
        or not 1.0 <= seconds <= 600.0
    ):
        from ..runtime import DataflowError

        raise DataflowError(
            "stall_seconds must be between 1 and 600"
        )

    if (
        not run
        or target <= 0
        or not math.isfinite(rpm)
        or not math.isfinite(target)
    ):

        state.update(
            {
                "zero_since": None,
                "stalled": False,
            }
        )

        return False

    if rpm <= 0.0:

        now = (
            context.runtime.clock()
        )

        if (
            state["zero_since"]
            is None
        ):

            state["zero_since"] = now

        elif (
            now
            - state["zero_since"]
            >= seconds
        ):

            state["stalled"] = True

    else:

        state.update(
            {
                "zero_since": None,
                "stalled": False,
            }
        )

    return bool(
        state["stalled"]
    )


# ================================================================
# SPINNING DROP STAGE WATCHER
# ================================================================

@registry.register(
    "spinning_drop_stage_watcher"
)
def spinning_drop_stage_watcher(
    context: HandlerContext,
):

    """
    Event-driven table builder.

    Official stage rows are created from the mean of exactly 10 saved
    stage samples. Arduino still owns all stage timing.
    """

    headers = [
        "RPM",
        "Dia (px)",
        "Dia (mm)",
        "kg/m3",
        "w²",
        "r³",
        "IFT N/m",
        "IFT mN/m",
    ]

    state_key = (
        f"stage-watcher:"
        f"{context.caller_vi or 'graph'}:"
        f"{context.graph_scope}:"
        f"{context.node.id}"
    )

    state = context.session.state.setdefault(
        state_key,
        {
            "s": "IDLE",
            "rows": [],
            "last_target": None,
            "sample_rpm": None,
            "samples": [],
            "last_completed_rpm": None,
        },
    )

    def result(state_label=None, error=None):
        return {
            "table_data": [headers, *state["rows"]],
            "state": state_label or state["s"],
            "error": error if error is not None else ErrorCluster(),
        }

    run = bool(context.inputs["run"])

    if not run:
        state.update({
            "s": "IDLE",
            "last_target": None,
            "sample_rpm": None,
            "samples": [],
        })
        return result()

    if context.inputs["error"].status:
        state["s"] = "ERROR"
        return result(
            "ERROR",
            ErrorCluster(True, 66, "serial fault: watcher halted " f"({context.inputs['error'].source})"),
        )

    if bool(context.inputs["stalled"]):
        state["s"] = "ERROR"
        return result("ERROR", ErrorCluster(True, 67, "RPM stall detected: watcher halted"))

    if state["s"] == "MAX_RPM_REACHED":
        return result(
            "MAX_RPM_REACHED",
            ErrorCluster(True, 68, "Maximum RPM 6000 reached. Measurement completed. Start a new run to continue."),
        )

    if state["s"] == "IDLE":
        state["s"] = "RUNNING"
        state["rows"] = []
        state["last_target"] = 1000.0
        state["sample_rpm"] = None
        state["samples"] = []
        state["last_completed_rpm"] = None
        context.session.state[_stage_measurements_key(context)] = []
        context.runtime.gmj_stage_measurements = []

    if state["s"] == "RUNNING":

        if bool(context.inputs["stage_changed"]):
            new_target = float(context.inputs["current_target_rpm"])
            state["last_target"] = new_target
            if new_target > 0.0:
                context.session.state[_stage_capture_key(context)] = int(round(new_target))

        sample_event = context.session.state.pop(_stage_sample_event_key(context), None)

        if sample_event is not None:
            try:
                sample_rpm = float(sample_event["rpm"])
                sample_index = int(sample_event["sample_index"])
                sample_path = str(sample_event["path"])
                diameter_px = float(
                    context.inputs["diameter_px"]
                )

                diameter_mm = float(
                    context.inputs["diameter_mm"]
                )

                scale_factor_mm_per_px = (
                    diameter_mm
                    / diameter_px
                    if (
                        math.isfinite(diameter_px)
                        and diameter_px > 0.0
                        and math.isfinite(diameter_mm)
                        and diameter_mm > 0.0
                    )
                    else 0.0
                )

                sample = {
                    "rpm": sample_rpm,
                    "sample": sample_index,
                    "diameter_px": diameter_px,
                    "diameter_mm": diameter_mm,
                    "scale_factor_mm_per_px": scale_factor_mm_per_px,
                    "delta_rho": float(context.inputs["delta_rho"]),
                    "capture_file": sample_path,
                }
            except (KeyError, TypeError, ValueError):
                sample = None
                sample_rpm = 0.0

            if sample is not None:
                if state["sample_rpm"] != sample_rpm:
                    state["sample_rpm"] = sample_rpm
                    state["samples"] = []

                state["samples"].append(sample)

                if len(state["samples"]) == 10:
                    summary = _stage_summary_from_samples(sample_rpm, state["samples"])
                    if summary is not None and state["last_completed_rpm"] != sample_rpm:
                        row, statistics = summary
                        state["rows"].append(row)
                        stage_record = {
                            "rpm": sample_rpm,
                            "samples": [dict(item) for item in state["samples"]],
                            "statistics": statistics,
                            "summary_row": list(row),
                        }
                        history = context.session.state.setdefault(_stage_measurements_key(context), [])
                        history.append(stage_record)
                        context.runtime.gmj_stage_measurements = [dict(record) for record in history]
                        state["last_completed_rpm"] = sample_rpm

                    state["sample_rpm"] = None
                    state["samples"] = []

        if bool(context.inputs["autostop"]):
            state["s"] = "MAX_RPM_REACHED"
            return result(
                "MAX_RPM_REACHED",
                ErrorCluster(True, 68, "Maximum RPM 6000 reached. Measurement completed. Start a new run to continue."),
            )

    return result()


# ================================================================
# CAMERA CAPTURE
# ================================================================

@registry.register(
    "camera_capture_dual_mode"
)
def camera_capture_dual_mode(
    context: HandlerContext,
):

    """
    Shared Oil-live / Reference-snapshot camera handler.

    Stage measurement:
        - keep a stage request pending until actual RPM is within ±100 RPM
        - save exactly 10 images, spaced 0.4 s apart, without sleep()
        - emit one measurement event per saved image
        - show the 10th image in Picture Comparison

    Reference capture remains one manual snapshot per rising edge.
    """

    key = (
        f"camera:"
        f"{context.caller_vi or 'graph'}:"
        f"{context.graph_scope}:"
        f"{context.node.id}"
    )

    trigger = bool(context.inputs["capture_trigger"])

    state = context.session.state.setdefault(
        key,
        {
            "frame": None,
            "last_trigger": trigger,
            "capture_behavior": "live" if trigger else "snapshot",
            "initialized": False,
            "last_saved_path": None,
            "last_stage_snapshot_path": None,
            "last_auto_stage_target": None,
            "previous_run": False,
            "stage_burst": None,
        },
    )

    behavior = state["capture_behavior"]

    if behavior == "live":
        telemetry_snapshot = context.session.state.get(_telemetry_snapshot_key(context), {})
        telemetry_run = bool(telemetry_snapshot.get("run", False))
        telemetry_rpm = float(telemetry_snapshot.get("rpm", 0.0))
        telemetry_target = float(telemetry_snapshot.get("target", 0.0))

        if telemetry_run and not state["previous_run"]:
            state["last_auto_stage_target"] = None
            state["stage_burst"] = None

        if not telemetry_run:
            state["stage_burst"] = None

        # Standard Mode:
        # arm exactly one 10-photo burst for every firmware target
        # (1000, 2000, ... 6000). The request is armed as soon as the
        # target changes, while the existing burst logic still waits
        # until actual RPM is within ±100 RPM before capturing.
        if (
            telemetry_run
            and not bool(
                context.session.state.get(
                    _GRADUAL_STOP_REQUEST_KEY,
                    False,
                )
            )
            and not _manual_mode_active(
                context
            )
            and telemetry_target in (
                1000.0,
                2000.0,
                3000.0,
                4000.0,
                5000.0,
                6000.0,
            )
            and state["last_auto_stage_target"]
            != telemetry_target
        ):
            context.session.state[
                _stage_capture_key(
                    context
                )
            ] = int(
                round(
                    telemetry_target
                )
            )

            state[
                "last_auto_stage_target"
            ] = telemetry_target

        state["previous_run"] = telemetry_run

        frame = context.runtime.vision.capture_source(
            context.inputs["mode"],
            context.inputs["device_index"],
            context.inputs["network_url"],
            context.inputs["timeout_seconds"],
        )

        if frame is not None:
            state["frame"] = frame
            pending_stage = context.session.state.get(_stage_capture_key(context))

            if state["stage_burst"] is None and pending_stage is not None:
                requested_rpm = int(round(float(pending_stage)))
                target_matches = int(round(telemetry_target)) == requested_rpm
                rpm_stable = abs(telemetry_rpm - float(requested_rpm)) < 100.0

                if telemetry_run and requested_rpm > 0 and target_matches and rpm_stable:
                    context.session.state.pop(_stage_capture_key(context), None)
                    state["stage_burst"] = {
                        "rpm": requested_rpm,
                        "count": 0,
                        "next_capture_at": context.runtime.clock(),
                    }

            burst = state["stage_burst"]
            sample_event_pending = _stage_sample_event_key(context) in context.session.state

            if burst is not None and not sample_event_pending:
                now = context.runtime.clock()
                if now >= float(burst["next_capture_at"]):
                    stage_rpm = int(burst["rpm"])
                    sample_index = int(burst["count"]) + 1
                    active_session = _active_session_root(context)
                    capture_folder = (
                        session_stage_dir(active_session, stage_rpm)
                        if active_session is not None
                        else captures_dir()
                    )
                    capture_folder.mkdir(parents=True, exist_ok=True)
                    image_path = _capture_path_with_daily_sequence(
                        capture_folder,
                        f"stage_{stage_rpm}rpm",
                    )
                    context.runtime.vision.save(frame, image_path)
                    state["last_saved_path"] = str(image_path)

                    analysis_requests = getattr(
                        context.runtime,
                        "gmj_analysis_capture_requests",
                        None,
                    )

                    if not isinstance(
                        analysis_requests,
                        list,
                    ):
                        analysis_requests = []
                        context.runtime.gmj_analysis_capture_requests = (
                            analysis_requests
                        )

                    # Display-only snapshot for Picture Comparison / Grafik Kawat.
                    #
                    # IMPORTANT:
                    # The frozen reference/calibration camera remains untouched.
                    # This only prepares the exact stage sample frame and its
                    # matching intensity profile for the Front Panel display.
                    display_wire_profile = None

                    try:
                        wire_orientation = str(
                            context.controls.get(
                                "wire_orientation",
                                "vertical",
                            )
                        )

                        wire_threshold = 127.0
                        wire_foreground = "dark"

                        if (
                            context.project is not None
                            and context.caller_vi is not None
                            and context.caller_vi in context.project.vis
                        ):
                            wire_edge_node = (
                                context.project.vis[
                                    context.caller_vi
                                ].graph.nodes.get(
                                    "wire_edge"
                                )
                            )

                            if wire_edge_node is not None:
                                wire_threshold = float(
                                    wire_edge_node.properties.get(
                                        "threshold",
                                        wire_threshold,
                                    )
                                )
                                wire_foreground = str(
                                    wire_edge_node.properties.get(
                                        "foreground",
                                        wire_foreground,
                                    )
                                )

                        display_wire_result = (
                            context.runtime.vision.edge_intensity_profile(
                                frame,
                                wire_orientation,
                                wire_threshold,
                                wire_foreground,
                            )
                        )

                        profile_value = display_wire_result.get(
                            "intensity_profile"
                        )

                        if isinstance(
                            profile_value,
                            list,
                        ):
                            display_wire_profile = list(
                                profile_value
                            )

                    except (
                        KeyError,
                        RuntimeError,
                        TypeError,
                        ValueError,
                    ):
                        # Display-only enhancement must never interrupt the
                        # existing stage capture / measurement pipeline.
                        display_wire_profile = None

                    analysis_requests.append(
                        {
                            "rpm": stage_rpm,
                            "sample_index": sample_index,
                            "capture_file": str(image_path),
                            "display_frame": frame,
                            "display_wire_profile": display_wire_profile,
                        }
                    )

                    # IMPORTANT:
                    # The measurement pipeline must see the exact frame that
                    # belongs to this saved sample BEFORE the sample event is
                    # consumed by the watcher. Previously Picture Comparison
                    # was only updated on sample #10, so samples #1..#9 could
                    # be paired with stale diameter values.
                    context.session.state[
                        _stage_snapshot_frame_key(
                            context
                        )
                    ] = {
                        "frame": frame,
                        "rpm": stage_rpm,
                        "path": str(image_path),
                    }

                    context.session.state[
                        _stage_sample_event_key(
                            context
                        )
                    ] = {
                        "rpm": stage_rpm,
                        "sample_index": sample_index,
                        "path": str(image_path),
                    }

                    burst["count"] = sample_index
                    burst["next_capture_at"] = now + 0.4

                    if sample_index >= 10:
                        state["stage_burst"] = None

        state["last_trigger"] = trigger
        state["initialized"] = True
        return state["frame"]

    is_reference_calibration_camera = bool(
        context.node.properties.get(
            "reference_calibration_camera",
            False,
        )
    )

    # The calibration/reference camera must remain frozen on the operator's
    # captured reference image. Automatic stage samples must not replace it,
    # otherwise wire diameter and scale factor change during a measurement.
    if not is_reference_calibration_camera:
        stage_snapshot = context.session.state.get(
            _stage_snapshot_frame_key(context)
        )

        if stage_snapshot is not None:
            stage_path = stage_snapshot.get("path")

            if (
                stage_path
                and stage_path
                != state.get(
                    "last_stage_snapshot_path"
                )
            ):
                stage_frame = stage_snapshot.get(
                    "frame"
                )

                if stage_frame is not None:
                    state["frame"] = stage_frame
                    state["last_stage_snapshot_path"] = stage_path

    if not state["initialized"]:
        frame = context.runtime.vision.capture_source(
            context.inputs["mode"],
            context.inputs["device_index"],
            context.inputs["network_url"],
            context.inputs["timeout_seconds"],
        )
        if frame is not None:
            state["frame"] = frame
        state["initialized"] = True
        state["last_trigger"] = trigger
        return state["frame"]

    rising_edge = trigger and not bool(state["last_trigger"])

    if rising_edge:
        frame = context.runtime.vision.capture_source(
            context.inputs["mode"],
            context.inputs["device_index"],
            context.inputs["network_url"],
            context.inputs["timeout_seconds"],
        )
        if frame is not None:
            state["frame"] = frame
            active_session = _active_session_root(context)
            capture_folder = (
                session_reference_dir(active_session)
                if active_session is not None
                else captures_dir()
            )
            capture_folder.mkdir(parents=True, exist_ok=True)
            image_path = _capture_path_with_daily_sequence(capture_folder, "reference")
            context.runtime.vision.save(frame, image_path)
            state["last_saved_path"] = str(image_path)

    state["last_trigger"] = trigger
    return state["frame"]


# ================================================================
# EDGE INTENSITY PROFILE
# ================================================================

@registry.register(
    "edge_intensity_profile"
)
def edge_intensity_profile(
    context: HandlerContext,
):

    """
    Calculate grayscale edge/intensity profile.

    Includes a small per-node cache.

    This especially helps the Reference image:
    when the snapshot has not changed, its expensive profile does not
    need to be calculated again on every Continuous iteration.
    """

    context.session.token.check()

    image = context.inputs[
        "image"
    ]

    orientation = context.inputs[
        "scan_orientation"
    ]

    threshold = (
        context.node.properties.get(
            "threshold",
            127,
        )
    )

    foreground = (
        context.node.properties.get(
            "foreground",
            "dark",
        )
    )

    # ImageFrame itself stays identical for a held reference snapshot.
    #
    # Oil live camera receives a new ImageFrame object every iteration,
    # so its profile still updates normally.

    cache_key = (
        f"edge-profile:"
        f"{context.caller_vi or 'graph'}:"
        f"{context.graph_scope}:"
        f"{context.node.id}"
    )

    state = context.session.state.setdefault(
        cache_key,
        {
            "image_id": None,
            "orientation": None,
            "threshold": None,
            "foreground": None,
            "result": None,
        },
    )

    image_id = id(
        image
    )

    if (
        state["result"] is not None
        and state["image_id"]
        == image_id
        and state["orientation"]
        == orientation
        and state["threshold"]
        == threshold
        and state["foreground"]
        == foreground
    ):

        return state[
            "result"
        ]

    result = (
        context.runtime.vision.edge_intensity_profile(
            image,
            orientation,
            threshold,
            foreground,
        )
    )

    context.session.token.check()

    state[
        "image_id"
    ] = image_id

    state[
        "orientation"
    ] = orientation

    state[
        "threshold"
    ] = threshold

    state[
        "foreground"
    ] = foreground

    state[
        "result"
    ] = result

    return result


# ================================================================
# WIRE CALIBRATION
# ================================================================

@registry.register(
    "wire_calibration"
)
def wire_calibration(
    context: HandlerContext,
):

    pixels = _finite_positive(
        context.inputs[
            "diameter_px"
        ],
        "wire diameter_px",
    )

    diameter_mm = (
        _finite_positive(
            context.inputs[
                "known_wire_diameter_mm"
            ],
            "known wire diameter",
        )
    )

    return (
        diameter_mm
        / pixels
    )


# ================================================================
# PIXEL -> MM
# ================================================================

@registry.register(
    "pixel_to_mm"
)
def pixel_to_mm(
    context: HandlerContext,
):

    pixels = _finite_positive(
        context.inputs[
            "diameter_px"
        ],
        "drop diameter_px",
    )

    scale = _finite_positive(
        context.inputs[
            "scale_factor_mm_per_px"
        ],
        "scale factor",
    )

    return (
        pixels
        * scale
    )


# ================================================================
# DENSITY INPUT SELECTOR
# ================================================================

@registry.register(
    "density_input_selector"
)
def density_input_selector(
    context: HandlerContext,
):

    """
    Resolve the density difference used by the spinning-drop IFT formula.

    Manual Δρ:
        Preserve the existing workflow. The operator enters the final
        density difference directly.

    Template:
        Water  -> 1000 kg/m3
        Oil    -> 850 kg/m3
        Custom -> use the corresponding manual density field

        delta_rho = abs(density_1 - density_2)
    """

    from ..runtime import DataflowError

    mode = str(
        context.inputs[
            "mode"
        ]
    ).strip()

    if mode == "Manual Δρ":

        delta_rho = _finite_positive(
            context.inputs[
                "manual_delta_rho"
            ],
            "manual delta_rho",
        )

        return {
            "delta_rho": delta_rho,
            "density_1_effective": 0.0,
            "density_2_effective": 0.0,
        }

    if mode != "Template":

        raise DataflowError(
            "density mode must be 'Manual Δρ' or 'Template'"
        )

    templates = {
        "Water": 1000.0,
        "Oil": 850.0,
    }

    def resolve_density(
        fluid: object,
        custom_value: object,
        name: str,
    ) -> float:

        fluid_name = str(
            fluid
        ).strip()

        if fluid_name in templates:
            return templates[
                fluid_name
            ]

        if fluid_name == "Custom":
            return _finite_positive(
                custom_value,
                name,
            )

        raise DataflowError(
            f"{name} fluid must be Water, Oil, or Custom"
        )

    density_1 = resolve_density(
        context.inputs[
            "fluid_1"
        ],
        context.inputs[
            "density_1"
        ],
        "density_1",
    )

    density_2 = resolve_density(
        context.inputs[
            "fluid_2"
        ],
        context.inputs[
            "density_2"
        ],
        "density_2",
    )

    delta_rho = abs(
        density_1
        - density_2
    )

    if delta_rho <= 0.0:
        raise DataflowError(
            "density difference must be greater than zero"
        )

    return {
        "delta_rho": delta_rho,
        "density_1_effective": density_1,
        "density_2_effective": density_2,
    }


# ================================================================
# VONNEGUT IFT
# ================================================================

@registry.register(
    "vonnegut_ift"
)
def vonnegut_ift(
    context: HandlerContext,
):

    from ..runtime import DataflowError

    state_key = (
        f"vonnegut-hold:"
        f"{context.caller_vi or 'graph'}:"
        f"{context.graph_scope}:"
        f"{context.node.id}"
    )

    state = context.session.state.setdefault(
        state_key,
        {
            "last_result": None,
        },
    )

    if bool(
        context.session.state.get(
            _hold_state_key(context),
            False,
        )
    ):
        if state["last_result"] is not None:
            return state["last_result"]

    try:

        rpm = _finite_positive(
            context.inputs[
                "rpm"
            ],
            "rpm",
        )

        diameter_mm = (
            _finite_positive(
                context.inputs[
                    "diameter_mm"
                ],
                "diameter_mm",
            )
        )

        delta_rho = (
            _finite_positive(
                context.inputs[
                    "delta_rho"
                ],
                "delta_rho",
            )
        )

    except (
        DataflowError,
        TypeError,
        ValueError,
    ) as exc:

        return _ift_error(
            str(exc)
        )

    # Radius formulation:
    #
    # gamma = Δρ * ω² * R³ / 4

    radius_m = (
        diameter_mm
        / 1000.0
        / 2.0
    )

    omega = (
        2.0
        * math.pi
        * rpm
        / 60.0
    )

    omega_squared = (
        omega ** 2
    )

    radius_cubed = (
        radius_m ** 3
    )

    gamma_n_m = (
        delta_rho
        * omega_squared
        * radius_cubed
        / 4.0
    )

    result = {
        "omega_squared": omega_squared,
        "radius_cubed": radius_cubed,
        "ift_N_m": gamma_n_m,
        "ift_mN_m": (
            gamma_n_m
            * 1000.0
        ),
        "error": ErrorCluster(),
    }

    state["last_result"] = result

    return result


# ================================================================
# PYCNOMETER DENSITY
# ================================================================

@registry.register(
    "pycnometer_density"
)
def pycnometer_density(
    context: HandlerContext,
):

    empty = float(
        context.inputs[
            "bottle_weight_empty_g"
        ]
    )

    gross = float(
        context.inputs[
            "bottle_weight_gross_g"
        ]
    )

    volume = _finite_positive(
        context.inputs[
            "volume_ml"
        ],
        "volume_ml",
    )

    if (
        not math.isfinite(
            empty
        )
        or not math.isfinite(
            gross
        )
        or gross <= empty
    ):

        from ..runtime import DataflowError

        raise DataflowError(
            "gross bottle weight must be finite "
            "and greater than empty bottle weight"
        )

    density_g_ml = (
        gross
        - empty
    ) / volume

    return {
        "density_g_ml": (
            density_g_ml
        ),
        "density_kg_m3": (
            density_g_ml
            * 1000.0
        ),
    }


# ================================================================
# DELTA DENSITY
# ================================================================

@registry.register(
    "delta_density"
)
def delta_density(
    context: HandlerContext,
):

    first = float(
        context.inputs[
            "density_1"
        ]
    )

    second = float(
        context.inputs[
            "density_2"
        ]
    )

    if (
        not math.isfinite(
            first
        )
        or not math.isfinite(
            second
        )
        or first <= 0
        or second <= 0
    ):

        from ..runtime import DataflowError

        raise DataflowError(
            "densities must be finite "
            "and greater than zero"
        )

    return abs(
        first
        - second
    )