# PyLabView Studio

Versi stabil saat ini: **1.0.0**.

PyLabView Studio adalah lingkungan desktop dataflow visual independen yang dibuat dengan Python dan `tkinter`. Aplikasi ini ditujukan untuk pembelajaran, eksperimen, dan prototipe instrumentasi simulasi.

Proyek ini **bukan NI LabVIEW**, bukan produk National Instruments, serta tidak berafiliasi atau didukung oleh National Instruments. Tidak ada logo maupun aset merek NI di proyek ini. LabVIEW adalah merek dagang pemiliknya masing-masing.

## Fitur

- Editor Block Diagram berbasis canvas dengan grid dan zoom.
- Node dapat ditambah dari library, dipindah, dipilih, disalin, ditempel, dan dihapus.
- Wiring interaktif: klik port output kuning, lalu port input biru. Satu input menerima satu wire.
- Library numeric/string/boolean constant, Add, Subtract, Multiply, Divide, Sine, Compare, Select, Random, Timer, simulated analog input, Display, Waveform Chart, dan Log Output.
- Evaluasi dataflow topologis dengan deteksi cycle, input terputus, pembagian nol, dan error konfigurasi.
- Run once dan continuous run non-blocking menggunakan scheduler event loop Tk.
- Front Panel terpisah berisi kontrol constant, indikator Display, dan grafik riwayat Waveform Chart.
- Property inspector untuk label, nilai, channel, range, operator, history, dan konfigurasi lain.
- New, Open, Save, dan Save As dengan format JSON yang mudah dibaca.
- Undo/redo sampai 100 snapshot dan copy/paste node.
- Execution highlighting hijau/merah dan console log.
- Contoh proyek monitor analog simulasi.
- Menu quick help dan about.

## Persyaratan

- Python 3.10 atau lebih baru.
- `tkinter`, biasanya sudah disertakan pada installer Python Windows/macOS.
- Pada Debian/Ubuntu, bila belum tersedia: `sudo apt install python3-tk`.
- Tidak ada package runtime pihak ketiga.

## Menjalankan

Linux/macOS:

```bash
./run.sh
```

Atau pada semua platform:

```bash
python -m pylabview
```

Buka `examples/simulated_monitor.json`, tampilkan **View > Front Panel**, lalu tekan **F6** untuk melihat chart bergerak.

## Interaksi Editor

- Tambah node: klik ganda tipe node pada Node Library.
- Pindah node: drag badan node.
- Wiring: klik port output kuning, lalu port input biru.
- Hapus: pilih node atau wire, lalu tekan `Delete`.
- Properti: pilih node, ubah field di panel kanan, lalu tekan **Apply**.
- Zoom: `Ctrl` + roda mouse.
- Run once: `F5`; continuous: `F6`; stop: `Shift+F6`.
- Undo/redo: `Ctrl+Z` / `Ctrl+Y`; copy/paste: `Ctrl+C` / `Ctrl+V`.

## Pengujian Headless

Model, runtime, dan persistensi tidak mengimpor atau membuat window Tk, sehingga test dapat berjalan tanpa display server:

```bash
python -m unittest discover -s tests -v
python -m compileall -q pylabview tests
```

## Build Windows EXE

Build `.exe` harus dijalankan di Windows karena PyInstaller bukan cross-compiler. Dari Command Prompt Windows dengan Python terpasang:

```bat
build_windows.bat
```

Script memasang PyInstaller bila diperlukan dan menjalankan `PyLabViewStudio.spec`. Hasil berada di `dist\PyLabViewStudio.exe`. Repository ini dibuat di Linux, sehingga executable Windows tidak dihasilkan atau diklaim telah diuji di lingkungan ini.

## Rilis Siap Pakai

Setiap tag versi `v*` menjalankan GitHub Actions pada Windows untuk menguji proyek, membangun `PyLabViewStudio.exe`, membuat checksum SHA-256, dan menerbitkan GitHub Release. Halaman release juga menyediakan arsip source code ZIP dan TAR.GZ secara otomatis.

Unduh versi terbaru dari [GitHub Releases](https://github.com/ha-neko/py-labView/releases/latest).

## Struktur

```text
pylabview/
  app.py             UI utama dan lifecycle dokumen
  canvas_editor.py   editor Block Diagram
  front_panel.py     kontrol, indikator, dan chart
  model.py           graph, node, wire, katalog node
  runtime.py         validator dan mesin dataflow
  persistence.py     penyimpanan JSON
examples/            proyek contoh
tests/               unit test headless
```

## Format Proyek

File proyek JSON memiliki penanda `format: "pylabview-project"`, versi format, daftar node, dan daftar wire. Input yang sudah terhubung akan diganti bila wire baru diarahkan ke port input yang sama.
