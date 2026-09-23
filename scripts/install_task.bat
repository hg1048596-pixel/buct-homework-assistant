@echo off
chcp 936 >nul
rem 注册 Windows 任务计划：每 30 分钟扫描一次
setlocal
set "PY=%USERPROFILE%\.workbuddy\binaries\python\envs\default\Scripts\python.exe"
set "PYW=%USERPROFILE%\.workbuddy\binaries\python\envs\default\Scripts\pythonw.exe"
cd /d "%~dp0.."

schtasks /Create /TN "BUCT-HW-Assistant" /XML "%~dp0task.xml" /F
if errorlevel 1 (
  echo [错误] 注册失败。
  pause
  exit /b 1
)
echo [完成] 已注册，立即试跑一次 ...
schtasks /Run /TN "BUCT-HW-Assistant"
echo.
echo 说明：任务以「仅在用户登录时运行」方式注册，因为凭据用 DPAPI 绑定当前用户加密，
echo       换成其它账户或系统账户运行会解密失败。
pause
