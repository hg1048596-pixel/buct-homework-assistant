@echo off
chcp 936 >nul
rem 一键安装依赖（沙箱内 pip 联网受限，走 wheels 离线安装）
setlocal
set "PY=%USERPROFILE%\.workbuddy\binaries\python\envs\default\Scripts\python.exe"
set "PYW=%USERPROFILE%\.workbuddy\binaries\python\envs\default\Scripts\pythonw.exe"
cd /d "%~dp0.."

if not exist "%PY%" (
  echo [错误] 找不到 Python，请检查路径：
  echo        %PY%
  pause
  exit /b 1
)

set "BUCT_PY=%PY%"
echo [1/3] 下载依赖包 ...
"%PY%" tools\bootstrap_wheels.py
if errorlevel 1 goto err
echo [2/3] 安装 ...
"%PY%" tools\bootstrap_wheels.py install
if errorlevel 1 goto err
echo [3/3] 自检 ...
"%PY%" -m buct_assistant selftest
if errorlevel 1 goto err
echo.
echo [完成] 依赖就绪。
pause
exit /b 0

:err
echo.
echo [错误] 安装失败，请看上面的提示。
pause
exit /b 1
