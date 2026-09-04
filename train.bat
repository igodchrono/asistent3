@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0data"
set "PY=%~dp0python\python.exe"
if not exist "%PY%" (
  where python >nul 2>&1 && set "PY=python"
)
echo Training micro-models...
"%PY%" train_model.py %*
pause
endlocal
