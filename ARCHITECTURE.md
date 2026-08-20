# Arsitektur PyLabView Studio 2

PyLabView Studio memisahkan UI `tkinter` dari core yang dapat diuji headless.

## Lapisan

- `typesystem.py`: tipe wire eksplisit, coercion, validasi, serialisasi `Waveform` dan `ErrorCluster`.
- `model.py`: katalog node, `Graph`, `VirtualInstrument`, connector pane, dan `Project` multi-VI.
- `runtime.py`: validasi dependency/call graph dan scheduler dataflow. Node ready pada level yang sama dikirim ke `ThreadPoolExecutor`; hasilnya digabung menurut urutan graph. Worker tidak memanggil Tk.
- `drivers.py`: kontrak `DAQDriver`, registry plugin, channel config, dan DAQ simulasi bawaan.
- `persistence.py`: schema JSON v2 manual, migrasi v1, dan atomic replace.
- `canvas_editor.py`, `front_panel.py`, `app.py`: adapter presentasi desktop.

## Eksekusi

Wire membentuk dependency DAG. Runtime menjalankan level ready, menyimpan nilai per `(node_id, port)`, memeriksa tipe output, status, log, dan durasi. SubVI memanggil VI target melalui connector pane. Call graph rekursif ditolak sebelum eksekusi.

Loop v2 adalah node fungsional bounded, bukan frame diagram bersarang. `for_loop` memetakan array dengan operasi terbatas. `while_loop` mengubah nilai sampai kondisi selesai atau bound tercapai. Template producer-consumer memakai array ticks dan tidak merupakan queue/message scheduler penuh.

## Ekstensi

Driver perusahaan mengimplementasikan `DAQDriver`, lalu didaftarkan pada `DriverRegistry`. Runtime tidak mengklaim atau mengimpor NI-DAQmx. Node/protokol serial, Modbus, atau hardware harus ditambahkan sebagai plugin konkret dengan lifecycle, timeout, dan test integrasi sendiri.

## Threading

Evaluator node berjalan di worker. Pengumpulan result serta seluruh pembaruan canvas/front panel terjadi di thread Tk setelah `run` selesai. Continuous run saat ini memanggil satu graph run per tick event-loop, sehingga node delay panjang tetap dapat menunda UI; roadmap mencakup controller run asynchronous penuh.

## Boundary File I/O

Canonical path checking pada `data_root` mencegah traversal biasa, tetapi bukan sandbox adversarial yang tahan race symlink lintas platform. Proyek tak tepercaya harus dijalankan dengan direktori privat, permission OS minimum, dan isolasi akun/proses atau container.
