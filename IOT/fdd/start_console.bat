@echo off
rem FDD local console launcher - double-click to run (opens browser automatically)
rem NOTE: keep this file ASCII-only. A UTF-8/GBK mismatch makes cmd.exe abort parsing
rem before reaching pause, which looks like the window flashing and closing instantly.
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] Project venv not found: .venv\Scripts\python.exe
  echo Create the venv ^(Python 3.12^) under the fdd directory and install deps first.
  echo.
  pause
  exit /b 1
)

echo ============================================================
echo  FDD local console starting ^(local machine only^)
echo  URL : http://127.0.0.1:8765/
echo  Stop: close this window or press Ctrl+C
echo ============================================================
echo.

".venv\Scripts\python.exe" "app\fdd_console.py" %*

echo.
echo [console stopped] exit code %errorlevel%
pause
