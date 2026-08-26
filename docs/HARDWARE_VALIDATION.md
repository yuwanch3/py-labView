# Hardware Validation Status

| Subsystem | Implemented | Automated evidence | Physical validation |
|---|---|---|---|
| Simulated DAQ | Yes | Unit tests | Not applicable |
| NI-DAQmx AI/AO/DI/DO | Yes | Injected fake API, sequence/bounds/cleanup | **Not performed** |
| VISA | Yes | Fake ResourceManager/instrument | **Not performed** |
| Serial | Yes | Fake stream; pyserial loop URL optional | **Not performed** |
| OPC UA value read/write | Yes | Fake sync client | No physical/production server qualification |
| Modbus TCP FC01/02/03/04/05/06/15/16 | Yes | Local stub/vector tests | No vendor device qualification |
| OpenCV vision operators | Yes | Fake unit tests; actual in-memory OpenCV/NumPy only in full frozen self-test, no camera | No industrial camera/vision validation |
| HTML/CSV reports | Yes | Actual temporary files | Not applicable |
| XLSX/DOCX/PDF reports | Yes when package installed | Fake unit tests plus dependency import in full frozen self-test | No compliance certification |
| Verilog subset | Yes | Golden/rejection tests | No board, synthesis timing, or bitstream validation |
| External RT target | Handshake contract only | Fake socket | No qualified target |
| Spinning-drop IFT tensiometer prototype (Arduino/BTS7960, RPM pulse sensor, dual-mode camera) | Modelled/implemented for automated evaluation | Injected serial/OpenCV backends, firmware-protocol parsing (telemetry/ACK/TARGET_RPM), event-driven stage watcher, PC-side RPM stall watchdog, image-profile and Vonnegut tests | **Not performed** |

PyLabView Studio 4.3.4 is not safety-rated, medically certified, hard real-time, or qualified for control of hazardous processes. Users must perform device-specific installation, calibration, electrical protection, fault handling, cybersecurity, and acceptance testing.

The handler-registry, parser, and UI decomposition is an internal refactor. It adds no physical hardware evidence and does not change any physical-validation outcome above.

## Spinning Drop IFT Use Case

`examples/spinning_drop_ift.json` models the confirmed laboratory arrangement: a TZ20002MG mechanical base, 60 W / 12 V / 5 A DC spindle motor, BTS7960 HW-039 H-bridge, Arduino Uno-compatible ATmega328P controller, installed pulse RPM sensor, capillary holder, and USB or network camera. This description records the supplied hardware inventory; it is **not** evidence that this software build has operated that equipment.

The built-in nodes `arduino_telemetry_reader`, `rpm_stall_watchdog`, `spinning_drop_stage_watcher`, `camera_capture_dual_mode`, `edge_intensity_profile`, `wire_calibration`, `pixel_to_mm`, and `vonnegut_ift` are implemented and covered only by automated tests. The density difference is a manual operator input on the front panel, matching the original VI; the pycnometer/delta-density calculator nodes remain available as general platform nodes but are not wired into this example.

### Serial protocol: ground truth from the lab firmware source (found 2026-08-21)

The Arduino exchange is no longer provisional. The original firmware source was found directly on the lab computer on **2026-08-21**; the protocol below is transcribed from that source, not assumed or reverse-engineered:

- PC to Arduino, plain text plus newline: `START` (firmware begins its own 6-stage sequence at 1000 RPM) and `STOP` (forced stop; the firmware replies `ACK:STOP`).
- Firmware replies: `ACK:START`, `ACK:STOP`, and `ACK:AUTOSTOP_6000` — the last is sent autonomously by the firmware after 3 minutes at 6000 RPM, without a PC request.
- Continuous telemetry while running (~100 ms cadence): `RPM:<int>;PWM:<int>;TIME:<float 3dp>;TARGET:<int>`. `TIME` is seconds since the last target change. The parser tolerates garbage and partial lines; incomplete chunks stay buffered until their newline arrives.
- Stage-change event, sent once per firmware-initiated RPM step: `TARGET_RPM:<int>`. The initial 1000 RPM target is **not** announced: receiving `START` makes the firmware ramp to a hardcoded 1000 RPM silently, so `TARGET_RPM` events only ever fire for the increments to 2000–6000. The stage watcher therefore seeds its "previous stage" record with 1000 at the IDLE→RUNNING transition; without this, the lowest data point would be silently lost in every experiment.

Architecture consequence: the 6-stage RPM sequencing (1000–6000 RPM, 3 minutes per stage, autostop after 6000) is entirely a firmware responsibility. PyLabView Studio is a passive event listener — `spinning_drop_stage_watcher` appends one table row per stage-completion event (five `TARGET_RPM` events plus the final `ACK:AUTOSTOP_6000`) and never measures stage duration itself. An earlier PC-side sequencer node that duplicated this timing was removed. The PC never sends PWM values; RPM arrives already computed by the firmware (4 holes per revolution on the sensor disc), and no pulse-to-RPM calculation exists anywhere in the PC codebase.

Because the firmware reports no sensor status, there is no `sensor_status` wire. A dead sensor or motor can only be inferred PC-side: the optional `rpm_stall_watchdog` node flags a stall when RPM stays at 0 for a configurable duration while the target demands rotation. Cancellation callbacks and serial-session cleanup issue a best-effort `STOP`; callback write failures are exposed in the debugger trace. This is not a certified emergency stop. Physical deployment still requires a hardware power-disconnect/E-stop appropriate to the apparatus.

Oil and reference-wire captures in the example share one camera mode, USB index, network URL, and optical path; adapter access is serialized to avoid simultaneous ownership of one device. The two captures are separated by trigger, not by source: `oil_camera` runs live (its `capture_trigger` is a True constant) while `wire_camera` holds its last frame and only re-captures when the operator presses the panel's "Capture Reference" button. This stops the comparison picture silently re-grabbing the same instant of the oil feed as an identical image. Calibration must still be acquired as a separate staged specimen operation without changing camera, resolution, crop, zoom, lens, focus, or working distance; the graph does not automate physical wire-to-drop specimen exchange, so physical qualification must split those acquisitions operationally. The network URL is operator-supplied and causes outbound OpenCV access when the graph runs; only trusted camera endpoints should be used. Backend timeout properties are requested where OpenCV supports them, but some camera backends may ignore them.

The five supplied pycnometer records are tested against the stated mass/volume formula (the calculator nodes remain part of the platform). The raw floating-point results are retained; the handwritten whole-number references 953, 976, 988, 941, and 1010 kg/m³ correspond to truncating those raw values, not conventional nearest-integer rounding. In the example project the density difference is entered manually, as in the original VI.

Physical qualification remains pending. A future record must include test date, operator, Arduino/CH340 port and driver version, firmware hash, camera source and resolution, known-wire micrometer measurement, serial transcript, independent tachometer comparison, source images, calculated intermediates, and pass/fail results. Until then the status is: **implemented, automated test only (fake serial backend replaying the real firmware line formats), physical hardware validation not performed**.
