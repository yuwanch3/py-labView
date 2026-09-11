# Arsitektur PyLabView Studio 8.0.0

## Boundaries

- `model.py`, `typesystem.py`, `persistence.py`: strict schema v3, graph types, and atomic project persistence.

- `execution.py`, `resources.py`, `runtime.py`: desktop CPython dataflow scheduler, cooperative cancellation, and session-owned handles. `DataflowRuntime` honors an explicitly supplied `data_root`; otherwise its writable runtime root defaults to the user data directory provided by `paths.py`, rather than the process working directory.

- `paths.py`: resolves bundled application resources separately from writable user data. In source mode, bundled resources resolve from the project root; in frozen mode they resolve from the PyInstaller bundle root. Writable application data is stored beneath `Documents\GMJ PyLabView`. Release 8.0.0 creates the top-level `Examples`, `Projects`, and `Sessions` directories. Legacy top-level `Captures` and `Measurement Exports` are no longer created by the spinning-drop workflow.

- `startup_screen.py`, `app.py`: startup presentation and operating-mode selection. The user selects Standard Mode or Manual RPM Mode before the corresponding bundled project is loaded. Startup logo and example-project lookup use bundled resource helpers so the same path model works in source and frozen builds.

- `app.py` owns the application-session lifecycle. One successful startup mode selection creates one folder:
  `Sessions\Session_YYYYMMDD_HHMMSS_Standard|Manual`.
  The session contains `Captures\Reference`, `Captures\Stages`, `Captures\Analysis`, `Measurements`, and `Session_Info.json`. Individual RPM subfolders are created on demand.

- `app.py` also owns the Analysis PNG background queue/worker. The UI thread freezes the Analysis data associated with a stage sample, then a background worker performs off-screen rendering and PNG write so Tkinter refresh is not blocked by image generation.

- `handlers/`: typed `HandlerContext`, `NodeHandler` protocol, duplicate-safe registry, and category modules for all built-in node behavior. `DataflowRuntime._evaluate` resolves one handler and invokes it; it does not dispatch on node type.

- `handlers/spinning_drop.py`: Standard Mode domain handlers for passive Arduino telemetry listening, START/STOP commands, ACK handling, `RPM:;PWM:;TIME:;TARGET:` telemetry, and `TARGET_RPM:` stage events parsed tolerantly from one stream. It also provides the PC-side RPM stall watchdog, event-driven stage-watcher table building, wire calibration, radius-form Vonnegut IFT, pycnometer/delta-density calculators, automatic 10-sample stage capture, reference/image behavior, and the shared stage-sample mechanism used by Manual Mode.

- `handlers/spinning_drop_manual.py`: Manual RPM Mode domain handlers. The PC selects Manual Mode and sends the requested target RPM, while PWM remains controlled by the Arduino PID. The handler consumes the same bounded serial telemetry stream and the `TARGET_REACHED:<rpm>` event. Manual measurement rows are published only after the shared 10-sample stage batch is complete.

- The dual-mode Arduino protocol uses `MODE:STANDARD`, `MODE:MANUAL`, `SET_TARGET:<rpm>`, `START`, `SOFT_STOP`, and `STOP` commands. `SOFT_STOP` performs firmware-side gradual deceleration for Stop Bertahap, while `STOP` remains the immediate hard-stop command and takes precedence. Manual operation is bounded to 6000 RPM. Standard automatic sequencing and Manual target operation remain separate workflows while sharing telemetry and safety-oriented stop behavior.

- `camera_capture_dual_mode` is trigger-held per node: Picture Oil remains live, while the reference/calibration camera captures only through the operator Capture Reference action and otherwise preserves the calibration frame. During a stage burst, Picture Comparison and Grafik Kawat may display the current stage sample through the application display-only path without replacing the frozen reference used for scale calibration.

- The frozen wire reference determines `wire_calibration` / scale factor. Automatic stage sample frames must not replace that calibration source. This separates measurement visualization from calibration state.

- For each accepted stage/Manual target, 10 raw stage images are captured at the existing sample interval. Each sample is paired with an Analysis request containing the corresponding display/analysis state. Analysis snapshots are stored separately from raw stage images.

- `front_panel.py`: Tk presentation plus the off-screen Analysis renderer. `freeze_analysis_snapshot()` copies only the values/chart data needed by the Analysis image. Rendering uses that frozen data rather than reading later live UI state.

- `protocols.py`: bounded stdlib TCP/UDP and Modbus TCP FC01/02/03/04/05/06/15/16; pyserial loader remains compatibility API.

- `integrations/`: optional capability/diagnostic, NI-DAQmx, VISA, OPC UA, vision, report, and plugin process adapters. Constructors accept backend injection and do not import optional packages at core startup.

- `hdl.py`: validated combinational graph-to-Verilog subset and optional bounded Yosys syntax subprocess.

- `targets.py`: bounded external target manifest/handshake. A response is reported honestly and never upgrades desktop execution into hard RT.

- `front_panel.py`, `canvas_editor.py`, `app.py`: Tk presentation. Runtime workers never call Tk directly.

- `app.py` owns application-level run/stop presentation behavior, session-based measurement export, and mode-aware UI integration. Stop Continuous stops the measurement/motor run while preserving the intended live-camera workflow; Global Stop, including the bottom front-panel STOP control, stops the active motor/controller/runtime path consistently in Standard and Manual modes.

## Lifecycle And Bounds

`RunSession` owns a `ResourceManager`. Its worker `finally` is the sole cleanup owner; cancellation never closes vendor handles concurrently from the UI thread. VISA, serial, and OPC UA wrappers serialize operations and close. Non-interruptible vendor calls can delay cancellation until their configured timeout.

Camera/network capture keeps the latest available frame for network sources to reduce stale-buffer behavior. Spinning-drop stage capture uses the exact frame associated with the saved sample before publishing the corresponding measurement event.

The Analysis export path is noncritical to motor/runtime control. Frozen Analysis payloads are queued for background rendering so GDI drawing, PNG compression, and file output do not hold the Tkinter refresh path.

Network operations cap one call at 16 MiB and 300 seconds. Serial requests and VISA writes use the same payload ceiling; VISA response size is checked after PyVISA returns and is not a pre-allocation bound. NI samples cap at 1,000,000 and rate at 10 MHz (software guard only, not hardware capability). Images validate shape, dtype, decoded memory metadata, and cap at 100 million pixels, but OpenCV decode allocation occurs before those metadata checks. Reports cap at 100,000 rows and 1 million cells.

Writable application paths resolve beneath the configured runtime/user data root. Bundled application resources remain separate from user-generated session data.

## Optionality

Missing packages produce explicit unavailable capabilities or runtime node errors. Project loading only needs node definitions and never imports vendor APIs. Diagnostics software probing is side-effect-light; NI device and VISA resource enumeration occur only when the user presses Refresh Hardware.

Process-isolated plugin evaluators exchange bounded JSON with request IDs. They can contain crashes and enforce a parent timeout, but child code retains the user's OS permissions and therefore is not a security sandbox.

The Windows release uses the full optional instrumentation profile. Python dependencies required by that profile are bundled into the frozen application where supported, but external vendor runtimes/drivers such as NI-DAQmx and the selected VISA backend remain separate system dependencies.

## Handler Registry And Extensions

Importing `pylabview.handlers` loads the category modules and populates the default built-in mapping from node type to handler. The frozen-build spec explicitly includes dynamically imported handler modules, including the Standard and Manual spinning-drop handlers. Registry registration fails on duplicates, and `HandlerRegistry.audit` compares the mapping with `NODE_DEFINITIONS`.

`DataflowRuntime` also accepts explicit handler and plugin registries so tests and embedding applications can assemble or replace dispatch without mutating global state. Handlers receive runtime services, node, normalized inputs, controls, logs, project/caller identity, session, and graph scope through one immutable context object.

Built-in definitions must have an explicit registered handler. A type absent from the built-in registry crosses the plugin boundary: the runtime first checks an isolated evaluator, then a trusted in-process evaluator, and otherwise reports an unknown node.

## Persistence

Application release 8.0.0 deliberately keeps project schema version 3. New behavior is represented by existing schema-v3 nodes, handlers, properties, session infrastructure, and application-level UI/export behavior, so no schema migration is required.

V1/v2 projects continue to migrate to schema v3, and existing schema-v3 projects remain the persisted project format.

The bundled spinning-drop examples are:

- `examples/spinning_drop_ift.json` for Standard Mode.
- `examples/spinning_drop_manual_ift.json` for Manual RPM Mode.

The bundled examples are the startup master projects. User copies are stored under `Documents\GMJ PyLabView\Examples` and are refreshed from the bundled release templates so they do not remain on an obsolete default version.

The legacy `csv_report` node has been removed from the bundled Standard and Manual spinning-drop example projects; spinning-drop measurement output now uses session-based XLSX export instead.

## Session Output

A typical session is:

```text
Documents\GMJ PyLabView\
└── Sessions\
    └── Session_YYYYMMDD_HHMMSS_Standard|Manual\
        ├── Captures\
        │   ├── Reference\
        │   ├── Stages\
        │   │   └── <RPM>_RPM\
        │   └── Analysis\
        │       └── <RPM>_RPM\
        ├── Measurements\
        │   └── spinning_drop_run_001.xlsx
        └── Session_Info.json
```

The Excel workbook contains:

- Measurement Summary
- Stage Samples
- Statistics

Stage Samples preserves per-sample traceability, while summary/statistics retain stage-level measurement reporting.

## Frozen Windows Build

The full Windows build uses `PyLabViewStudioFull.spec` as the packaging profile and produces the single release executable:

`PyLabViewStudio.exe`

The spec includes application assets, bundled examples, documentation, and the optional instrumentation dependency profile required by the full release.

The release workflow performs source unit tests, core/full self-tests, optional Yosys validation where available, the PyInstaller build, a frozen executable self-test, and SHA-256 checksum generation.

The release artifact set remains:

- `PyLabViewStudio.exe`
- `PyLabViewStudio.exe.sha256`

Build success, software self-tests, and syntax validation do not constitute physical hardware qualification, hard real-time certification, safety certification, or FPGA timing closure.
