# Enterprise Roadmap Setelah V4

V4 menyediakan adapter instrumentation fungsional, tetapi deployment production masih memerlukan qualification terpisah.

## Qualification

- Hardware-in-loop matrix untuk model NI, channel topology, rates, voltage ranges, disconnect, calibration, trigger, buffering, dan vendor runtime versions.
- VISA interoperability untuk NI-VISA, Keysight VISA, dan `pyvisa-py`; serial device/baud/flow-control matrix; Modbus vendor conformance and fault soak.
- OPC UA certificate/security-policy provisioning, StatusCode/timestamp surfaces, subscriptions, reconnect, and server interoperability.
- Vision camera/backend matrix, dataset regression, color/depth contracts, and performance envelopes.
- Signed packages, SBOM, secrets store, RBAC, audit trail, recovery journal, and OS sandbox profile.

## Real-Time And FPGA

Desktop `ThreadPoolExecutor`, GC, and cooperative cancellation are non-real-time. A future target requires watchdog, deployment signing, bounded allocation, priority scheduling, WCET/deadline evidence, and qualified RT OS.

HDL export remains a combinational integer/boolean subset. A future FPGA product needs fixed-point IR, clock/reset semantics, simulation, constraints, synthesis/place/route integration, timing/resource reports, vendor board support, and bitstream provenance. Yosys syntax success is not timing closure or a bitstream.

Tidak ada klaim safety certification, industrial vision validation, physical hardware validation, hard RT, atau FPGA compilation pada V4.
