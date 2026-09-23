@echo off
chcp 936 >nul
rem 带控制台启动网页控制台（调试用，能看到日志）
setlocal
set "PY=%USERPROFILE%\.workbuddy\binaries\python\envs\default\Scripts\python.exe"
set "PYW=%USERPROFILE%\.workbuddy\binaries\python\envs\default\Scripts\pythonw.exe"
cd /d "%~dp0.."

echo 控制台地址： http://127.0.0.1:8765
"%PY%" -m buct_assistant serve
pause
