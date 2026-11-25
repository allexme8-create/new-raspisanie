Как запустить (Windows)
=======================

Подробно — в docs\how-to-download.md репозитория.

1) Диагностика IIS (ничего не меняет), PowerShell ОТ АДМИНИСТРАТОРА:
   powershell -ExecutionPolicy Bypass -File .\diagnose-iis.ps1

2) Резервный сервер без IIS:
   - скопировать serve_lan.py и serve.bat в папку с расписанием
     (рядом с info_panel_1.html), например C:\inetpub\wwwroot\raspisanie
   - двойной щелчок по serve.bat
   - открыть http://localhost:8000/info_panel_1.html
   - адрес для других устройств в сети скрипт напечатает в консоли

3) Доступ из локальной сети (PowerShell от администратора):
   New-NetFirewallRule -DisplayName "Raspisanie HTTP 8000" -Direction Inbound -Protocol TCP -LocalPort 8000 -Action Allow -Profile Private,Domain
