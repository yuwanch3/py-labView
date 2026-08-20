# Enterprise Roadmap

Dokumen ini menyatakan arah, bukan fitur yang sudah tersedia.

## Fase 1: Fondasi Produksi

- Schema evolution bertanda tangan, audit trail, role-based access, package/plugin trust, dan recovery dokumen.
- Scheduler cancellation/asynchronous, resource lifecycle, structured telemetry, benchmarking, dan soak test.
- UI connector pane grafis, frame visual bersarang, debugging probe/breakpoint, dan diff/merge VI.

## Fase 2: DAQ dan Integrasi

- Plugin nyata per vendor dengan capability discovery, calibration, buffering, trigger, sample clock, dan integration test pada hardware.
- Serial, TCP, OPC UA, dan Modbus dengan timeout/retry eksplisit serta secrets management.
- Tidak ada dukungan NI-DAQmx dalam v2 ini. Integrasi tersebut baru boleh diklaim setelah adapter resmi dan validasi hardware tersedia.

## Fase 3: Real-Time

- Runtime terpisah yang deterministik, deployment protocol, watchdog, health monitoring, bounded memory, dan target OS real-time.
- Analisis deadline/WCET dan priority scheduling. `ThreadPoolExecutor` desktop v2 bukan runtime real-time.

## Fase 4: FPGA

- IR statis tersendiri, fixed-point type, synthesis backend, timing/resource report, simulator cycle-accurate, dan toolchain hardware vendor.
- Node loop fungsional desktop tidak dianggap sebagai FPGA compiler.

## Fase 5: Vision

- Buffer gambar bertipe, pipeline streaming, backend kamera, operator vision tervalidasi, akselerasi opsional, dan dataset regression.
- Vision tidak disertakan dalam v2.

Setiap fase memerlukan threat model, SBOM, qualification matrix, dokumentasi keselamatan, dan batas dukungan yang dapat diaudit sebelum dipakai pada proses kritis.
