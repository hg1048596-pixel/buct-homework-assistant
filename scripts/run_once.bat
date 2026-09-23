@echo off
chcp 936 >nul
rem 单次扫描 + 提醒（供任务计划程序调用）
setlocal
set "PY=%USERPROFILE%\.workbuddy\binaries\python\envs\default\Scripts\python.exe"
set "PYW=%USERPROFILE%\.workbuddy\binaries\python\envs\default\Scripts\pythonw.exe"
cd /d "%~dp0.."

"%PYW%" -m buct_assistant once --quiet
exit /b %errorlevel%
