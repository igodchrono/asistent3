@echo off
chcp 65001 >nul
cd /d "%~dp0"
if exist "..\..\python\python.exe" (
  "..\..\python\python.exe" -m py_compile _guard.py
) else (
  python -m py_compile _guard.py
)
echo Скомпилировано. Для релиза: filter.json держать отдельно, policy.py можно отдать — чат его не читает.
pause
