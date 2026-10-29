@echo off
for %%I in ("%~dp0..") do set "ASTRBOT_ROOT=%%~fI"
cd /d "%ASTRBOT_ROOT%\mock"
"%ASTRBOT_ROOT%\tools\astrbot\Scripts\python.exe" "%ASTRBOT_ROOT%\mock\mock_llm.py" >> "%ASTRBOT_ROOT%\mock\mock_llm.out.log" 2>> "%ASTRBOT_ROOT%\mock\mock_llm.err.log"
