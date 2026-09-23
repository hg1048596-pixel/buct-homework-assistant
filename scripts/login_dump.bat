@echo off
chcp 936 >nul
rem 登录北化在线并 dump 页面到 calibration\raw\（校准用）
setlocal
set "PY=%USERPROFILE%\.workbuddy\binaries\python\envs\default\Scripts\python.exe"
set "PYW=%USERPROFILE%\.workbuddy\binaries\python\envs\default\Scripts\pythonw.exe"
cd /d "%~dp0.."

"%PY%" tools\dump_pages.py
echo.
pause
