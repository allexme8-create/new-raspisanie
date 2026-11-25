# IIS: `http://127.0.0.1/raspisanie/` не открывается — разбор по шагам

Файлы в `C:\inetpub\wwwroot\raspisanie` — это правильно, но IIS отдаёт их
**только если** сайт смотрит в `wwwroot` и папка лежит именно там. Дальше —
проверки в порядке вероятности. Первые три закрывают 90 % случаев.

Быстрый автоматический прогон (PowerShell **от администратора**):

```powershell
powershell -ExecutionPolicy Bypass -File diagnose-iis.ps1
```

(скрипт лежит в `tools\` этого репозитория; ничего не меняет, только печатает
состояние служб, привязки сайтов, права, наличие файлов и реальные HTTP-коды).

---

## 1. Открыть файл напрямую — так сразу видно, «папка не видна» или «индекс не подхватился»

В браузере: `http://127.0.0.1/raspisanie/info_panel_1.html`

| Что видно | Причина | Что делать |
|---|---|---|
| Страница открылась | сайт и права в порядке, проблема только в странице по умолчанию | п. 2 |
| **403.14 Forbidden** («Directory listing denied») | папка видна, но `info_panel_1.html` не найден **или** `web.config` с `defaultDocument` не читается | п. 2 и п. 3 |
| **404.0 / 404.3 Not Found** | папки нет по этому пути, либо не установлен компонент «Статическое содержимое» | п. 3, п. 4 |
| **500.19 Internal Server Error** | сломан `web.config` | п. 3 |
| **401.3 Unauthorized** | нет прав NTFS для `IIS_IUSRS` | п. 5 |
| Ничего / «не удаётся подключиться» | IIS не запущен или не слушает порт 80 | п. 6 |

---

## 2. Страница по умолчанию: `defaultDocument`

`web.config` с `defaultDocument → info_panel_1.html` работает **только если**
в IIS установлен компонент *Default Document* (`IIS-DefaultDocument`).
Если он выключен, `web.config` игнорируется и на `/raspisanie/` получаешь
403.14.

Проверить/включить (PowerShell от администратора):

```powershell
Enable-WindowsOptionalFeature -Online -FeatureName IIS-DefaultDocument,IIS-StaticContent,IIS-HttpErrors -All
```

Альтернатива без настройки IIS: скопировать `info_panel_1.html` ещё и как
`index.html` (IIS отдаёт `index.html` по умолчанию всегда):

```powershell
Copy-Item C:\inetpub\wwwroot\raspisanie\info_panel_1.html C:\inetpub\wwwroot\raspisanie\index.html
```

> Твой `web.config` корректен:
> ```xml
> <defaultDocument><files><add value="info_panel_1.html" /></files></defaultDocument>
> ```
> Ещё вариант — оставить `web.config` как есть и открывать
> `http://127.0.0.1/raspisanie/info_panel_1.html` (без слэша в конце).

---

## 3. Убедиться, что сайт смотрит в `C:\inetpub\wwwroot`

```powershell
Import-Module WebAdministration
Get-ChildItem IIS:\Sites | Format-List Name, State, PhysicalPath, Bindings
```

- `PhysicalPath` у `Default Web Site` должен быть `C:\inetpub\wwwroot`.
  Если там другой путь — либо копируй папку туда, либо создай свой сайт/приложение
  (п. 7).
- `Bindings` должны содержать `http/*:80:` (все адреса, порт 80). Если привязки
  только `http/*:8080:` — открывать надо `http://127.0.0.1:8080/raspisanie/`.
- `State` — `Started`. Если `Stopped`: `Start-Website "Default Web Site"`.

Проверить содержимое папки, как его видит сервер:

```cmd
dir C:\inetpub\wwwroot
dir C:\inetpub\wwwroot\raspisanie
```

Классическая ошибка: распаковка создала вложенную папку
`C:\inetpub\wwwroot\raspisanie\raspisanie\...` — тогда правильный адрес
`http://127.0.0.1/raspisanie/raspisanie/info_panel_1.html`.
Ещё вариант — папка называется с пробелом/по-другому (`raspisanie ` с пробелом
в конце, `raspisanie (2)`).

---

## 4. `web.config` может «ломать» выдачу (500.19)

Если после запроса видишь **500.19**, проверь `web.config` в корне `wwwroot` —
там бывают секции вроде `<rewrite>`, `<handlers>`, которые требуют
дополнительных модулей. Быстрая проверка: переименуй `web.config` в
`web.config.bak` в папке `raspisanie` и открой
`http://127.0.0.1/raspisanie/info_panel_1.html`. Если открылось — проблема в
конфиге, а не в файлах.

Наш `web.config` содержит только `defaultDocument`, он безопасен. Но чтобы
`defaultDocument` работал локально для папки, разрешено и такое:

```cmd
%windir%\system32\inetsrv\appcmd.exe set config "Default Web Site/raspisanie" -section:system.webServer/defaultDocument /+"files.[value='info_panel_1.html']" /commit:apphost
```

---

## 5. Права на папку (401.3 / 403)

```powershell
icacls C:\inetpub\wwwroot\raspisanie
icacls C:\inetpub\wwwroot\raspisanie /grant "IIS_IUSRS:(OI)(CI)R"
icacls C:\inetpub\wwwroot\raspisanie /grant "IUSR:(OI)(CI)R"
```

Обычно права наследуются от `wwwroot` — но если папку копировали с другого
диска/из архива с сохранением прав, наследование может быть снято.

---

## 6. Служба IIS и порт 80

```powershell
Get-Service W3SVC, WAS
Start-Service W3SVC
netstat -ano | findstr ":80 "     # кто слушает 80
```

Если порт 80 занят другим процессом (Skype, Apache, nginx, «World Wide Web
Publishing Service» от другого продукта) — IIS не запустится или не ответит.
Освободи порт либо поменяй привязку сайта на 8080:

```powershell
Import-Module WebAdministration
Set-ItemProperty "IIS:\Sites\Default Web Site" -Name bindings -Value @{protocol="http";bindingInformation="*:8080:"}
# затем: http://127.0.0.1:8080/raspisanie/
```

---

## 7. Если хочется отдельный сайт/приложение (аккуратный вариант)

Приложение внутри `Default Web Site` (адрес останется `/raspisanie/`):

```powershell
Import-Module WebAdministration
New-WebApplication -Site "Default Web Site" -Name "raspisanie" `
    -PhysicalPath "C:\inetpub\wwwroot\raspisanie" -ApplicationPool "DefaultAppPool"
```

Отдельный сайт на порту 80 (если `Default Web Site` не нужен):

```powershell
New-WebSite -Name "Raspisanie" -PhysicalPath "C:\inetpub\wwwroot\raspisanie" `
    -Port 80 -ApplicationPool "DefaultAppPool"
```

Проверка списка:

```cmd
%windir%\system32\inetsrv\appcmd.exe list apps
%windir%\system32\inetsrv\appcmd.exe list vdirs
```

---

## 8. Полезные быстрые проверки

```powershell
# код ответа без браузера
curl.exe -I http://127.0.0.1/raspisanie/info_panel_1.html

# подробная ошибка IIS прямо в ответе
# (по умолчанию detail показывается только для localhost — это ок)
curl.exe -s http://127.0.0.1/raspisanie/ | Select-Object -First 20

# журнал IIS
Get-Content C:\inetpub\logs\LogFiles\W3SVC1\*.log -Tail 20
```

В логе видно, какой именно URL и какой код вернул IIS — например
`GET /raspisanie/ - 403` (нет индексного файла) или `GET /raspisanie/info_panel_1.html - 200`
(значит дело было именно в defaultDocument).

---

## 9. Доступ из локальной сети

После того как заработало на `127.0.0.1`:

```powershell
New-NetFirewallRule -DisplayName "IIS HTTP 80" -Direction Inbound -Protocol TCP `
    -LocalPort 80 -Action Allow -Profile Private,Domain
ipconfig | findstr /i "IPv4"
```

С другого устройства: `http://192.168.x.x/raspisanie/`
(не `localhost`, и сеть должна быть «Частной»).

---

## 10. TL;DR по твоему случаю

1. Открой `http://127.0.0.1/raspisanie/info_panel_1.html` — это отделит «нет
   индексного файла» от «папка недоступна».
2. Скопируй файл в `index.html` — самый быстрый способ получить `/raspisanie/`.
3. Если и прямой URL не открывается: `Get-ChildItem IIS:\Sites` (путь и
   привязки), `icacls` (права), `Get-Service W3SVC` (служба), `netstat` (порт 80).
4. `500.19` → проблема в `web.config`; `404.3` → включить `IIS-StaticContent`;
   `403.14` → `IIS-DefaultDocument` / `index.html`; `401.3` → `icacls`.

Пришли вывод `diagnose-iis.ps1` (разделы 3, 5, 7) — назову точную причину и
дам одну команду для исправления.
