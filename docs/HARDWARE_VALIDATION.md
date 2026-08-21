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
| Spinning-drop IFT tensiometer prototype (Arduino/BTS7960, RPM pulse sensor, dual-mode camera) | Modelled/implemented for automated evaluation | Injected serial/OpenCV backends, protocol parsing, sensor interlock, image-profile, Vonnegut tests, and sequencer state-machine | **Not performed** |

PyLabView Studio 4.2.0 is not safety-rated, medically certified, hard real-time, or qualified for control of hazardous processes. Users must perform device-specific installation, calibration, electrical protection, fault handling, cybersecurity, and acceptance testing.

The handler-registry, parser, and UI decomposition is an internal refactor. It adds no physical hardware evidence and does not change any physical-validation outcome above.

## Spinning Drop IFT Use Case

`examples/spinning_drop_ift.json` models the confirmed laboratory arrangement: a TZ20002MG mechanical base, 60 W / 12 V / 5 A DC spindle motor, BTS7960 HW-039 H-bridge, Arduino Uno-compatible ATmega328P controller, installed pulse RPM sensor, capillary holder, and USB or network camera. This description records the supplied hardware inventory; it is **not** evidence that this software build has operated that equipment.

The built-in nodes `arduino_motor_rpm`, `camera_capture_dual_mode`, `edge_intensity_profile`, `wire_calibration`, `pixel_to_mm`, `vonnegut_ift`, `pycnometer_density`, and `delta_density` are implemented and covered only by automated tests. The RPM sensor status is a mandatory `vonnegut_ift` input; any value other than `OK` produces an error cluster and zero IFT outputs. Error clusters also gate the log-row node, preventing rejected measurements from reaching the report. Wire diameter has no valid default: the example starts at zero and calculation is rejected until the operator enters a measured value.

The current Arduino exchange is the provisional text protocol `SET_PWM:<0-255>`, `ACK_PWM:<value>`, and one of the documented `RPM:` responses. Requested and acknowledged PWM must match. Sensor/protocol failures, cancellation callbacks, and serial-session cleanup issue a bounded best-effort `SET_PWM:0`; callback write failures are exposed in the debugger trace. This is not a certified emergency stop. Physical deployment also requires a firmware PWM watchdog that disables the BTS7960 when valid host commands stop, plus a hardware power-disconnect/E-stop appropriate to the apparatus. The protocol must be checked against the original VI block diagram or matching firmware before physical qualification. The first `TIME(s)` control supplies the bounded camera open/read timeout as an assumed measurement-duration interpretation. The second is retained as an explicitly unconfirmed sampling-interval field and does not alter the application's continuous-run cadence.

Oil and reference-wire captures in the example share one camera mode, USB index, network URL, and optical path; adapter access is serialized to avoid simultaneous ownership of one device. Calibration must be acquired as a separate staged specimen operation without changing camera, resolution, crop, zoom, lens, focus, or working distance. The supplied graph documents both capture paths but does not automate physical wire-to-drop specimen exchange, so physical qualification must split those acquisitions operationally. The network URL is operator-supplied and causes outbound OpenCV access when the graph runs; only trusted camera endpoints should be used. Backend timeout properties are requested where OpenCV supports them, but some camera backends may ignore them.

The five supplied pycnometer records are tested against the stated mass/volume formula. The raw floating-point results are retained; the handwritten whole-number references 953, 976, 988, 941, and 1010 kg/m³ correspond to truncating those raw values, not conventional nearest-integer rounding.

Physical qualification remains pending. A future record must include test date, operator, Arduino/CH340 port and driver version, firmware hash, exact sensor pulses per revolution, camera source and resolution, known-wire micrometer measurement, serial transcript, independent tachometer comparison, source images, calculated intermediates, and pass/fail results. Until then the status is: **implemented, automated test only, physical hardware validation not performed**.
