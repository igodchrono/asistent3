@echo off
chcp 65001 >nul
setlocal EnableExtensions
cd /d "%~dp0\.."

echo ========================================
echo  Selftest CALIBRATION
echo  (folder selftest_calibration — deletable)
echo ========================================
echo Folder: %CD%

set "PY=%CD%\..\python\python.exe"
if not exist "%PY%" set PY=python

echo Using: %PY%
echo.

"%PY%" -u selftest_calibration\run_calibration.py %*
set ERR=%ERRORLEVEL%
echo.
echo Exit: %ERR%
echo Log: data\selftest_calibration_run.log
echo.
echo To delete tests: remove folder data\selftest_calibration
pause
exit /b %ERR%
