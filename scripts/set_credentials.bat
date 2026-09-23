@echo off
chcp 936 >nul
rem 录入学号密码（DPAPI 加密，只存本机）
setlocal
set "PY=%USERPROFILE%\.workbuddy\binaries\python\envs\default\Scripts\python.exe"
set "PYW=%USERPROFILE%\.workbuddy\binaries\python\envs\default\Scripts\pythonw.exe"
cd /d "%~dp0.."

"%PY%" -m buct_assistant set-credentials
echo.
pause
