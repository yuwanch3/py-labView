# V3 User Guide

## Workspace

Setiap VI mempunyai tab Front Panel dan Block Diagram dalam window utama. Front Panel mode **Edit** menampilkan grid; drag item untuk memindahkan dan drag handle kanan-bawah untuk resize. Bounds di-snap ke 10 pixel dan disimpan dalam proyek. Mode **Operate** mengubah boolean dengan click serta numeric/string/array dengan double-click.

Panel item terikat ke node terminal melalui `terminal_node_id`. Control menjadi input runtime dan indicator/chart menerima nilai sink setelah result. Migrasi v2 menghasilkan posisi awal deterministik yang dapat disusun ulang.

## Running dan Debugging

- F5 menjalankan sekali di background.
- F6 menjalankan tick berulang dalam satu session sehingga Feedback mempertahankan state.
- Shift+F6 meminta cancellation.
- Pilih node dan tekan **Breakpoint** untuk toggle breakpoint.
- Pilih wire dan tekan **Probe** untuk mencatat value preview.
- Debugger Trace menyediakan Pause, Resume, dan Step. Compute node memakai satu worker agar dispatch deterministik. Wait/producer sinkronisasi berjalan pada worker khusus agar Queue Get sebelum Queue Put tidak deadlock; urutan completion primitive concurrent tidak dijamin.

Stop adalah cooperative cancellation. Delay, timed loop, synchronization waits, dan bounded network operations merespons cancellation. TCP memakai nonblocking connect dan polling I/O; pemanggilan resolver OS yang sedang berjalan tidak dapat dihentikan oleh Python tetapi diisolasi tanpa socket dan tidak menahan shutdown. Plugin yang tidak mengikuti API dapat tetap lambat berhenti.

## Visual Structures

Tambahkan **Case Structure** atau **For Loop Structure**. Pilih node dan tekan **Open Structure**; untuk Case pilih region True/False. **Root Diagram** kembali ke graph utama.

For body berisi Value Tunnel, Iteration Terminal, dan Output Tunnel. Tepat satu output tunnel wajib menghasilkan nilai tiap iterasi. `max_iterations` mencegah array tak terbatas. Case memilih satu subdiagram berdasarkan selector. Legacy Functional nodes tetap tersedia untuk proyek lama dan bukan nested visual frames.

## Synchronization

- Queue: FIFO consume-once dengan capacity/backpressure.
- Notifier: latest value plus generation.
- Named Event: occurrence payload plus generation.
- Channel: typed bounded message mode.

Timeout 0 bersifat non-blocking. Resource otomatis ditutup di akhir session dan reference dari session lain ditolak.

## Network

TCP bekerja pada bytes dengan read `up_to`, `exactly`, atau `until_delimiter`. UDP memproses datagram dan source address tanpa jaminan delivery; bind wildcard harus ditulis eksplisit sebagai `0.0.0.0` karena host kosong ditolak. Modbus TCP mendukung FC03 dan FC06 dengan alamat 0-based dan menolak range yang melewati register 65535. Timeout maksimal 300 detik dan ukuran operasi maksimal 16 MiB.

Serial membutuhkan `pyserial`. OPC UA ditampilkan unavailable karena core hanya menyediakan contract. Jangan memakai node jaringan untuk safety control atau menganggap desktop scheduler real-time.

## Project Migration

Open menerima v1/v2/v3. V1/v2 dimigrasikan in-memory dan save menulis v3. Unknown v3 core fields ditolak; plugin metadata harus berada di `extensions`. Simpan salinan sumber sebelum workflow migrasi massal.
