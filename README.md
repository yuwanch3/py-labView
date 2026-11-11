# PyLabView Studio 9.0.0

PyLabView Studio adalah aplikasi desktop visual dataflow independen untuk Python 3.10+ dan `tkinter`. Aplikasi mempertahankan core dataflow dan schema proyek v3, serta menyediakan integrasi instrumentation, vision, serial communication, dan workflow spinning-drop interfacial tension (IFT).

Proyek ini tidak berafiliasi dengan National Instruments; LabVIEW adalah merek dagang pemiliknya.

## Spinning-Drop IFT

PyLabView Studio 9.0.0 menyediakan workflow spinning-drop IFT dengan dua mode operasi:

- **Standard Mode**: menjalankan sequence RPM 1000 → 2000 → 3000 → 4000 → 5000 → 6000 RPM dengan kontrol PID pada Arduino dan stage otomatis.
- **Manual RPM Mode**: operator menentukan target RPM hingga 6000 RPM, sedangkan PWM tetap dikendalikan otomatis oleh PID.
- **Ganti Mode** tersedia langsung dari workspace melalui menu `Mode`, sehingga operator dapat berpindah antara Standard Mode dan Manual RPM Mode tanpa menutup aplikasi.
- Saat **Ganti Mode** dijalankan, motor/runtime aktif dihentikan terlebih dahulu, resource camera dan serial ditutup secara aman, workspace lama di-reset, lalu layar pemilihan mode ditampilkan kembali. Mode berikutnya dimulai dengan workspace dan session state yang fresh.
- Front Panel dan Block Diagram menyediakan scrollbar vertikal visual, selain navigasi mouse-wheel dan zoom yang sudah tersedia.
- Front Panel Operate Mode menggunakan persistent rendering untuk live picture, Grafik Oil/Kawat, tabel, serta indikator berfrekuensi tinggi sehingga refresh runtime tidak membangun ulang seluruh canvas.
- **Manual Target RPM spinner** mengubah target dalam langkah 250 RPM melalui tombol ▲/▼; tombol dapat ditahan untuk auto-repeat dan tetap dibatasi pada 1000–6000 RPM.
- Perubahan posisi/ukuran item Front Panel membuat satu checkpoint undo per drag, bukan checkpoint berulang pada setiap event gerakan.
- Arduino serial telemetry untuk RPM, PWM, elapsed time, dan current target.
- Kamera/OpenCV untuk live image dan pengukuran diameter.
- Wire/reference calibration untuk konversi diameter pixel ke millimeter.
- Capture Reference satu klik dengan calibration reference yang tetap frozen selama measurement run.
- Picture Comparison dan Grafik Kawat dapat mengikuti masing-masing stage sample tanpa mengganti calibration reference.
- Setiap completed stage/target menghasilkan 10 raw stage JPG captures.
- Setiap raw stage sample memiliki satu synchronized Analysis PNG berisi Grafik Oil, Grafik Kawat, w², r³, IFT N/m, dan IFT mN/m.
- Analysis PNG dirender melalui background worker agar proses encoding/write tidak memblokir refresh Front Panel.
- Perhitungan spinning-drop IFT menggunakan density difference, angular velocity, radius, serta output IFT dalam N/m dan mN/m.
- Measurement Log untuk setiap stage pengukuran.
- Automatic Excel `.xlsx` export dengan tiga sheet: Measurement Summary, Stage Samples, dan Statistics.
- Global Stop dan Stop Continuous untuk kontrol measurement/runtime.
- **Stop Bertahap** untuk deselerasi motor secara gradual pada Standard Mode dan Manual RPM Mode; hard Stop tetap bekerja secara langsung sebagai emergency stop.
- Fallback telemetry Standard Mode hanya menerima 1000, 2000, 3000, 4000, 5000, dan 6000 RPM sebagai stage pengukuran; target ramp internal firmware tidak membuat measurement stage tambahan.

Data pengguna disimpan pada:

`Documents\GMJ PyLabView\`

dengan struktur utama:

```text
GMJ PyLabView\
├── Examples\
├── Projects\
└── Sessions\
    └── Session_YYYYMMDD_HHMMSS_Standard|Manual\
        ├── Captures\
        │   ├── Reference\
        │   ├── Stages\
        │   │   └── <RPM>_RPM\
        │   └── Analysis\
        │       └── <RPM>_RPM\
        ├── Measurements\
        └── Session_Info.json
```

Folder RPM dibuat on-demand saat capture dilakukan.

Default example project tersedia untuk Standard Mode dan Manual RPM Mode. Bundled examples adalah master startup project; user-copy di `Documents\GMJ PyLabView\Examples` disinkronkan dari bundled release examples.

Legacy top-level `Captures`, `Measurement Exports`, dan `spinning-drop-ift.csv` tidak lagi digunakan oleh workflow spinning-drop release 9.0.0.

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

App version adalah **9.0.0**.

Format persisted tetap `pylabview-project` schema version 3. Perubahan versi aplikasi tidak mengubah schema project.

V1/v2 tetap dimigrasi ke schema v3 dan semua project v3 tetap dapat dibuka.

## Test

```bash
python -m pytest
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
