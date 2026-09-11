@echo off
chcp 65001 >nul
setlocal EnableExtensions
cd /d "%~dp0\.."
set "PY=%CD%\..\python\python.exe"
if not exist "%PY%" set PY=python
echo Selftest CALIBRATION FULL --llm --browser
"%PY%" -u selftest_calibration\run_calibration.py --llm --browser
echo Exit: %ERRORLEVEL%
pause
