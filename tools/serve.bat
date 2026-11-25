@echo off
rem ---------------------------------------------------------------------------
rem  Запуск локального HTTP-сервера для папки с расписанием (info_panel_1.html)
rem  Положите этот файл и serve_lan.py в папку с расписанием и запустите двойным
rem  щелчком. Окно закрывать нельзя — пока оно открыто, страница доступна в сети.
rem ---------------------------------------------------------------------------
chcp 65001 >nul
setlocal
cd /d "%~dp0"

set PORT=8000

rem ищем Python
set PY=
where py >nul 2>nul && set PY=py
if "%PY%"=="" (where python >nul 2>nul && set PY=python)
if "%PY%"=="" (
  echo Python не найден.
  echo Установите его командой:  winget install -e --id Python.Python.3.12
  echo или запустите сервер вручную одним из способов из docs\windows10-http-server.md
  pause
  exit /b 1
)

echo.
echo Открываю http://localhost:%PORT%/info_panel_1.html
echo Закрыть это окно = остановить сервер.
echo.

%PY% "%~dp0serve_lan.py" "%~dp0" -p %PORT% --open
pause
