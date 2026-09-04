@echo off
chcp 65001 >nul
setlocal
set "ROOT=%~dp0"
if exist "%ROOT%data\selftest_human.py" (
  set "APP=%ROOT%data"
  set "PY=%ROOT%python\python.exe"
) else (
  set "APP=%ROOT%"
  set "PY=%ROOT%..\python\python.exe"
)
if not exist "%PY%" set "PY=python"
cd /d "%APP%"
echo ========================================
echo  Lisichka human selftest
echo  browser + LLM + auto greet + auto screen
echo ========================================
echo Folder: %CD%
echo Python: %PY%
echo ========================================
"%PY%" selftest_human.py --browser --llm %*
echo.
echo Exit code: %ERRORLEVEL%
echo Log: %APP%\selftest_human.log
pause
endlocal
