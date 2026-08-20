# Enterprise Roadmap Setelah V3

Dokumen ini menyatakan arah, bukan fitur yang sudah tersedia.

## Stabilization

- Process isolation untuk plugin, signed package policy, recovery journal, audit trail, RBAC, dan secrets store.
- Connector pane grafis, richer typed arrays/clusters, conditional/auto-index tunnel, shift-register UI boundary, multi-frame structure navigation, dan VI diff/merge.
- TLS adapter, serial hardware qualification, Modbus interoperability matrix, reconnect policy, dan packet/fault soak testing.
- OPC UA adapter konkret hanya setelah certificate/security policy, namespace, StatusCode/timestamp, subscription, dan reconnect tervalidasi terhadap server nyata.

## Hardware

- Driver vendor nyata memerlukan capability discovery, calibration, buffering, trigger/sample clock, lifecycle, hardware-in-loop test, dan daftar perangkat yang didukung.
- Tidak ada dukungan NI-DAQmx dalam core v3. Simulated DAQ bukan bukti kompatibilitas hardware.

## Real-Time

- Runtime proses terpisah, bounded allocation, deployment protocol, watchdog, priority scheduling, WCET/deadline analysis, dan target OS real-time.
- `ThreadPoolExecutor` desktop dan cooperative cancellation v3 bukan hard real-time atau safety-rated.

## FPGA dan Vision

- FPGA memerlukan IR statis/fixed-point, synthesis backend vendor, cycle-accurate simulation, dan timing/resource report.
- Vision memerlukan typed image buffers, camera backend, validated operators, dataset regression, dan optional acceleration.

Setiap klaim produksi memerlukan threat model, SBOM, support matrix, signing, qualification evidence, dan dokumentasi keselamatan. V3 belum certified untuk proses kritis.
