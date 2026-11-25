# Порт 80 отвечает `Server: Microsoft-HTTPAPI/2.0` → это НЕ IIS

## Что показывает твой вывод

```
HTTP/1.1 404 Not Found
Server: Microsoft-HTTPAPI/2.0
Content-Type: text/html; charset=us-ascii
```

`Microsoft-HTTPAPI/2.0` — это «HTTP.sys» (драйвер ядра Windows) без IIS.
Значит на порту 80 слушает **не сайт IIS**, а что-то зарегистрировавшееся в
`http.sys`: обычно **World Wide Web Publishing Service (W3SVC, IIS) не запущен**,
а порт занят другой службой/приложением (часто — «World Wide Web Publishing
Service» чужого продукта, WSUS, SQL Server Reporting Services, TeamViewer,
Skype, «Сетевое обнаружение», иногда — сама служба IIS, но с пустой
конфигурацией и без сайта `Default Web Site`).

Второй симптом из твоего вывода:

```
Get-ChildItem : Диск с именем "IIS" не существует
```

— модуль `WebAdministration` не загружен (не установлена роль
«Веб-сервер (IIS)» целиком / модуль управления), либо PowerShell не видит
провайдер, потому что компонент IIS не установлен. Плюс `icacls` показал, что
права `IIS_IUSRS` на папку уже есть — с доступом к файлам всё нормально, дело
именно в том, кто слушает порт 80.

---

## Шаг 1. Понять, кто слушает порт 80

```powershell
Get-NetTCPConnection -LocalPort 80 -State Listen |
    Select-Object LocalAddress, OwningProcess,
        @{n='Process';e={(Get-Process -Id $_.OwningProcess).ProcessName}},
        @{n='Path';e={(Get-Process -Id $_.OwningProcess).Path}} | Format-List
```

или проще:

```cmd
netstat -ano | findstr ":80 "
tasklist /svc | findstr /i "PID"
```

Если `Process` = `System` (PID 4) — это нормально: порт 80 держит `http.sys`,
а конкретную регистрацию показывает:

```cmd
netsh http show servicestate
```

В выводе ищи блок `Request queue` → `Registered URLs`. Там будет видно, что
зарегистрировано: `http://+:80/` (IIS) или что-то вроде
`http://+:80/ReportingServices/`, `http://+:80/Temporary_Listen_Addresses/`.

---

## Шаг 2. Запустить IIS

```powershell
Get-Service W3SVC, WAS | Format-Table Name, Status, StartType
Start-Service W3SVC
```

Если `W3SVC` **отсутствует** в списке — роль IIS не установлена:

```powershell
Enable-WindowsOptionalFeature -Online -FeatureName IIS-WebServerRole,IIS-WebServer,IIS-StaticContent,IIS-DefaultDocument,IIS-HttpErrors,IIS-ManagementConsole -All
```

(или: Панель управления → «Программы и компоненты» → «Включение или отключение
компонентов Windows» → Internet Information Services → отметить «Веб-сервер
(IIS)» + «Средства управления». После установки `IIS:\` в PowerShell появится.)

Проверить, что IIS запустился и держит порт 80:

```powershell
Get-Service W3SVC
Import-Module WebAdministration
Get-ChildItem IIS:\Sites | Format-List Name, State, PhysicalPath, Bindings
```

Если теперь `curl.exe -I http://127.0.0.1/` отвечает `Server: Microsoft-IIS/10.0`
— IIS работает, идём к шагу 3.

---

## Шаг 3. Если IIS запустить не удалось: порт 80 занят другим приложением

Симптом: `Start-Service W3SVC` падает с ошибкой 183 («Невозможно запустить
службу... уже выполняется») / 1068, а `netsh http show servicestate` показывает
чужие URL.

Два выхода:

**А. Освободить порт 80.** Найдите процесс из шага 1 и остановите службу,
которая держит `http://+:80/` (часто это «WSUS», «SQL Server Reporting
Services», «BranchCache», панель какого-нибудь ПО). Отключать навсегда:
`Set-Service <Имя> -StartupType Disabled`.

**Б. Перевести IIS на другой порт** (быстро и безопасно):

```powershell
Import-Module WebAdministration
Set-ItemProperty "IIS:\Sites\Default Web Site" -Name bindings `
    -Value @{protocol='http'; bindingInformation='*:8080:'}
Start-Website "Default Web Site"
```

Тогда адрес панели: `http://127.0.0.1:8080/raspisanie/`, а для других
устройств в сети — `http://192.168.x.x:8080/raspisanie/`
(+ правило брандмауэра на 8080).

---

## Шаг 4. Пока IIS разбирается — панель можно уже показывать

Раз порт 80 занят чужим сервисом, а панель нужна на экране, самый короткий путь —
Python-сервер из этого репозитория на свободном порту 8000:

```cmd
cd /d C:\inetpub\wwwroot\raspisanie
python serve_lan.py . -p 8000
```

→ `http://localhost:8000/info_panel_1.html`,
для других устройств — `http://192.168.x.x:8000/info_panel_1.html`
(+ `New-NetFirewallRule -DisplayName "Raspisanie 8000" -Direction Inbound -Protocol TCP -LocalPort 8000 -Action Allow -Profile Private,Domain`).

Это не «костыль навсегда»: локальная сеть, порт 8000 ни с чем не конфликтует,
и панель работает независимо от того, кто занял 80-й.

---

## Почему `/raspisanie/` не открывался «через IIS»

Цепочка причин сейчас такая:

1. Порт 80 отвечает `Microsoft-HTTPAPI/2.0` — значит запрос обрабатывает не сайт
   IIS, а `http.sys` без сайта → **404** на любой URL (в том числе на
   `/raspisanie/info_panel_1.html`). Файлы при этом на месте и права в порядке.
2. Провайдер `IIS:` не найден → модуль `WebAdministration` не загружен
   (IIS-роль/консоль управления, скорее всего, установлена частично), поэтому
   команды вида `Get-ChildItem IIS:\Sites` и не работают.

То есть проблема была не в `web.config`, не в правах и не в `defaultDocument` —
до них запрос просто не доходит.

---

## Быстрая шпаргалка команд

```cmd
:: кто на 80-м
netstat -ano | findstr ":80 "
netsh http show servicestate

:: IIS: служба и сайты
sc query W3SVC
%windir%\system32\inetsrv\appcmd.exe list sites
%windir%\system32\inetsrv\appcmd.exe list apps

:: проверить ответ
curl.exe -I http://127.0.0.1/
curl.exe -I http://127.0.0.1/raspisanie/info_panel_1.html
```

`appcmd.exe` работает и без провайдера `IIS:` — если `Get-ChildItem IIS:\Sites`
ругается, используй `appcmd list sites` / `appcmd list vdirs`.
