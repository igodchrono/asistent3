@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "DST=%~dp0..\data\personas\characters"
if not exist "%~dp0..\data" set "DST=%~dp0personas\characters"
if not exist "%DST%" mkdir "%DST%"
echo Копирую в %DST%
xcopy /E /I /Y "%~dp0personas\characters\кошечка" "%DST%\кошечка\"
xcopy /E /I /Y "%~dp0personas\characters\ученый" "%DST%\ученый\"
xcopy /E /I /Y "%~dp0personas\characters\писатель" "%DST%\писатель\"
xcopy /E /I /Y "%~dp0personas\characters\скромница" "%DST%\скромница\"
echo Готово. Перезапусти ассистента.
pause
