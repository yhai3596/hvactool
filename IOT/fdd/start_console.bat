@echo off
rem FDD 本地控制台启动器 — 双击即用(自动打开浏览器)
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo [错误] 找不到项目虚拟环境 .venv\Scripts\python.exe
  echo 请先在 fdd 目录建立 venv(Python 3.12)并安装项目依赖。
  pause
  exit /b 1
)
".venv\Scripts\python.exe" app\fdd_console.py %*
pause
