@echo off
for %%I in ("%~dp0..") do set "ASTRBOT_ROOT=%%~fI"
cd /d "%ASTRBOT_ROOT%"
set PYTHONIOENCODING=utf-8
set PATH=%ASTRBOT_ROOT%\bin;%PATH%
"%ASTRBOT_ROOT%\bin\astrbot.exe" run >> "%ASTRBOT_ROOT%\run-stdout.log" 2>> "%ASTRBOT_ROOT%\run-stderr.log"
