@echo off
chcp 936 >nul
rem 卸载任务计划
setlocal
set "PY=%USERPROFILE%\.workbuddy\binaries\python\envs\default\Scripts\python.exe"
set "PYW=%USERPROFILE%\.workbuddy\binaries\python\envs\default\Scripts\pythonw.exe"
cd /d "%~dp0.."

schtasks /Delete /TN "BUCT-HW-Assistant" /F
echo.
pause
