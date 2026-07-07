@echo off
chcp 65001 >nul
title HVAC 工具站
echo 正在启动 HVAC 工具站: http://127.0.0.1:8137
start "" http://127.0.0.1:8137
python "%~dp0server.py"
pause
