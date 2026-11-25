# Как скачать и запустить файлы из этого репозитория (Windows)

Все мои файлы лежат в GitHub-репозитории
`https://github.com/allexme8-create/new-raspisanie` (он публичный) в ветке
`arena/d727e62f-new-raspisanie`. Скачать можно двумя способами — выбирай любой.

Нужные файлы:

```
tools/serve_lan.py          — HTTP-сервер для папки с расписанием
tools/serve.bat             — запуск сервера двойным щелчком
tools/diagnose-iis.ps1      — диагностика IIS
docs/iis-troubleshooting.md — разбор «почему IIS не открывает /raspisanie/»
docs/info-panel-lan.md      — как открыть info_panel_1.html по сети
docs/windows10-http-server.md — общая шпаргалка по HTTP-серверу
```

---

## Вариант A. Скачать один файл (без git) — самое быстрое

1. Открой в браузере страницу файла, например:
   `https://github.com/allexme8-create/new-raspisanie/blob/arena/d727e62f-new-raspisanie/tools/serve_lan.py`
2. Справа сверху у кода — кнопка **«Raw»** (или иконка загрузки ⤓
   «Download raw file»).
3. Сохранится как `serve_lan.py` (браузер может добавить `.txt` — тогда
   переименуй, убрав `.txt`; включи в Проводнике «Расширения имён файлов»).
4. Повтори для `serve.bat` и/или `diagnose-iis.ps1`.

Сохраняй **`serve.bat` и `serve_lan.py` в одну папку** — с расписанием
(`info_panel_1.html`, `schedule_panel.js`, `nika_data_*.js`, `images\`).

> `serve.bat` в браузере может «не скачаться», а открыться текстом — правый
> клик по ссылке → «Сохранить ссылку как…».

---

## Вариант B. Скачать весь репозиторий архивом

1. `https://github.com/allexme8-create/new-raspisanie`
2. Переключи ветку на `arena/d727e62f-new-raspisanie`
   (кнопка с названием ветки слева над списком файлов).
3. Кнопка **«Code»** → **«Download ZIP»**.
4. Распакуй, например в `C:\temp\new-raspisanie` — нужные файлы будут в
   `tools\` и `docs\`.

Или одной командой (PowerShell, ничего устанавливать не надо):

```powershell
$zip = "$env:TEMP\raspisanie.zip"
Invoke-WebRequest "https://codeload.github.com/allexme8-create/new-raspisanie/zip/refs/heads/arena/d727e62f-new-raspisanie" -OutFile $zip
Expand-Archive $zip -DestinationPath "C:\temp\new-raspisanie" -Force
dir "C:\temp\new-raspisanie\*\tools"
```

---

## Вариант C. Через git (если стоит Git for Windows)

```cmd
cd /d C:\
git clone -b arena/d727e62f-new-raspisanie https://github.com/allexme8-create/new-raspisanie.git C:\new-raspisanie
dir C:\new-raspisanie\tools
```

Дальше `git pull` для обновления.

---

## Вариант D. Совсем без скачивания — запустить прямо в PowerShell

Эти файлы маленькие, и `diagnose-iis.ps1` можно запустить одной строкой,
без сохранения:

```powershell
# PowerShell ОТ АДМИНИСТРАТОРА
irm "https://raw.githubusercontent.com/allexme8-create/new-raspisanie/arena/d727e62f-new-raspisanie/tools/diagnose-iis.ps1" -OutFile "$env:TEMP\diag.ps1"
powershell -ExecutionPolicy Bypass -File "$env:TEMP\diag.ps1"
```

Проверить, что адрес вообще доступен (иногда блокирует провайдер):

```powershell
curl.exe -I "https://raw.githubusercontent.com/allexme8-create/new-raspisanie/arena/d727e62f-new-raspisanie/tools/serve_lan.py"
```
Должно быть `HTTP/1.1 200 OK`. Если `000`/таймаут — GitHub недоступен из твоей
сети, используй VPN/другую сеть или попроси файл в чате.

> Если `irm` ругается на сертификат — сначала выполни:
> `[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12`

---

## Как запустить то, что скачал

### 1. Диагностика IIS (ничего не меняет)

PowerShell **от администратора**, из папки, куда скачал (или с полным путём):

```powershell
cd C:\temp\new-raspisanie
powershell -ExecutionPolicy Bypass -File .\tools\diagnose-iis.ps1
```

Если PowerShell запрещает запуск скриптов («выполнение сценариев отключено»)
— именно флаг `-ExecutionPolicy Bypass` это обходит.

### 2. Резервный локальный сервер (если IIS упрямится)

1. Скопируй `serve_lan.py` + `serve.bat` в папку с расписанием
   (`C:\inetpub\wwwroot\raspisanie`).
2. Двойной щелчок по `serve.bat` (нужен Python:
   `winget install -e --id Python.Python.3.12`, затем заново `serve.bat`).
3. Браузер откроет `http://localhost:8000/info_panel_1.html`; адрес для других
   устройств скрипт напечатает сам. Окно консоли не закрывать.
4. Если другие устройства не видят — разреши порт:
   ```powershell
   New-NetFirewallRule -DisplayName "Raspisanie HTTP 8000" -Direction Inbound -Protocol TCP -LocalPort 8000 -Action Allow -Profile Private,Domain
   ```

Запуск без `.bat`:

```cmd
cd /d C:\inetpub\wwwroot\raspisanie
python serve_lan.py . -p 8000
```

### 3. Проверка, что IIS теперь отвечает

```powershell
curl.exe -I http://127.0.0.1/raspisanie/info_panel_1.html
curl.exe -I http://127.0.0.1/raspisanie/
```

---

## Быстрая проверка «а файл скачался нормально?»

- `.bat` / `.ps1` открываются в блокноте как текст, начинаются с `@echo off` /
  `#` — значит всё ок.
- Если у файла расширение `.txt` (`.bat.txt`, `.py.txt`) — Проводник →
  «Вид» → включи «Расширения имён файлов» → переименуй.
- Python: `python --version` в cmd должен что-то ответить.
