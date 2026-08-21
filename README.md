# PyLabView Studio 4.3.1

PyLabView Studio adalah aplikasi desktop visual dataflow independen untuk Python 3.10+ dan `tkinter`. V4 mempertahankan core standard-library dan schema proyek v3, lalu menambahkan instrumentation adapters nyata yang dimuat secara opsional. Proyek ini tidak berafiliasi dengan National Instruments; LabVIEW adalah merek dagang pemiliknya.

## Instrumentation V4

- NI-DAQmx melalui package resmi `nidaqmx`: AI/AO/DI/DO, physical channel, range, finite samples/rate, task cleanup, dan device discovery eksplisit.
- PyVISA: list/open resource, timeout, text write/query, raw read/write, post-read response-size validation, dan close.
- PySerial: open/read/write/close untuk bytes atau encoded text.
- OPC UA melalui `asyncua.sync.Client`: connect, read/write value, dan disconnect. Tidak mengklaim subscription.
- Modbus TCP FC01/02/03/04/05/06/15/16 dengan validation, exception response, dan LSB-first coil packing.
- OpenCV/NumPy vision: file/camera single frame, grayscale, blur, threshold, Canny, resize, template match, save, dan image metadata indicator.
- Report HTML/CSV selalu tersedia; XLSX, DOCX, dan PDF opsional.
- Restricted combinational HDL exporter dan optional Yosys syntax check. Ini bukan FPGA compiler atau bitstream generator.
- Opt-in JSON plugin evaluator process host untuk timeout/crash isolation. Ini bukan security sandbox.
- Hardware / Integration Diagnostics memisahkan software probe dari explicit hardware Refresh.

Semua resource external dimiliki worker run session dan ditutup pada sukses, error, atau cancellation. Stop tidak menutup handle dari thread UI. Vendor call yang tidak interruptible baru berhenti saat timeout adapter berakhir. File report/image dibatasi ke `DataflowRuntime.data_root`; network, payload, sample, image, dan timeout memiliki bounds. Batas VISA response diterapkan setelah backend selesai membaca response dan bukan memory-allocation bound.

## Instalasi

Core tidak mempunyai dependency PyPI:

```bash
python -m pylabview
python -m pylabview --self-test
```

Pasang adapter yang diperlukan saja atau seluruh profile:

```bash
python -m pip install -r requirements-optional.txt
```

NI memerlukan package Python `nidaqmx` **dan** NI-DAQmx vendor runtime/driver yang sesuai. PyVISA memerlukan backend VISA, misalnya NI-VISA vendor runtime atau `pyvisa-py`; instalasi `PyVISA` saja tidak selalu menyediakan transport. Windows Full build tidak membundel driver vendor NI/VISA.

## Compatibility

App version adalah 4.3.1; format persisted tetap `pylabview-project` schema version 3. Node/properties baru dapat disimpan tanpa field schema baru. V1/v2 tetap dimigrasi ke schema v3; semua proyek v3 tetap dapat dibuka.

## Test

```bash
python -m unittest discover -s tests -v
python -m compileall -q pylabview tests
python -m pylabview --self-test
python -c "from pathlib import Path; from pylabview.persistence import load_project; from pylabview.runtime import DataflowRuntime; [(p, DataflowRuntime().validate(project.main.graph, project, project.main_vi)) for p in Path('examples').glob('*.json') for project in [load_project(p)]]"
git diff --check
```

Test tidak mengakses internet atau hardware. Adapter hardware diuji dengan fake backend; protocol memakai loopback/stub lokal. OpenCV/NumPy aktual hanya dijalankan oleh full-profile frozen self-test. `examples/spinning_drop_ift.json` adalah proyek hardware prototype dan hanya dimuat/divalidasi oleh perintah di atas; menjalankannya memerlukan Arduino, sensor RPM, kamera, dan kalibrasi kawat yang sesuai. Lihat `docs/V4_INSTRUMENTATION_GUIDE.md` dan `docs/HARDWARE_VALIDATION.md` untuk support matrix.

## Windows Builds

- `build_windows.bat`: small core executable; optional packages tetap tidak dibundel.
- `build_windows_full.bat`: memasang `requirements-optional.txt` dan menghasilkan `PyLabViewStudioFull.exe`.

CI membangun core dan full profile pada job terpisah. Full executable menjalankan `--self-test-full`, yang mengimpor seluruh dependency opsional dan hanya memakai data in-memory/fake tanpa enumerasi hardware.

Keduanya tetap memerlukan vendor driver/runtime eksternal untuk NI hardware dan backend VISA. Build, unit test, dan syntax check bukan bukti hardware qualification, hard real-time, safety certification, atau FPGA timing closure.
