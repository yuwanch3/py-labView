@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if errorlevel 1 (
    echo Python launcher "py" tidak ditemukan. Pasang Python 3.10+ dari python.org.
    exit /b 1
)

py -3 -c "import tkinter" >nul 2>nul
if errorlevel 1 (
    echo tkinter tidak tersedia. Ubah instalasi Python dan aktifkan Tcl/Tk.
    exit /b 1
)

py -3 -m PyInstaller --version >nul 2>nul
if errorlevel 1 (
    echo Memasang PyInstaller...
    py -3 -m pip install -r requirements-build.txt
    if errorlevel 1 exit /b 1
)

py -3 -m PyInstaller --noconfirm --clean PyLabViewStudio.spec
if errorlevel 1 exit /b 1

echo Build selesai: dist\PyLabViewStudio.exe
endlocal
