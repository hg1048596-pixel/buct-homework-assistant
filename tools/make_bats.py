# -*- coding: utf-8 -*-
"""生成 scripts/ 下的 .bat 与 task.xml。

为什么要有这个生成器：cmd.exe 按控制台代码页（中文 Windows 默认 936/GBK）读取 .bat，
如果 .bat 存成 UTF-8，中文注释里的多字节序列会被 GBK 当成前导字节吞掉后面的字符，
导致注释行被拆成命令报错（典型症状：'侊紙DPAPI' 不是内部或外部命令）。
所以 .bat 一律用 **GBK** 写盘；任务计划 XML 必须是 **UTF-16LE + BOM**。

改动 .bat 内容请改这里，然后运行：python tools/make_bats.py
"""
import os

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(BASE, "scripts")

# 用 %USERPROFILE% 而不是写死的绝对路径：不暴露 Windows 用户名，
# 且仓库克隆到任何机器上都能直接用（前提是 WorkBuddy 装在默认位置）。
PY = r"%USERPROFILE%\.workbuddy\binaries\python\envs\default\Scripts\python.exe"
PYW = r"%USERPROFILE%\.workbuddy\binaries\python\envs\default\Scripts\pythonw.exe"

HEAD = """@echo off
chcp 936 >nul
rem {desc}
setlocal
set "PY={py}"
set "PYW={pyw}"
cd /d "%~dp0.."
"""

BATS = {
    "setup_env.bat": HEAD.format(desc="一键安装依赖（沙箱内 pip 联网受限，走 wheels 离线安装）", py=PY, pyw=PYW) + """
if not exist "%PY%" (
  echo [错误] 找不到 Python，请检查路径：
  echo        %PY%
  pause
  exit /b 1
)

set "BUCT_PY=%PY%"
echo [1/3] 下载依赖包 ...
"%PY%" tools\\bootstrap_wheels.py
if errorlevel 1 goto err
echo [2/3] 安装 ...
"%PY%" tools\\bootstrap_wheels.py install
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
""",

    "set_credentials.bat": HEAD.format(desc="录入学号密码（DPAPI 加密，只存本机）", py=PY, pyw=PYW) + """
"%PY%" -m buct_assistant set-credentials
echo.
pause
""",

    "login_dump.bat": HEAD.format(desc="登录北化在线并 dump 页面到 calibration\\raw\\（校准用）", py=PY, pyw=PYW) + """
"%PY%" tools\\dump_pages.py
echo.
pause
""",

    "run_console.bat": HEAD.format(desc="带控制台启动网页控制台（调试用，能看到日志）", py=PY, pyw=PYW) + """
echo 控制台地址： http://127.0.0.1:8765
"%PY%" -m buct_assistant serve
pause
""",

    "run_console_nc.bat": HEAD.format(desc="无控制台启动网页控制台（日常用；出错看 logs\\app.log）", py=PY, pyw=PYW) + """
start "" "%PYW%" -m buct_assistant serve
""",

    "stop_console.bat": HEAD.format(desc="停止正在运行的助手（控制台 + 后台同步进程）", py=PY, pyw=PYW) + """
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
""",

    "run_once.bat": HEAD.format(desc="单次扫描 + 提醒（供任务计划程序调用）", py=PY, pyw=PYW) + """
"%PYW%" -m buct_assistant once --quiet
exit /b %errorlevel%
""",

    "test_notify.bat": HEAD.format(desc="测试提醒渠道是否配置正确", py=PY, pyw=PYW) + """
"%PY%" tools\\test_notify.py
echo.
pause
""",

    "install_task.bat": HEAD.format(desc="注册 Windows 任务计划：每 30 分钟扫描一次", py=PY, pyw=PYW) + """
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
""",

    "uninstall_task.bat": HEAD.format(desc="卸载任务计划", py=PY, pyw=PYW) + """
schtasks /Delete /TN "BUCT-HW-Assistant" /F
echo.
pause
""",
}

TASK_XML = """<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>北化在线作业助手 - 定时扫描未提交作业并提醒</Description>
  </RegistrationInfo>
  <Triggers>
    <CalendarTrigger>
      <StartBoundary>2026-09-24T08:00:00+08:00</StartBoundary>
      <Enabled>true</Enabled>
      <Repetition>
        <Interval>PT30M</Interval>
        <StopAtDurationEnd>false</StopAtDurationEnd>
      </Repetition>
      <ScheduleByDay>
        <DaysInterval>1</DaysInterval>
      </ScheduleByDay>
    </CalendarTrigger>
    <LogonTrigger>
      <Enabled>true</Enabled>
      <Delay>PT2M</Delay>
    </LogonTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>true</RunOnlyIfNetworkAvailable>
    <ExecutionTimeLimit>PT10M</ExecutionTimeLimit>
    <Hidden>true</Hidden>
    <WakeToRun>false</WakeToRun>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{pyw}</Command>
      <Arguments>-m buct_assistant once --quiet</Arguments>
      <WorkingDirectory>{base}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"""


def main() -> None:
    os.makedirs(SCRIPTS, exist_ok=True)
    for name, text in BATS.items():
        path = os.path.join(SCRIPTS, name)
        # 关键：GBK 写盘，并把换行统一成 CRLF，cmd 才吃得下
        with open(path, "w", encoding="gbk", errors="replace", newline="\r\n") as f:
            f.write(text.lstrip("\n"))
        print(f"[bat ] {name} ({os.path.getsize(path)}B, gbk)")

    xml = TASK_XML.format(pyw=PYW, base=BASE)
    xml_path = os.path.join(SCRIPTS, "task.xml")
    with open(xml_path, "w", encoding="utf-16") as f:
        f.write(xml)
    print(f"[xml ] task.xml ({os.path.getsize(xml_path)}B, utf-16)")


if __name__ == "__main__":
    main()
