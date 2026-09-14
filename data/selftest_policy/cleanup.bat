@echo off
chcp 65001 >nul
cd /d "%~dp0\.."
if exist "..\python\python.exe" (
  "..\python\python.exe" -u selftest_policy\cleanup.py
) else (
  python -u selftest_policy\cleanup.py
)
echo.
pause
