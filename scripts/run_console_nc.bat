@echo off
chcp 936 >nul
rem 无控制台启动网页控制台（日常用；出错看 logs\app.log）
setlocal
set "PY=%USERPROFILE%\.workbuddy\binaries\python\envs\default\Scripts\python.exe"
set "PYW=%USERPROFILE%\.workbuddy\binaries\python\envs\default\Scripts\pythonw.exe"
cd /d "%~dp0.."

start "" "%PYW%" -m buct_assistant serve
