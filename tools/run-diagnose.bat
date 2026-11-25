@echo off
rem Запуск диагностики IIS без возни с ExecutionPolicy.
rem Положите этот файл рядом с diagnose-iis.ps1 и запустите двойным щелчком
rem (лучше: правый клик -> "Запуск от имени администратора").
chcp 65001 >nul
setlocal
cd /d "%~dp0"

if not exist "%~dp0diagnose-iis.ps1" (
  echo Рядом с этим файлом нет diagnose-iis.ps1
  pause
  exit /b 1
)

echo Запуск диагностики IIS...
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0diagnose-iis.ps1" %*
echo.
echo === Готово. Скопируйте текст выше или сохраните в файл. ===
pause
