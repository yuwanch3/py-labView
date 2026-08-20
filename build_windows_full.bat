@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if errorlevel 1 exit /b 1
py -3 -m pip install -r requirements-build.txt -r requirements-optional.txt
if errorlevel 1 exit /b 1
py -3 -m PyInstaller --noconfirm --clean PyLabViewStudioFull.spec
if errorlevel 1 exit /b 1

echo Full build selesai: dist\PyLabViewStudioFull.exe
echo NI-DAQmx tetap memerlukan driver/runtime vendor NI terpisah.
endlocal
