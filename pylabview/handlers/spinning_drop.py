

import math
import re

from datetime import datetime

from ..execution import CancelledError
from ..paths import captures_dir
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
        },
    )

    try:

        run = bool(
            context.inputs["run"]
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
                    previous_target >= 6000.0
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
                # The firmware normally emits a dedicated
                # TARGET_RPM:<rpm> line on every stage change.
                if (
                    previous_target > 0.0
                    and new_target > 0.0
                    and new_target != previous_target
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

    All stage timing belongs to Arduino firmware.
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
        },
    )

    def result(
        state_label: str | None = None,
        error: ErrorCluster | None = None,
    ) -> dict[str, object]:

        return {
            "table_data": [
                headers,
                *state["rows"],
            ],
            "state": (
                state_label
                or state["s"]
            ),
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

        state.update(
            {
                "s": "IDLE",
                "last_target": None,
            }
        )

        return result()

    if (
        context.inputs[
            "error"
        ].status
    ):

        state["s"] = "ERROR"

        return result(
            "ERROR",
            ErrorCluster(
                True,
                66,
                "serial fault: watcher halted "
                f"({context.inputs['error'].source})",
            ),
        )

    if bool(
        context.inputs["stalled"]
    ):

        state["s"] = "ERROR"

        return result(
            "ERROR",
            ErrorCluster(
                True,
                67,
                "RPM stall detected: watcher halted",
            ),
        )

    if state["s"] == "MAX_RPM_REACHED":

        return result(
            "MAX_RPM_REACHED",
            ErrorCluster(
                True,
                68,
                "Maximum RPM 6000 reached. "
                "Measurement completed. "
                "Start a new run to continue.",
            ),
        )

    if state["s"] == "IDLE":

        state["s"] = "RUNNING"

        # New measurement run starts with a fresh table.
        state["rows"] = []

        # Arduino immediately starts at 1000 RPM.
        state["last_target"] = 1000.0

    if state["s"] == "RUNNING":

        def snapshot(
            completed_rpm: float,
        ) -> list[float]:

            row = [
                float(
                    completed_rpm
                )
            ] + [
                float(
                    context.inputs[port]
                )
                for port
                in measured
            ]

            return (
                row
                if all(
                    math.isfinite(value)
                    for value
                    in row
                )
                else []
            )

        if bool(
            context.inputs[
                "stage_changed"
            ]
        ):

            new_target = float(
                context.inputs[
                    "current_target_rpm"
                ]
            )

            if (
                state[
                    "last_target"
                ]
                is not None
            ):

                row = snapshot(
                    float(
                        state[
                            "last_target"
                        ]
                    )
                )

                if row:
                    state["rows"].append(
                        row
                    )

            state[
                "last_target"
            ] = new_target

            # Request ONE automatic Picture Oil snapshot when the
            # Arduino enters a new 1000-RPM stage.
            #
            # Example:
            # 1000 -> 2000  => save stage_2000rpm_....jpg
            # 2000 -> 3000  => save stage_3000rpm_....jpg
            if new_target > 0.0:
                context.session.state[
                    _stage_capture_key(context)
                ] = int(
                    round(new_target)
                )

        if bool(
            context.inputs[
                "autostop"
            ]
        ):

            if (
                state[
                    "last_target"
                ]
                is not None
            ):

                row = snapshot(
                    float(
                        state[
                            "last_target"
                        ]
                    )
                )

                if row:
                    state["rows"].append(
                        row
                    )

            state["s"] = (
                "MAX_RPM_REACHED"
            )

            return result(
                "MAX_RPM_REACHED",
                ErrorCluster(
                    True,
                    68,
                    "Maximum RPM 6000 reached. "
                    "Measurement completed. "
                    "Start a new run to continue.",
                ),
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
    Shared handler for Oil live camera and Reference snapshot camera.

    Behaviour is determined automatically from the INITIAL trigger state.

    Oil:
        capture_trigger starts True.
        This node becomes LIVE and grabs the latest cached camera frame
        every graph iteration.

    Reference:
        capture_trigger starts False.
        This node becomes SNAPSHOT mode.

        On first execution it grabs one bootstrap frame so downstream
        image-processing nodes never receive None.

        After that it updates ONLY on a rising edge:
            False -> True

        Holding the button True does NOT continuously re-capture.

        When the trigger returns False, the last captured reference
        frame remains available.

    Additional behaviour:
        Every new Reference snapshot captured by the operator is also
        saved automatically into:

            Documents/GMJ PyLabView/Captures/

        Example filename:

            reference_20260826_162500_123456.jpg
    """

    key = (
        f"camera:"
        f"{context.caller_vi or 'graph'}:"
        f"{context.graph_scope}:"
        f"{context.node.id}"
    )

    trigger = bool(
        context.inputs[
            "capture_trigger"
        ]
    )

    state = context.session.state.setdefault(
        key,
        {
            "frame": None,
            "last_trigger": trigger,
            "capture_behavior": (
                "live"
                if trigger
                else "snapshot"
            ),
            "initialized": False,
            "last_saved_path": None,
            "last_stage_snapshot_path": None,
            "initial_1000_capture_done": False,
            "previous_run": False,
        },
    )

    behavior = state[
        "capture_behavior"
    ]

    # ============================================================
    # LIVE MODE
    # Used by Picture Oil
    # ============================================================

    if behavior == "live":

        telemetry_snapshot = context.session.state.get(
            _telemetry_snapshot_key(context),
            {}
        )

        telemetry_run = bool(
            telemetry_snapshot.get(
                "run",
                False,
            )
        )

        telemetry_rpm = float(
            telemetry_snapshot.get(
                "rpm",
                0.0,
            )
        )

        telemetry_target = float(
            telemetry_snapshot.get(
                "target",
                0.0,
            )
        )

        # New measurement run:
        # allow one fresh automatic capture for the first 1000-RPM stage.
        if (
            telemetry_run
            and not state["previous_run"]
        ):
            state[
                "initial_1000_capture_done"
            ] = False

        # Initial 1000-RPM stage does not have a previous stage transition,
        # so request its snapshot once actual RPM has reached the same
        # stability band already used by the Arduino firmware: ±100 RPM.
        if (
            telemetry_run
            and not state[
                "initial_1000_capture_done"
            ]
            and telemetry_target == 1000.0
            and abs(
                telemetry_rpm
                - telemetry_target
            ) < 100.0
        ):
            context.session.state[
                _stage_capture_key(context)
            ] = 1000

            state[
                "initial_1000_capture_done"
            ] = True

        state["previous_run"] = telemetry_run

        frame = (
            context.runtime.vision.capture_source(
                context.inputs["mode"],
                context.inputs[
                    "device_index"
                ],
                context.inputs[
                    "network_url"
                ],
                context.inputs[
                    "timeout_seconds"
                ],
            )
        )

        if frame is not None:

            state["frame"] = frame

            # ----------------------------------------------------
            # AUTO SNAPSHOT ON RPM STAGE CHANGE
            # ----------------------------------------------------
            stage_rpm = context.session.state.pop(
                _stage_capture_key(context),
                None,
            )

            if stage_rpm is not None:

                capture_folder = (
                    captures_dir()
                )

                capture_folder.mkdir(
                    parents=True,
                    exist_ok=True,
                )

                timestamp = (
                    datetime.now()
                    .strftime(
                        "%Y%m%d_%H%M%S_%f"
                    )
                )

                image_path = (
                    capture_folder
                    / (
                        f"stage_"
                        f"{int(stage_rpm)}rpm_"
                        f"{timestamp}.jpg"
                    )
                )

                context.runtime.vision.save(
                    frame,
                    image_path,
                )

                state[
                    "last_saved_path"
                ] = str(
                    image_path
                )

                # Make the exact same automatic stage snapshot
                # available to Picture Comparison.
                context.session.state[
                    _stage_snapshot_frame_key(context)
                ] = {
                    "frame": frame,
                    "rpm": int(
                        stage_rpm
                    ),
                    "path": str(
                        image_path
                    ),
                }

        state["last_trigger"] = trigger
        state["initialized"] = True

        return state["frame"]

    # ============================================================
    # SNAPSHOT MODE
    # Used by Picture Comparison / Reference
    # ============================================================

    # ------------------------------------------------------------
    # SHOW LATEST AUTOMATIC STAGE SNAPSHOT
    #
    # Picture Oil remains live.
    # Picture Comparison updates only when a new automatic stage
    # snapshot is created, or when the operator manually captures
    # a new Reference image.
    # ------------------------------------------------------------

    stage_snapshot = context.session.state.get(
        _stage_snapshot_frame_key(context)
    )

    if stage_snapshot is not None:

        stage_path = stage_snapshot.get(
            "path"
        )

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

                state[
                    "last_stage_snapshot_path"
                ] = stage_path

    # ------------------------------------------------------------
    # Bootstrap one valid frame.
    #
    # Important:
    # Bootstrap frame is NOT saved to disk.
    #
    # We only save when operator explicitly presses
    # Capture Reference.
    # ------------------------------------------------------------

    if not state["initialized"]:

        frame = (
            context.runtime.vision.capture_source(
                context.inputs["mode"],
                context.inputs[
                    "device_index"
                ],
                context.inputs[
                    "network_url"
                ],
                context.inputs[
                    "timeout_seconds"
                ],
            )
        )

        if frame is not None:

            state["frame"] = frame

        state["initialized"] = True

        # Keep current trigger as reference for edge detection.
        state["last_trigger"] = trigger

        return state["frame"]

    # ============================================================
    # Detect button rising edge
    #
    # False -> True = take ONE reference snapshot.
    # ============================================================

    rising_edge = (
        trigger
        and not bool(
            state[
                "last_trigger"
            ]
        )
    )

    if rising_edge:

        frame = (
            context.runtime.vision.capture_source(
                context.inputs["mode"],
                context.inputs[
                    "device_index"
                ],
                context.inputs[
                    "network_url"
                ],
                context.inputs[
                    "timeout_seconds"
                ],
            )
        )

        if frame is not None:

            # ====================================================
            # HOLD REFERENCE FRAME
            # ====================================================

            state["frame"] = frame

            # ====================================================
            # SAVE REFERENCE PHOTO
            # ====================================================

            capture_folder = (
                captures_dir()
            )

            capture_folder.mkdir(
                parents=True,
                exist_ok=True,
            )

            timestamp = (
                datetime.now()
                .strftime(
                    "%Y%m%d_%H%M%S_%f"
                )
            )

            image_path = (
                capture_folder
                / (
                    f"reference_"
                    f"{timestamp}.jpg"
                )
            )

            context.runtime.vision.save(
                frame,
                image_path,
            )

            state[
                "last_saved_path"
            ] = str(
                image_path
            )

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