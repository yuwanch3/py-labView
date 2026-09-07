# PyLabView Studio 7.9.0

PyLabView Studio adalah aplikasi desktop visual dataflow independen untuk Python 3.10+ dan `tkinter`. Aplikasi mempertahankan core dataflow dan schema proyek v3, serta menyediakan integrasi instrumentation, vision, serial communication, dan workflow spinning-drop interfacial tension (IFT).

Proyek ini tidak berafiliasi dengan National Instruments; LabVIEW adalah merek dagang pemiliknya.

## Spinning-Drop IFT

PyLabView Studio 7.9.0 menyediakan workflow spinning-drop IFT dengan dua mode operasi:

- **Standard Mode**: menjalankan sequence RPM 1000 → 2000 → 3000 → 4000 → 5000 → 6000 RPM dengan kontrol PID pada Arduino dan stage otomatis.
- **Manual RPM Mode**: operator menentukan target RPM hingga 6000 RPM, sedangkan PWM tetap dikendalikan otomatis oleh PID.
- Arduino serial telemetry untuk RPM, PWM, elapsed time, dan current target.
- Kamera/OpenCV untuk live image dan pengukuran diameter.
- Wire/reference calibration untuk konversi diameter pixel ke millimeter.
- Capture Reference satu klik dan Picture Comparison.
- Automatic stage snapshot.
- Perhitungan spinning-drop IFT menggunakan parameter density difference, angular velocity, radius, serta output IFT dalam N/m dan mN/m.
- Measurement Log untuk setiap stage pengukuran.
- Automatic Excel `.xlsx` export setelah measurement run.
- Global Stop dan Stop Continuous untuk kontrol measurement/runtime.
- **Stop Bertahap** untuk deselerasi motor secara gradual pada Standard Mode dan Manual RPM Mode; hard Stop tetap bekerja secara langsung sebagai emergency stop.

Data pengguna disimpan pada:

`Documents\GMJ PyLabView`

dengan struktur:

- `Captures`
- `Measurement Exports`
- `Examples`
- `Projects`

Default example project tersedia untuk Standard Mode dan Manual RPM Mode. Existing user examples tidak ditimpa saat aplikasi dijalankan kembali.

## Instrumentation

- NI-DAQmx melalui package resmi `nidaqmx`: AI/AO/DI/DO, physical channel, range, finite samples/rate, task cleanup, dan device discovery eksplisit.
- PyVISA: list/open resource, timeout, text write/query, raw read/write, post-read response-size validation, dan close.
- PySerial: open/read/write/close untuk bytes atau encoded text.
- OPC UA melalui `asyncua.sync.Client`: connect, read/write value, dan disconnect.
- Modbus TCP FC01/02/03/04/05/06/15/16 dengan validation, exception response, dan LSB-first coil packing.
- OpenCV/NumPy vision untuk camera/image processing.
- Report HTML/CSV tersedia; XLSX, DOCX, dan PDF didukung melalui optional profile.
- Restricted combinational HDL exporter dan optional Yosys syntax check.
- Opt-in JSON plugin evaluator process host untuk timeout/crash isolation.
- Hardware / Integration Diagnostics memisahkan software probe dari explicit hardware refresh.

Semua external resource dimiliki worker run session dan ditutup pada sukses, error, atau cancellation. Vendor call yang tidak interruptible baru berhenti saat timeout adapter berakhir.

## Instalasi

Jalankan dari source:

```bash
python -m pylabview
```

Core self-test:

```bash
python -m pylabview --self-test
```

Full optional-profile self-test:

```bash
python -m pylabview --self-test-full
```

Pasang seluruh optional instrumentation profile:

```bash
python -m pip install -r requirements-optional.txt
```

NI memerlukan package Python `nidaqmx` **dan** NI-DAQmx vendor runtime/driver yang sesuai.

PyVISA memerlukan backend VISA, misalnya NI-VISA vendor runtime atau `pyvisa-py`. Instalasi `PyVISA` saja tidak selalu menyediakan transport.

Windows build tidak membundel driver vendor NI/VISA.

## Compatibility

App version adalah **7.9.0**.

Format persisted tetap `pylabview-project` schema version 3. Perubahan versi aplikasi tidak mengubah schema project.

V1/v2 tetap dimigrasi ke schema v3 dan semua project v3 tetap dapat dibuka.

## Test

```bash
python -m unittest discover -s tests -v

python -m compileall -q pylabview tests

python -m pylabview --self-test

python -m pylabview --self-test-full

git diff --check
```

Test otomatis tidak menggantikan validasi hardware fisik.

Spinning-drop workflow membutuhkan Arduino, RPM sensor, motor/controller, kamera, spinning-drop tube/capillary, serta kalibrasi reference object yang sesuai.

## Windows Build

Windows release menggunakan full instrumentation profile dan menghasilkan satu executable:

```text
PyLabViewStudio.exe
```

Build lokal:

```bat
build_windows_full.bat
```

PyInstaller menggunakan:

```text
PyLabViewStudioFull.spec
```

Nama spec tetap menggunakan `Full` sebagai build profile internal, tetapi executable release adalah:

```text
PyLabViewStudio.exe
```

GitHub Actions melakukan unit test, full-profile source self-test, PyInstaller build, frozen startup self-test, checksum SHA-256, dan publish release.

GitHub Release menyediakan:

```text
PyLabViewStudio.exe
PyLabViewStudio.exe.sha256
```

Vendor driver/runtime eksternal tetap diperlukan untuk hardware NI dan backend VISA.

Build, unit test, dan syntax check bukan bukti hardware qualification, hard real-time behavior, safety certification, atau FPGA timing closure.
