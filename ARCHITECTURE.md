# Arsitektur PyLabView Studio 3

## Boundary Modul

- `model.py`: compatibility model `Project`, `VirtualInstrument`, root `Graph`, persisted `subdiagrams`, connector, dan strict schema object validation.
- `typesystem.py`: wire types, coercion, `Waveform`, dan `ErrorCluster`.
- `persistence.py`: load v1/v2/v3 dan atomic v3 save.
- `execution.py`: `CancellationToken`, debugger trace, `RunSession`, dan asynchronous `RunController`.
- `resources.py`: session-scoped queue, notifier, event, channel, dan ownership validation.
- `protocols.py`: bounded TCP/UDP, Modbus TCP FC03/FC06, optional pyserial detection, dan OPC UA contract/capability.
- `plugins.py`: builtin/name-spaced registry dan entry-point discovery.
- `runtime.py`: compatibility scheduler/evaluator. Debug mode memakai satu worker; normal mode tetap menjalankan level independen secara paralel.
- `front_panel.py`, `canvas_editor.py`, `app.py`: Tk presentation layer. Worker tidak memanggil Tk.

Model tetap evolusioner agar consumer v2 tidak rusak. Builtin node mempertahankan ID lama; plugin baru wajib memakai type ID namespaced.

## Execution

`RunController` membuat coordinator thread dan satu `RunSession`. UI memanggil `drain_events()` melalui `after(30, ...)`; setiap event result membawa snapshot result tick-nya sendiri. Update control disalin di bawah lock pada batas tick. Synchronous `DataflowRuntime.run()` membuat session sementara dan menutup semua resource setelah result selesai.

Cancellation bersifat kooperatif. Delay/timed loop memakai `CancellationToken.wait`; resource waits memeriksa token setiap maksimal 50 ms. Socket memakai timeout terbatas. Python tidak dapat menghentikan plugin worker yang mengabaikan kontrak cancellation.

Feedback adalah satu-satunya dependency-breaking edge. Scheduler mengabaikan incoming edge menuju Feedback saat topological ordering, membaca nilai state sebelumnya, lalu commit input setelah tick sukses. Graph cycle tanpa Feedback tetap ditolak.

## Debugger

Debugger memeriksa breakpoint sebelum node dikirim, mencatat monotonic sequence/timestamp, dan membatasi trace. Probe memakai endpoint wire yang stabil. Pause menghentikan dispatch berikutnya; pekerjaan yang sudah berjalan tidak dihentikan paksa. Compute node memakai satu worker saat debug. Primitive wait dan action sinkronisasi memakai pool terpisah; setiap primitive dalam satu level mendapat slot agar wait tidak menahan worker producer. Jumlahnya dibatasi `max_sync_workers` dan graph di atas batas ditolak. Completion primitive tersebut dapat concurrent walaupun urutan dispatch tetap deterministik.

## Structures

VI mempunyai root graph dan dictionary subdiagram. `visual_case` menunjuk True/False region. `visual_for` menunjuk body region; `structure_input`, `structure_output`, dan `iteration_terminal` menjadi boundary contract. Runtime mengeksekusi subdiagram melalui session/cancellation/debugger yang sama. Legacy functional structures tidak diam-diam berubah makna.

## Resources dan Protocol

Semua handle dibungkus `ResourceRef` dengan UUID owner dan dimiliki satu `ResourceManager`. Queue adalah consume-once FIFO; notifier/event memakai generation; channel adalah bounded typed message queue. Close membangunkan waiter. State dan cached resource memakai scope `(VI, diagram, node)`.

TCP dan UDP memakai stdlib `socket`. TCP resolve/connect/read/write dipoll terhadap deadline dan cancellation; resolver OS yang tidak dapat dihentikan diisolasi pada maksimal delapan daemon resolver tanpa memiliki socket. Modbus memvalidasi MBAP transaction/protocol/length/unit, function, exception, byte count, dan FC06 echo serta menutup stream setelah mismatch. Serial hanya dimuat bila pyserial tersedia. OPC UA core tidak mempunyai evaluator jaringan dan capability `available=False`.

## Persistence dan Trust

V3 menolak unknown core fields dan menyediakan dictionary `extensions` pada root, panel, dan panel item. Save memakai temporary file, flush, `fsync`, dan `os.replace`. Migrasi v2 menghasilkan panel bounds deterministik dan mempertahankan legacy nodes.

Canonical `data_root` bukan process sandbox. Plugin entry point menjalankan Python tepercaya dalam proses aplikasi, tanpa `eval`/`exec` dan tanpa auto-install. Deployment yang membuka proyek/plugin tak tepercaya memerlukan isolasi OS/proses sendiri.
