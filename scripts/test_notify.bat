@echo off
chcp 936 >nul
rem 测试提醒渠道是否配置正确
setlocal
set "PY=%USERPROFILE%\.workbuddy\binaries\python\envs\default\Scripts\python.exe"
set "PYW=%USERPROFILE%\.workbuddy\binaries\python\envs\default\Scripts\pythonw.exe"
cd /d "%~dp0.."

"%PY%" tools\test_notify.py
echo.
pause
