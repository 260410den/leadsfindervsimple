@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 (
    where python >nul 2>nul
    if errorlevel 1 (
        echo Python belum ditemukan. Pasang Python 3 untuk Windows lalu jalankan file ini lagi.
        pause
        exit /b 1
    )
    set "PYTHON=python"
) else (
    set "PYTHON=py"
)
if not exist ".venv\Scripts\python.exe" (
    echo Menyiapkan lingkungan Python...
    %PYTHON% -m venv .venv
    if errorlevel 1 goto failed
)
echo Memastikan paket aplikasi tersedia...
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 goto failed
echo Membuka Lead Finder di browser...
start "" http://127.0.0.1:5001
.venv\Scripts\python.exe -m flask --app app run --host 127.0.0.1 --port 5001 --no-reload --no-debugger
goto end
:failed
echo Ada masalah saat menyiapkan aplikasi. Pastikan internet tersedia untuk pemasangan paket.
pause
:end
endlocal
