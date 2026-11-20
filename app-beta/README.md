# PyLabView Studio Development Build — Ganti Mode

Folder ini menyediakan executable development Windows untuk menguji fitur terbaru tanpa mengganti release stabil `v10.0.0`.

## Isi Development Build

`PyLabViewStudio-dev.exe` menggunakan basis fitur PyLabView Studio 10.0.0 dan menyertakan kembali fitur **Ganti Mode** melalui menu `Mode > Ganti Mode`.

Saat Ganti Mode dijalankan, aplikasi akan:

1. Menjalankan jalur Global Stop untuk menghentikan motor dan measurement aktif.
2. Menunggu runtime serta antrean pembuatan Analysis PNG selesai.
3. Menutup resource camera dan serial melalui cleanup runtime.
4. Menghapus workspace lama dan membuat runtime/controller baru.
5. Membersihkan state session lama, lalu menampilkan kembali pilihan Standard Mode atau Manual RPM Mode.
6. Memulai mode berikutnya dengan workspace dan session state yang fresh.

## Mengapa Dipisahkan dari Release Stabil?

Fitur Ganti Mode sudah dapat berjalan dan mekanisme stop/reset-nya dirancang aman. Namun, fitur ini tetap ditempatkan pada development build karena masih memerlukan pengujian lebih lanjut dalam penggunaan nyata, terutama untuk:

- pergantian mode berulang kali dalam satu peluncuran aplikasi;
- verifikasi motor benar-benar berhenti sebelum workspace diganti;
- cleanup dan pembukaan ulang koneksi Arduino/serial;
- pelepasan dan pembukaan ulang camera;
- penyelesaian antrean Analysis PNG saat mode diganti;
- pemisahan folder session dan data measurement antar-mode;
- pengujian recovery ketika hardware terputus atau tidak merespons.

Pemisahan ini menjaga release stabil `v10.0.0` tetap tidak berubah, sementara fitur Ganti Mode dapat diuji secara khusus sebelum dipromosikan ke release produksi berikutnya.

## File

Folder repository berisi:

```text
app-beta/
├── PyLabViewStudio-dev.exe
└── README.md
```

Artifact hasil GitHub Actions berisi:

```text
app-beta/
├── PyLabViewStudio-dev.exe
├── PyLabViewStudio-dev.exe.sha256
├── BUILD-INFO.txt
└── README.md
```

Build development diberi versi dinamis `10.0.0-dev+<commit>` pada aplikasi dan metadata Windows `.exe`. Build ini dibuat dari branch `main`, tidak memindahkan tag stabil, dan tidak mengganti asset release `v10.0.0`.

Executable yang disimpan langsung dalam folder ini memiliki versi `10.0.0-dev+7efad88`.

## Mengunduh

1. Buka tab **Actions** pada repository GitHub.
2. Pilih workflow **Build Windows Development**.
3. Buka run terbaru yang berhasil.
4. Unduh artifact bernama `PyLabViewStudio-Development-<commit>`.
5. Verifikasi `PyLabViewStudio-dev.exe` menggunakan file SHA-256 yang disertakan.

> **Peringatan:** development build ditujukan untuk pengujian fitur terbaru dan belum dianggap sebagai release produksi stabil. Tetap gunakan emergency stop fisik, interlock, dan prosedur keselamatan hardware saat melakukan pengujian motor.
