@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0\.."

where py >nul 2>&1
if %ERRORLEVEL%==0 (
    set "PY=py -3"
) else (
    set "PY=python"
)

%PY% "scripts\resetar_senha.py" --gui
endlocal
