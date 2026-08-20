# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path


root = Path(SPECPATH)

a = Analysis(
    [str(root / "pylabview_studio.py")],
    pathex=[str(root)],
    binaries=[],
    datas=[(str(root / "examples" / "simulated_monitor.json"), "examples")],
    hiddenimports=["pylabview.app"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="PyLabViewStudio",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    version=str(root / "version_info.txt"),
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
