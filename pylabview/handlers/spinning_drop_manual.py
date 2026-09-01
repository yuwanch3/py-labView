from __future__ import annotations

import math
import re

from ..execution import CancelledError
from ..typesystem import ErrorCluster
from .api import HandlerContext
from .registry import BUILTIN_HANDLERS as registry


_TELEMETRY = re.compile(
    r"RPM:(\d+);PWM:(\d+);TIME:(\d+(?:\.\d+)?);TARGET:(\d+)"
)

_TARGET_REACHED = re.compile(
    r"TARGET_REACHED:(\d+)"
)


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


def _telemetry_snapshot_key(
    context: HandlerContext,
) -> str:
    return (
        f"spinning-drop-telemetry-snapshot:"
        f"{context.caller_vi or 'graph'}:"
        f"{context.graph_scope}"
    )


@registry.register("arduino_manual_rpm_reader")
def arduino_manual_rpm_reader(
    context: HandlerContext,
):
    """
    Manual-RPM serial controller with explicit Arduino handshake.

    Important for Arduino UNO:
    opening the serial port can reset the board. Therefore Manual mode
    is NOT considered active merely because MODE:MANUAL was written.

    START is allowed only after:
        1. ACK:MODE_MANUAL
        2. ACK:TARGET:<requested rpm>

    Commands are retried while waiting for their ACK, so a command lost
    during the UNO reset/boot window cannot silently fall back to the
    firmware's default Standard mode.

    PC -> Arduino:
        MODE:MANUAL
        SET_TARGET:<rpm>
        START
        STOP

    Arduino -> PC:
        ACK:MODE_MANUAL
        ACK:TARGET:<rpm>
        ACK:START
        ACK:STOP
        TARGET_REACHED:<rpm>
        RPM:<int>;PWM:<int>;TIME:<float>;TARGET:<int>

    PWM is never commanded by the PC. PID and soft-ramp remain on Arduino.
    """

    connection = None

    state_key = (
        f"manual-telemetry:"
        f"{context.caller_vi or 'graph'}:"
        f"{context.graph_scope}:"
        f"{context.node.id}"
    )

    state = context.session.state.setdefault(
        state_key,
        {
            "mode_confirmed": False,
            "mode_last_sent": None,
            "target_confirmed": None,
            "target_last_sent": None,
            "requested_target": None,
            "running": False,
            "start_pending": False,
            "rpm": 0.0,
            "pwm": 0.0,
            "elapsed": 0.0,
            "target": 0.0,
            "target_reached_latched": None,
        },
    )

    try:
        run = bool(
            context.inputs["run"]
        )

        requested_target = float(
            context.inputs["target_rpm"]
        )

        if (
            not math.isfinite(requested_target)
            or requested_target < 0.0
            or requested_target > 6000.0
        ):
            raise ValueError(
                "Manual Target RPM must be between 0 and 6000"
            )

        if run and requested_target <= 0.0:
            raise ValueError(
                "Manual Target RPM must be greater than 0 before START"
            )

        rounded_target = int(
            round(
                requested_target
            )
        )

        # A new requested target requires a fresh target ACK.
        if state["requested_target"] != rounded_target:
            state["requested_target"] = rounded_target
            state["target_confirmed"] = None
            state["target_last_sent"] = None
            state["target_reached_latched"] = None

        context.session.state[
            _hold_state_key(context)
        ] = not run

        maximum = int(
            context.node.properties.get(
                "response_bytes",
                4096,
            )
        )

        max_lines = int(
            context.node.properties.get(
                "max_lines",
                32,
            )
        )

        if maximum < 32 or maximum > 65536:
            raise ValueError(
                "Arduino response_bytes must be between 32 and 65536"
            )

        if max_lines < 1 or max_lines > 256:
            raise ValueError(
                "Arduino max_lines must be between 1 and 256"
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
                                9600,
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

        connection = context.session.resources.get(
            connection_ref,
            "serial",
        )

        cancel_key = (
            f"arduino-manual-safe-stop:"
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
        # FIRST: DRAIN AND PARSE ARDUINO RESPONSES
        # ========================================================

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

            match = _TELEMETRY.fullmatch(
                text
            )

            if match:
                # Preserve the last displayed measurement after STOP.
                if not run:
                    continue

                state["rpm"] = float(
                    match.group(1)
                )
                state["pwm"] = float(
                    match.group(2)
                )
                state["elapsed"] = float(
                    match.group(3)
                )
                state["target"] = float(
                    match.group(4)
                )
                continue

            match = _TARGET_REACHED.fullmatch(
                text
            )

            if match:
                reached = int(
                    match.group(1)
                )

                state["target"] = float(
                    reached
                )

                # Latch the event instead of exposing it for only one
                # graph iteration. The Manual watcher deduplicates rows,
                # so this also survives an unrelated camera/vision error.
                state[
                    "target_reached_latched"
                ] = reached

                context.session.state[
                    _stage_capture_key(context)
                ] = reached

                continue

            if text == "ACK:MODE_MANUAL":
                state["mode_confirmed"] = True
                continue

            if text.startswith("ACK:TARGET:"):
                try:
                    acknowledged_target = int(
                        text.split(
                            ":",
                            2,
                        )[2]
                    )
                except ValueError:
                    continue

                if acknowledged_target == rounded_target:
                    state[
                        "target_confirmed"
                    ] = acknowledged_target

                continue

            if text == "ACK:START":
                state["start_pending"] = False
                state["running"] = True
                continue

            if text == "ACK:STOP":
                state["running"] = False
                state["start_pending"] = False
                continue

        context.session.token.check()

        # ========================================================
        # HANDSHAKE / COMMAND RETRY
        # ========================================================

        now = context.runtime.clock()
        retry_seconds = 1.0

        def ready_to_retry(
            timestamp: object,
        ) -> bool:
            return (
                timestamp is None
                or now - float(timestamp)
                >= retry_seconds
            )

        # Arduino UNO can reset when COM opens. Keep retrying MODE
        # until the board explicitly confirms Manual mode.
        if (
            not state["mode_confirmed"]
            and ready_to_retry(
                state["mode_last_sent"]
            )
        ):
            command = b"MODE:MANUAL\n"

            if int(
                connection.write(
                    command
                )
            ) != len(command):
                raise OSError(
                    "incomplete MODE:MANUAL command write"
                )

            state["mode_last_sent"] = now

        # Never send SET_TARGET before Manual mode is confirmed.
        if (
            state["mode_confirmed"]
            and state["target_confirmed"]
            != rounded_target
            and rounded_target > 0
            and ready_to_retry(
                state["target_last_sent"]
            )
        ):
            command = (
                f"SET_TARGET:{rounded_target}\n"
            ).encode(
                "ascii"
            )

            if int(
                connection.write(
                    command
                )
            ) != len(command):
                raise OSError(
                    "incomplete SET_TARGET command write"
                )

            state["target_last_sent"] = now

        # START is intentionally gated by BOTH ACKs.
        if (
            run
            and state["mode_confirmed"]
            and state["target_confirmed"]
            == rounded_target
            and not state["running"]
            and not state["start_pending"]
        ):
            command = b"START\n"

            if int(
                connection.write(
                    command
                )
            ) != len(command):
                raise OSError(
                    "incomplete START command write"
                )

            state["start_pending"] = True

        if (
            not run
            and (
                state["running"]
                or state["start_pending"]
            )
        ):
            command = b"STOP\n"

            if int(
                connection.write(
                    command
                )
            ) != len(command):
                raise OSError(
                    "incomplete STOP command write"
                )

            state["running"] = False
            state["start_pending"] = False

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

        target_reached = (
            state["target_reached_latched"]
            == rounded_target
            and rounded_target > 0
        )

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
            "target_reached": target_reached,
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
            "target_reached": False,
            "error": ErrorCluster(
                True,
                70,
                str(exc),
            ),
        }


@registry.register("spinning_drop_manual_watcher")
def spinning_drop_manual_watcher(
    context: HandlerContext,
):
    """
    Manual-mode Measurement Log builder.

    One row is appended once the Arduino emits TARGET_REACHED:<rpm>.
    Starting a new Manual run resets the table, matching Standard mode.
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

    measured = (
        "diameter_px",
        "diameter_mm",
        "delta_rho",
        "omega_squared",
        "radius_cubed",
        "ift_N_m",
        "ift_mN_m",
    )

    state_key = (
        f"manual-stage-watcher:"
        f"{context.caller_vi or 'graph'}:"
        f"{context.graph_scope}:"
        f"{context.node.id}"
    )

    state = context.session.state.setdefault(
        state_key,
        {
            "running": False,
            "rows": [],
            "last_logged_target": None,
        },
    )

    def result(
        state_label: str,
        error: ErrorCluster | None = None,
    ):
        return {
            "table_data": [
                headers,
                *state["rows"],
            ],
            "state": state_label,
            "error": (
                error
                if error is not None
                else ErrorCluster()
            ),
        }

    run = bool(
        context.inputs["run"]
    )

    if not run:
        state["running"] = False
        return result(
            "IDLE"
        )

    if context.inputs["error"].status:
        return result(
            "ERROR",
            ErrorCluster(
                True,
                71,
                "manual serial fault: watcher halted "
                f"({context.inputs['error'].source})",
            ),
        )

    if bool(
        context.inputs["stalled"]
    ):
        return result(
            "ERROR",
            ErrorCluster(
                True,
                72,
                "RPM stall detected: manual watcher halted",
            ),
        )

    if not state["running"]:
        state["running"] = True
        state["rows"] = []
        state["last_logged_target"] = None

    if bool(
        context.inputs["target_reached"]
    ):
        completed_rpm = float(
            context.inputs[
                "current_target_rpm"
            ]
        )

        if (
            completed_rpm > 0.0
            and completed_rpm
            != state[
                "last_logged_target"
            ]
        ):
            row = [
                completed_rpm
            ] + [
                float(
                    context.inputs[
                        port
                    ]
                )
                for port
                in measured
            ]

            if all(
                math.isfinite(
                    value
                )
                for value
                in row
            ):
                state["rows"].append(
                    row
                )
                state[
                    "last_logged_target"
                ] = completed_rpm

    return result(
        "RUNNING"
    )
