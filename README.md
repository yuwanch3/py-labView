# PyLabView Studio 3.0.0

PyLabView Studio adalah aplikasi desktop visual dataflow independen untuk Python 3.10+ dan `tkinter`. V3 menyatukan Front Panel dan Block Diagram dalam satu window, menjalankan diagram di background, serta menyediakan primitive state, debugging, sinkronisasi, dan protokol jaringan yang benar-benar dieksekusi.

Proyek ini bukan clone lengkap NI LabVIEW, bukan produk National Instruments, dan tidak berafiliasi atau didukung oleh National Instruments. LabVIEW adalah merek dagang pemiliknya masing-masing.

## Fitur V3

- Workspace `ttk.Notebook` dengan embedded **Front Panel** dan **Block Diagram**.
- Front Panel free-layout berbasis Canvas: persisted bounds, grid/snap, drag, resize, mode Edit/Operate, dan binding item ke terminal node.
- `RunController` background dengan cooperative cancellation. Tk hanya mem-poll event melalui `after()`.
- Breakpoint node, probe wire, bounded trace, pause/resume, dan deterministic single-step saat debug memakai satu worker.
- Feedback state antar-tick continuous session. Cycle biasa tetap ditolak.
- Visual Case dan For Loop memakai subdiagram tersimpan; editor membuka region melalui **Open Structure**. For Loop menyediakan input tunnel, output tunnel, iteration terminal, dan iteration bound.
- FIFO bounded queue, latest-generation notifier, named event, dan typed message channel dengan timeout/cancellation/close semantics.
- TCP client, UDP endpoint, dan Modbus TCP client FC03/FC06 nyata dengan timeout, size bound, serta frame validation.
- Serial tersedia hanya bila `pyserial` dipasang. OPC UA hanya mempunyai adapter contract dan ditampilkan sebagai unavailable; tidak ada implementasi palsu.
- Plugin registry dengan node namespaced, API compatibility check, `importlib.metadata` discovery, dan isolasi kegagalan import.
- JSON `pylabview-project` v3 dengan `extensions`, atomic save, persisted panel/subdiagram, serta migrasi v1/v2.
- API sinkron `DataflowRuntime.run()`, `Graph`, `load_graph()`, dan `save_graph()` tetap tersedia sebagai compatibility facade.

Legacy `case`, `sequence`, `for_loop`, dan `while_loop` tetap dapat dijalankan dan diberi nama **Legacy Functional**. Mereka bukan visual structure bersarang.

## Menjalankan

```bash
./run.sh
# atau
python -m pylabview
```

Self-test tanpa GUI:

```bash
python -m pylabview --self-test
```

Serial opsional:

```bash
python -m pip install pyserial
```

Tidak ada dependency runtime pihak ketiga untuk core. `tkinter` harus tersedia dari distribusi Python/OS.

## Workflow

1. Pilih VI dari VI Explorer.
2. Gunakan tab Front Panel untuk drag/resize item dan mode Operate untuk mengubah control.
3. Gunakan tab Block Diagram untuk menambah node dan wire.
4. Pilih Visual Case/For lalu **Open Structure** untuk mengedit region; **Root Diagram** kembali ke root.
5. Pilih node lalu **Breakpoint**, atau pilih wire lalu **Probe**.
6. Jalankan F5 atau continuous F6. Stop membatalkan delay, loop, dan wait secara kooperatif.

File v1/v2 dibuka sebagai model v3 dengan migration report dan layout panel deterministik. Save berikutnya menulis v3; file sumber tidak ditimpa sampai user memilih tujuan save.

## Network dan Resource

- Semua timeout network harus lebih dari 0 dan maksimal 300 detik.
- Operasi network dibatasi maksimal 16 MiB per call.
- TCP bekerja pada `bytes`; encoding text harus dilakukan terpisah.
- UDP tidak menjamin delivery/order.
- Modbus memakai alamat register 0-based dan hanya mengklaim FC03/FC06.
- Resource reference hanya valid di run session pembuatnya dan ditutup saat session selesai.

File I/O tetap dibatasi pada `data_root` dengan canonical path checking. Ini bukan sandbox adversarial yang tahan race symlink. Plugin Python juga bukan sandbox dan berjalan dengan hak proses pengguna; aplikasi tidak auto-install plugin/dependency dari proyek.

## Test

```bash
python -m unittest discover -s tests -v
python -m compileall -q pylabview tests
python -m pylabview --self-test
python -c "from pathlib import Path; from pylabview.persistence import load_project; from pylabview.runtime import DataflowRuntime; [DataflowRuntime().run_project(load_project(p)) for p in Path('examples').glob('*.json')]"
git diff --check
```

Protocol integration tests hanya memakai loopback lokal dan tidak mengakses internet.

## Windows

Jalankan `build_windows.bat` pada Windows. PyInstaller menghasilkan `dist\PyLabViewStudio.exe`; workflow release menjalankan test, build, frozen `--self-test`, checksum, dan artifact. Build atau test software tidak membuktikan kompatibilitas hardware atau certification.

## Batasan Jujur

PyLabView Studio 3 bukan hard real-time, safety-rated, FPGA compiler, Vision system, NI hardware driver, atau implementasi OPC UA penuh. Cancellation thread bersifat kooperatif. Plugin tidak diisolasi proses. Modbus terbatas FC03/FC06. Nested editor membuka satu subdiagram pada satu waktu dan belum menyediakan semua tunnel mode LabVIEW. Lihat `docs/V3_USER_GUIDE.md`, `docs/PLUGIN_SDK.md`, dan `ARCHITECTURE.md`.
