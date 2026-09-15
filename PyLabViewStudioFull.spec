# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
from PyInstaller.utils.hooks import collect_all

root = Path(SPECPATH)
hiddenimports = ["pylabview.app", "pylabview.integrations.capabilities", "pylabview.integrations.nidaqmx_adapter",
                 "pylabview.integrations.visa_adapter", "pylabview.integrations.opcua_adapter",
                 "pylabview.integrations.serial_adapter",
                 "pylabview.integrations.vision_adapter", "pylabview.integrations.reports_adapter",
                 "pylabview.integrations.isolation", "pylabview.hdl", "pylabview.targets"]
binaries, datas = [], [(str(root / "examples"), "examples"), (str(root / "docs"), "docs"),
                       (str(root / "README.md"), "."), (str(root / "ARCHITECTURE.md"), ".")]
for package in ("nidaqmx", "pyvisa", "serial", "asyncua", "cv2", "numpy", "openpyxl", "docx", "reportlab"):
    package_datas, package_binaries, package_hidden = collect_all(package)
    datas += package_datas; binaries += package_binaries; hiddenimports += package_hidden

a = Analysis([str(root / "pylabview_studio.py")], pathex=[str(root)], binaries=binaries, datas=datas,
             hiddenimports=hiddenimports, hookspath=[], hooksconfig={}, runtime_hooks=[], excludes=[], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name="PyLabViewStudioFull", debug=False,
          bootloader_ignore_signals=False, strip=False, upx=True, console=False,
          version=str(root / "version_info.txt"), disable_windowed_traceback=False,
          argv_emulation=False, target_arch=None, codesign_identity=None, entitlements_file=None)
