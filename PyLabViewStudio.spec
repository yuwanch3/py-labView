# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path


root = Path(SPECPATH)

a = Analysis(
    [str(root / "pylabview_studio.py")],
    pathex=[str(root)],
    binaries=[],
    datas=[(str(root / "examples"), "examples"), (str(root / "docs"), "docs"),
           (str(root / "README.md"), "."), (str(root / "ARCHITECTURE.md"), ".")],
    hiddenimports=["pylabview.app", "pylabview.execution", "pylabview.resources",
                    "pylabview.protocols", "pylabview.plugins", "pylabview.hdl",
                    "pylabview.handlers.core_math", "pylabview.handlers.collections",
                    "pylabview.handlers.structures", "pylabview.handlers.sync", "pylabview.handlers.io",
                    "pylabview.handlers.instrumentation", "pylabview.handlers.vision",
                    "pylabview.handlers.network", "pylabview.handlers.project",
                    "pylabview.handlers.spinning_drop",
                    "pylabview.integrations.capabilities", "pylabview.integrations.visa_adapter",
                    "pylabview.integrations.serial_adapter",
                    "pylabview.integrations.opcua_adapter", "pylabview.integrations.vision_adapter",
                    "pylabview.integrations.reports_adapter", "pylabview.integrations.isolation",
                    "pylabview.targets"],
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
