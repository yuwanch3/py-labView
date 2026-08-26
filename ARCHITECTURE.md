# Arsitektur PyLabView Studio 4

## Boundaries

- `model.py`, `typesystem.py`, `persistence.py`: strict schema v3, graph types, and atomic project persistence.
- `execution.py`, `resources.py`, `runtime.py`: desktop CPython dataflow scheduler, cooperative cancellation, and session-owned handles.
- `handlers/`: typed `HandlerContext`, `NodeHandler` protocol, duplicate-safe registry, and category modules for all built-in node behavior. `DataflowRuntime._evaluate` resolves one handler and invokes it; it does not dispatch on node type.
- `handlers/spinning_drop.py`: domain handlers for passive Arduino telemetry listening (START/STOP commands, ACK handling, `RPM:;PWM:;TIME:;TARGET:` telemetry and `TARGET_RPM:` stage events parsed tolerantly from one stream), a PC-side RPM stall watchdog, event-driven stage-watcher table building, wire calibration, radius-form Vonnegut IFT, and pycnometer/delta-density calculators. All RPM sequencing timing belongs to the Arduino firmware (ground truth from lab source, 2026-08-21); the PC never sends PWM values. Error clusters are explicit wires; invalid measurements cannot reach report generation.
- `protocols.py`: bounded stdlib TCP/UDP and Modbus TCP FC01/02/03/04/05/06/15/16; pyserial loader remains compatibility API.
- `integrations/`: optional capability/diagnostic, NI-DAQmx, VISA, OPC UA, vision, report, and plugin process adapters. Constructors accept backend injection and do not import optional packages at core startup.
- `hdl.py`: validated combinational graph-to-Verilog subset and optional bounded Yosys syntax subprocess.
- `targets.py`: bounded external target manifest/handshake. A response is reported honestly and never upgrades desktop execution into hard RT.
- `front_panel.py`, `canvas_editor.py`, `app.py`: Tk presentation. Runtime workers never call Tk.
- `front_panel.py` renders persisted start/stop radio controls, bounded gauges, dropdown metadata, intensity-chart axis labels, and compact tabular indicators used by the spinning-drop example; computation remains in graph nodes.

## Lifecycle And Bounds

`RunSession` owns a `ResourceManager`. Its worker `finally` is the sole cleanup owner; cancellation never closes vendor handles concurrently from the UI thread. VISA, serial, and OPC UA wrappers serialize operations and close. Non-interruptible vendor calls can delay cancellation until their configured timeout. NI operations create one task, configure channels/timing, perform one bounded operation, and close in `finally`. Camera capture similarly releases its device after one frame. Report output uses a temporary file and `os.replace`.

Network operations cap one call at 16 MiB and 300 seconds. Serial requests and VISA writes use the same payload ceiling; VISA response size is checked after PyVISA returns and is not a pre-allocation bound. NI samples cap at 1,000,000 and rate at 10 MHz (software guard only, not hardware capability). Images validate shape, dtype, decoded memory metadata, and cap at 100 million pixels, but OpenCV decode allocation occurs before those metadata checks. Reports cap at 100,000 rows and 1 million cells. Paths resolve beneath `data_root`; this canonical check is not an adversarial filesystem sandbox.

## Optionality

Missing packages produce explicit unavailable capabilities or runtime node errors. Project loading only needs node definitions and never imports vendor APIs. Diagnostics software probing is side-effect-light; NI device and VISA resource enumeration occur only when the user presses Refresh Hardware.

Process-isolated plugin evaluators exchange bounded JSON with request IDs. They can contain crashes and enforce a parent timeout, but child code retains the user's OS permissions and therefore is not a security sandbox.

## Handler Registry And Extensions

Importing `pylabview.handlers` loads the category modules and populates the default built-in mapping from node type to handler. The frozen-build specs explicitly include those dynamically imported modules. Registry registration fails on duplicates, and `HandlerRegistry.audit` compares the mapping with `NODE_DEFINITIONS`. `DataflowRuntime` also accepts explicit handler and plugin registries so tests and embedding applications can assemble or replace dispatch without mutating global state. Handlers receive runtime services, node, normalized inputs, controls, logs, project/caller identity, session, and graph scope through one immutable context object.

Built-in definitions must have an explicit registered handler. A type absent from the built-in registry crosses the plugin boundary: the runtime first checks an isolated evaluator, then a trusted in-process evaluator, and otherwise reports an unknown node. Plugin output normalization remains owned by the runtime scheduler, so single-output and multi-output behavior share the same path as built-ins.

## Persistence

Application release 4.3.2 deliberately keeps project schema version 3. New behavior is represented by node type/properties and root/panel extension points, so no v3-to-v4 data migration is necessary.
