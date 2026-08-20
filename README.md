# PyLabView Studio 2.0.0

PyLabView Studio adalah platform desktop visual dataflow independen berbasis Python standard library dan `tkinter`. Versi 2.0.0 menyediakan proyek multi-VI, tipe wire, SubVI executable, runtime dataflow paralel, Front Panel, simulasi DAQ, dan file JSON terbuka untuk pembelajaran, prototipe instrumentasi, serta fondasi integrasi perusahaan.

Proyek ini **bukan clone lengkap NI LabVIEW**, bukan produk National Instruments, dan tidak berafiliasi atau didukung oleh National Instruments. Tidak ada aset atau branding NI. LabVIEW adalah merek dagang pemiliknya masing-masing.

## Fitur V2

- `Project` berisi banyak `VirtualInstrument`; setiap VI mempunyai graph, connector pane input/output, dan metadata Front Panel.
- Format JSON `pylabview-project` versi 2 dengan validasi schema manual, migrasi graph v1, dan save atomik melalui temporary file + `os.replace`.
- Tipe eksplisit `numeric`, `boolean`, `string`, `array`, `cluster`, `waveform (t0, dt, y)`, `variant`, dan `error cluster`; wire dan port diberi warna menurut tipe serta koneksi inkompatibel ditolak.
- SubVI memanggil VI lain melalui connector pane dinamis. Runtime menolak referensi hilang dan recursion/cycle antar-VI.
- Scheduler dependency menjalankan node ready independen melalui `ThreadPoolExecutor`, lalu menggabungkan hasil secara deterministik menurut urutan graph. Result mencatat value, value per port, status, error, log, dan durasi node.
- Library array build/index/size, cluster bundle/unbundle, waveform create/stats, boolean AND/OR/NOT, min/max/abs, string concatenate/format, case/select, sequence, loop bounded, delay/timed loop, CSV logger, text file I/O, error nodes, dan simulated analog/digital I/O.
- Abstraksi `DAQDriver` dan `DriverRegistry`; distribusi ini hanya menyertakan driver `simulated`. Tidak ada klaim NI-DAQmx atau hardware nyata.
- Front Panel `Toplevel` untuk kontrol numeric/string/boolean/array, indikator teks, LED, gauge, progress, thermometer, dan waveform chart. Rebuild mempertahankan state kontrol dan history chart berdasarkan ID node.
- Editor dengan VI explorer, tambah/rename/delete/set main/switch VI, pencarian palette, validasi toolbar, connector editor, pembuatan SubVI, undo/redo, zoom, inspector `display_type`, execution highlight, dan log.

## Persyaratan dan Menjalankan

- Python 3.10 atau lebih baru.
- `tkinter` dari distribusi Python/OS; Debian/Ubuntu biasanya memakai `sudo apt install python3-tk`.
- Tidak ada dependency runtime pihak ketiga.

```bash
./run.sh
# atau
python -m pylabview
```

Buka proyek pada `examples/`, tampilkan **View > Front Panel**, lalu gunakan `F5` atau `F6`.

## Alur Editor

- Kelola VI lewat **VI Explorer**. Tanda `*` menunjukkan main VI.
- Cari dan klik ganda node pada palette untuk menambahnya.
- Klik port output lalu port input untuk membuat wire. Status/log menjelaskan penolakan tipe.
- Konfigurasikan terminal lewat **Connector** dengan satu baris `direction,name,node_id,port,type`. Setiap input wajib menunjuk output node control yang unik. Output menunjuk port output yang akan diekspos; bila memakai indikator, pilih source sebelum node indikator.
- Gunakan **Create SubVI**, lalu masukkan nama VI target. Port node mengikuti connector pane target.
- Ubah properti termasuk `display_type` di inspector dan tekan **Apply**.
- `Ctrl+Z`/`Ctrl+Y`: undo/redo; `Ctrl+C`/`Ctrl+V`: copy/paste; `Ctrl`+wheel: zoom.

## Semantik Struktur

- `case` dan `select` memilih salah satu nilai setelah dependency input tersedia.
- `sequence` mengembalikan input kedua; wire dependency memastikan kedua tahap selesai, tetapi ini bukan visual sequence frame bersarang.
- `for_loop` memproses array dengan operasi `identity`, `abs`, atau `scale`, dibatasi `max_iterations`.
- `while_loop` menaikkan nilai dengan `step` selama kondisi `less_than`/`greater_than`, dan menghasilkan error jika bound tercapai.
- `timed_loop` menghasilkan array timestamp sebanyak `iterations`; interval dan jumlah iterasi dibatasi.
- Template producer-consumer menyimulasikan produksi/consumption sebagai array ticks. Ia bukan queue asynchronous, backpressure, atau scheduler actor penuh.

## Keamanan File I/O

`DataflowRuntime(data_root=...)` membatasi path normal untuk `file_read`, `file_write`, dan `csv_logger`. Path node harus relatif/berada di bawah root setelah canonical resolution; traversal seperti `../` ditolak, parent directory tidak dibuat otomatis, dan kegagalan dikembalikan sebagai `ErrorCluster`, bukan menjatuhkan runtime. Pemeriksaan path lintas platform ini bukan strong adversarial sandbox dan tidak menjamin perlindungan terhadap race penggantian symlink oleh proses lokal lain. Default root adalah working directory; deployment perusahaan harus memakai direktori data privat dengan permission OS minimum serta isolasi akun/proses atau container bila memproses proyek tak tepercaya. Fitur ini juga bukan sandbox proses terhadap plugin Python berbahaya.

## Contoh

- `simulated_monitor.json`: analog input simulasi, chart, indikator, dan log.
- `waveform_acquisition.json`: membangun waveform dan menghitung statistik.
- `state_machine.json`: state machine dua-state sederhana dengan case node.
- `producer_consumer.json`: demonstrasi scheduler/template yang disederhanakan.

Semua file merupakan proyek v2 dan dapat dieksekusi headless:

```bash
python -c "from pathlib import Path; from pylabview.persistence import load_project; from pylabview.runtime import DataflowRuntime; [DataflowRuntime().run_project(load_project(p)) for p in Path('examples').glob('*.json')]"
```

## Arsitektur dan Test

Lihat [ARCHITECTURE.md](ARCHITECTURE.md) untuk boundary modul/thread dan [docs/ENTERPRISE_ROADMAP.md](docs/ENTERPRISE_ROADMAP.md) untuk fase menuju integrasi DAQ nyata, RT, FPGA, dan Vision tanpa mengklaim fitur tersebut sudah tersedia.

```bash
python -m unittest discover -s tests -v
python -m compileall -q pylabview tests
git diff --check
```

Core model/runtime/persistence/driver tidak membuat window Tk, sehingga test tidak memerlukan display server.

## Build EXE dan Release

Build Windows harus dilakukan di Windows karena PyInstaller bukan cross-compiler:

```bat
build_windows.bat
```

`PyLabViewStudio.spec` membundel semua examples, README, arsitektur, dan docs. Hasil berada di `dist\PyLabViewStudio.exe`. Workflow `.github/workflows/release.yml` menjalankan test, build, checksum SHA-256, artifact, dan GitHub Release untuk tag `v*`; workflow tetap harus dijalankan pada repository GitHub yang memiliki permission release. Proses ini tidak membuktikan kompatibilitas hardware.

## Batasan Jujur

- Runtime desktop bukan hard real-time, safety-rated, distributed, FPGA compiler, atau vision engine.
- Loop/structure masih berupa functional node, bukan nested visual frame lengkap.
- Continuous execution UI belum memiliki cancellation worker preemptive; delay panjang dapat menunda respons satu iterasi UI.
- Connector editor masih tekstual dan layout Front Panel belum merupakan designer bebas.
- Simulated DAQ tidak merepresentasikan timing, buffering, calibration, trigger, atau failure mode hardware nyata.
- Belum ada package trust/signing, RBAC, audit trail, deployment target, probe/breakpoint, atau merge tool VI.

API `Graph`, `save_graph`, `load_graph`, dan `DataflowRuntime.run(graph)` dipertahankan untuk integrasi v1; save graph baru menghasilkan proyek v2 satu-VI, sedangkan loader memigrasikan file v1 saat dibuka.
