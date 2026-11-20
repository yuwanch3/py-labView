# PyLabView Studio Development Build

Folder ini adalah struktur paket untuk build development Windows yang dibuat oleh workflow **Build Windows Development**.

Artifact hasil GitHub Actions berisi:

```text
app-beta/
├── PyLabViewStudio-dev.exe
├── PyLabViewStudio-dev.exe.sha256
├── BUILD-INFO.txt
└── README.md
```

Build development diberi versi dinamis `10.0.0-dev+<commit>` pada aplikasi dan metadata Windows `.exe`. Build ini dibuat dari branch `main`, tidak memindahkan tag stabil, dan tidak mengganti asset release `v10.0.0`.

## Mengunduh

1. Buka tab **Actions** pada repository GitHub.
2. Pilih workflow **Build Windows Development**.
3. Buka run terbaru yang berhasil.
4. Unduh artifact bernama `PyLabViewStudio-Development-<commit>`.
5. Verifikasi `PyLabViewStudio-dev.exe` menggunakan file SHA-256 yang disertakan.

> Development build ditujukan untuk pengujian fitur terbaru dan belum dianggap sebagai release produksi stabil.
