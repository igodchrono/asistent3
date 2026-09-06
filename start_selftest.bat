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

echo ========================================
echo  asistent3 plugin selftest
echo  2 passes x each plugin + log
echo ========================================
echo Folder: %CD%
echo Python: %PY%
echo ========================================

if not exist "selftest_plugins.py" (
  echo ERROR: selftest_plugins.py not found in %CD%
  pause
  exit /b 2
)

"%PY%" selftest_plugins.py --rounds 2 --browser --llm %*

echo.
echo Exit code: %ERRORLEVEL%
echo Log: %APP%\selftest_plugins.log
echo Log: %APP%\selftest_human.log
echo ========================================
pause
endlocal
