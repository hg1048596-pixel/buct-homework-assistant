@echo off
chcp 936 >nul
rem 停止正在运行的助手（控制台 + 后台同步进程）
setlocal
set "PY=%USERPROFILE%\.workbuddy\binaries\python\envs\default\Scripts\python.exe"
set "PYW=%USERPROFILE%\.workbuddy\binaries\python\envs\default\Scripts\pythonw.exe"
cd /d "%~dp0.."

set "FOUND=0"
for /f "tokens=5" %%a in ('netstat -ano ^| findstr /C:":8765 " ^| findstr "LISTENING"') do (
    for /f "tokens=1" %%n in ('tasklist /FI "PID eq %%a" ^| findstr /I "python"') do (
        echo 结束控制台进程 PID=%%a
        taskkill /F /PID %%a >nul 2>&1
        set "FOUND=1"
    )
)
if "%FOUND%"=="0" echo 控制台未在运行（端口 8765 无监听）

powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*cache-course*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"

echo.
echo 已停止。重新启动请双击 run_console.bat
pause
