# Arsitektur PyLabView Studio 7.8.3

## Boundaries

- `model.py`, `typesystem.py`, `persistence.py`: strict schema v3, graph types, and atomic project persistence.

- `execution.py`, `resources.py`, `runtime.py`: desktop CPython dataflow scheduler, cooperative cancellation, and session-owned handles. `DataflowRuntime` honors an explicitly supplied `data_root`; otherwise its writable runtime root defaults to the user data directory provided by `paths.py`, rather than the process working directory.

- `paths.py`: resolves bundled application resources separately from writable user data. In source mode, bundled resources resolve from the project root; in frozen mode they resolve from the PyInstaller bundle root. Writable application data is stored beneath `Documents\GMJ PyLabView`, including `Captures`, `Measurement Exports`, `Examples`, and `Projects`. Default Standard and Manual example projects are copied to the user Examples directory only when missing and never overwrite existing user files.

- `startup_screen.py`, `app.py`: startup presentation and operating-mode selection. The user selects Standard Mode or Manual RPM Mode before the corresponding bundled project is loaded. Startup logo and example-project lookup use bundled resource helpers so the same path model works in source and frozen builds.

- `handlers/`: typed `HandlerContext`, `NodeHandler` protocol, duplicate-safe registry, and category modules for all built-in node behavior. `DataflowRuntime._evaluate` resolves one handler and invokes it; it does not dispatch on node type.

- `handlers/spinning_drop.py`: Standard Mode domain handlers for passive Arduino telemetry listening, START/STOP commands, ACK handling, `RPM:;PWM:;TIME:;TARGET:` telemetry, and `TARGET_RPM:` stage events parsed tolerantly from one stream. It also provides the PC-side RPM stall watchdog, event-driven stage-watcher table building, wire calibration, radius-form Vonnegut IFT, pycnometer/delta-density calculators, automatic stage capture, and reference/image behavior. Standard RPM sequencing 1000 → 2000 → 3000 → 4000 → 5000 → 6000 and its timing remain owned by the Arduino firmware; the PC never sends PWM values.

- `handlers/spinning_drop_manual.py`: Manual RPM Mode domain handlers. The PC selects Manual Mode and sends the requested target RPM, while PWM remains controlled by the Arduino PID. The handler consumes the same bounded serial telemetry stream and the `TARGET_REACHED:<rpm>` event. Manual measurement rows are captured when the requested final target is reached; intermediate soft-ramp targets are not recorded as measurement stages.

- The dual-mode Arduino protocol uses `MODE:STANDARD`, `MODE:MANUAL`, `SET_TARGET:<rpm>`, `START`, and `STOP` commands. Manual operation is bounded to 6000 RPM. Standard automatic sequencing and Manual target operation remain separate workflows while sharing telemetry and safety-oriented stop behavior.

- `camera_capture_dual_mode` is trigger-held per node: the oil image can remain live while the staged reference/comparison node only re-captures on its operator action and otherwise preserves the previous frame. Capture Reference is momentary from the operator perspective: one activation captures/updates the reference and then returns to the inactive state. Error clusters remain explicit wires; invalid measurements cannot reach report generation.

- `protocols.py`: bounded stdlib TCP/UDP and Modbus TCP FC01/02/03/04/05/06/15/16; pyserial loader remains compatibility API.

- `integrations/`: optional capability/diagnostic, NI-DAQmx, VISA, OPC UA, vision, report, and plugin process adapters. Constructors accept backend injection and do not import optional packages at core startup.

- `hdl.py`: validated combinational graph-to-Verilog subset and optional bounded Yosys syntax subprocess.

- `targets.py`: bounded external target manifest/handshake. A response is reported honestly and never upgrades desktop execution into hard RT.

- `front_panel.py`, `canvas_editor.py`, `app.py`: Tk presentation. Runtime workers never call Tk.

- `front_panel.py` renders persisted start/stop controls, bounded gauges, dropdown metadata, intensity-chart axis labels, compact tabular indicators, Manual RPM controls where present, and the bottom STOP control used by the spinning-drop projects; computation remains in graph nodes.

- `app.py` owns application-level run/stop presentation behavior, measurement export, and mode-aware UI integration. Stop Continuous stops the measurement/motor run while preserving the intended live-camera workflow; Global Stop, including the bottom front-panel STOP control, stops the active motor/controller/runtime path consistently in Standard and Manual modes.

## Lifecycle And Bounds

`RunSession` owns a `ResourceManager`. Its worker `finally` is the sole cleanup owner; cancellation never closes vendor handles concurrently from the UI thread. VISA, serial, and OPC UA wrappers serialize operations and close. Non-interruptible vendor calls can delay cancellation until their configured timeout. NI operations create one task, configure channels/timing, perform one bounded operation, and close in `finally`. Camera capture similarly releases its device after one frame where single-frame capture is used. Report output uses a temporary file and `os.replace`.

Network operations cap one call at 16 MiB and 300 seconds. Serial requests and VISA writes use the same payload ceiling; VISA response size is checked after PyVISA returns and is not a pre-allocation bound. NI samples cap at 1,000,000 and rate at 10 MHz (software guard only, not hardware capability). Images validate shape, dtype, decoded memory metadata, and cap at 100 million pixels, but OpenCV decode allocation occurs before those metadata checks. Reports cap at 100,000 rows and 1 million cells.

Writable application paths resolve beneath the configured runtime/user data root. This canonical path handling separates user-generated data from bundled application resources; it is not an adversarial filesystem sandbox.

## Optionality

Missing packages produce explicit unavailable capabilities or runtime node errors. Project loading only needs node definitions and never imports vendor APIs. Diagnostics software probing is side-effect-light; NI device and VISA resource enumeration occur only when the user presses Refresh Hardware.

Process-isolated plugin evaluators exchange bounded JSON with request IDs. They can contain crashes and enforce a parent timeout, but child code retains the user's OS permissions and therefore is not a security sandbox.

The Windows release uses the full optional instrumentation profile. Python dependencies required by that profile are bundled into the frozen application where supported, but external vendor runtimes/drivers such as NI-DAQmx and the selected VISA backend remain separate system dependencies.

## Handler Registry And Extensions

Importing `pylabview.handlers` loads the category modules and populates the default built-in mapping from node type to handler. The frozen-build spec explicitly includes dynamically imported handler modules, including the Standard and Manual spinning-drop handlers. Registry registration fails on duplicates, and `HandlerRegistry.audit` compares the mapping with `NODE_DEFINITIONS`.

`DataflowRuntime` also accepts explicit handler and plugin registries so tests and embedding applications can assemble or replace dispatch without mutating global state. Handlers receive runtime services, node, normalized inputs, controls, logs, project/caller identity, session, and graph scope through one immutable context object.

Built-in definitions must have an explicit registered handler. A type absent from the built-in registry crosses the plugin boundary: the runtime first checks an isolated evaluator, then a trusted in-process evaluator, and otherwise reports an unknown node. Plugin output normalization remains owned by the runtime scheduler, so single-output and multi-output behavior share the same path as built-ins.

## Persistence

Application release 7.8.3 deliberately keeps project schema version 3. New behavior is represented by node types, properties, handlers, and root/panel extension points, so no schema migration is required for the 7.8.3 application release.

V1/v2 projects continue to migrate to schema v3, and existing schema-v3 projects remain the persisted project format.

The bundled spinning-drop examples are:

- `examples/spinning_drop_ift.json` for Standard Mode.
- `examples/spinning_drop_manual_ift.json` for Manual RPM Mode.

At application startup, missing default examples may be copied to the user's `Documents\GMJ PyLabView\Examples` directory. Existing user copies are preserved.

## Frozen Windows Build

The full Windows build uses `PyLabViewStudioFull.spec` as the packaging profile and produces the single release executable:

`PyLabViewStudio.exe`

The spec includes application assets, bundled examples, documentation, and the optional instrumentation dependency profile required by the full release.

The release workflow performs source unit tests, core/full self-tests, optional Yosys validation where available, the PyInstaller build, a frozen executable self-test, and SHA-256 checksum generation.

The release artifact set is intentionally limited to:

- `PyLabViewStudio.exe`
- `PyLabViewStudio.exe.sha256`

Build success, software self-tests, and syntax validation do not constitute physical hardware qualification, hard real-time certification, safety certification, or FPGA timing closure.
