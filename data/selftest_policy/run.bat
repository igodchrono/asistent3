@echo off
chcp 65001 >nul
cd /d "%~dp0\.."
if exist "..\python\python.exe" (
  "..\python\python.exe" -u selftest_policy\run_policy_test.py
) else (
  python -u selftest_policy\run_policy_test.py
)
echo.
pause
