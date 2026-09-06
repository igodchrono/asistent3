@echo off
chcp 65001 >nul
setlocal
set "ROOT=%~dp0"
if exist "%ROOT%data\selftest_plugins.py" (
  set "APP=%ROOT%data"
  set "PY=%ROOT%python\python.exe"
) else if exist "%ROOT%selftest_plugins.py" (
  set "APP=%ROOT%"
  set "PY=%ROOT%..\python\python.exe"
) else (
  set "APP=%ROOT%data"
  set "PY=%ROOT%python\python.exe"
)
if not exist "%PY%" set "PY=python"
cd /d "%APP%"
echo Quick selftest (1 pass, no browser)
"%PY%" selftest_plugins.py --rounds 1 --quick %*
echo Exit: %ERRORLEVEL%  Log: %APP%\selftest_plugins.log
pause
endlocal
