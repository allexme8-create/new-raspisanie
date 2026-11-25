# Быстрый HTTP-сервер на Windows 10 для раздачи HTML

Ниже — от самого простого к «правильному». Любой вариант выдаёт `index.html`
из текущей папки на `http://localhost:8000`.

---

## 0. Подготовка (30 секунд)

1. Создай папку, например `C:\site`, и положи туда `index.html`.
2. Открой эту папку в Проводнике, затем в адресной строке набери `cmd` и Enter —
   консоль откроется уже в нужной папке (`cd` не нужен).

> Если console выдаёт «кракозябры» вместо русского текста:
> `chcp 65001` (UTF-8) — но файл `index.html` всё равно сохраняй в UTF-8
> (в `<head>`: `<meta charset="utf-8">`).

---

## 1. Python — самый быстрый способ (если стоит Python)

```cmd
python -m http.server 8000
```

Открыть: http://localhost:8000

- Остановить: `Ctrl+C`.
- Другой порт: `python -m http.server 8080`.
- Слушать все интерфейсы (для доступа с телефона в той же Wi-Fi):
  `python -m http.server 8000 --bind 0.0.0.0`
- Нет Python? `winget install -e --id Python.Python.3.12` в PowerShell
  (или `py -m http.server 8000`, если установлен лаунчер `py`).

Проверить, установлен ли: `python --version`.

---

## 2. Node.js — без установки чего-либо ещё

```cmd
npx --yes http-server . -p 8000 -c-1
```

или через `serve`:

```cmd
npx --yes serve . -l 8000
```

- `-c-1` у http-server отключает кеширование — удобно при правках HTML.
- Нужен Node.js: `winget install -e --id OpenJS.NodeJS.LTS`.

---

## 3. Совсем без установок — PowerShell-сервер (одна команда)

Windows 10 уже содержит .NET `HttpListener`. Скопируй целиком в PowerShell:

```powershell
$root = "C:\site"; $port = 8000
$l = New-Object System.Net.HttpListener
$l.Prefixes.Add("http://localhost:$port/")
$l.Start(); Write-Host "http://localhost:$port"
while ($l.IsListening) {
  $c = $l.GetContext()
  $p = $c.Request.Url.LocalPath.TrimStart('/'); if (-not $p) { $p = 'index.html' }
  $f = Join-Path $root $p
  if (Test-Path $f -PathType Leaf) {
    $b = [IO.File]::ReadAllBytes($f)
    $ext = [IO.Path]::GetExtension($f).ToLower()
    $c.Response.ContentType = switch ($ext) {
      '.html' {'text/html; charset=utf-8'} '.css' {'text/css; charset=utf-8'}
      '.js' {'application/javascript; charset=utf-8'} '.json' {'application/json'}
      '.png' {'image/png'} '.jpg' { 'image/jpeg' } '.svg' {'image/svg+xml'}
      default {'application/octet-stream'}
    }
    $c.Response.OutputStream.Write($b, 0, $b.Length)
  } else { $c.Response.StatusCode = 404 }
  $c.Response.Close()
}
```

Минус: обработка по одному запросу за раз, только локально. Для показа
одной страницы — более чем достаточно. Готовый файл: `serve-http.ps1`
(см. рядом), запуск: `powershell -ExecutionPolicy Bypass -File serve-http.ps1`.

> `http://localhost:8000` требует прав администратора? Нет. А вот
> `http://+:8000/` или `http://*:8000/` — требует (`netsh http add urlacl ...`),
> поэтому проще оставить `localhost`.

---

## 4. PHP, если он есть

```cmd
php -S localhost:8000
```

---

## 5. «По-взрослому» — IIS (постоянный сервер, автозапуск)

1. Панель управления → «Программы и компоненты» → **Включение или отключение
   компонентов Windows** → Internet Information Services → включить
   «Веб-управление» + «Основные компоненты» (и «Статические средства»).
   Или PowerShell (от администратора):
   ```powershell
   Enable-WindowsOptionalFeature -Online -FeatureName IIS-WebServerRole,IIS-WebServer,IIS-StaticContent -All
   ```
2. Открыть `C:\inetpub\wwwroot` (или создать сайт через **inetmgr** → «Сайты» →
   «Добавить веб-сайт», путь `C:\site`, порт 8000).
3. Открыть в браузере `http://localhost` (порт 80) или `http://localhost:8000`.
4. Служба `W3SVC` поднимается сама при старте Windows — это вариант для
   «работает всегда».

---

## Если настройки веб-страницы должны быть доступны с других устройств

1. Разрешить порт в брандмауэре (PowerShell **от администратора**):
   ```powershell
   New-NetFirewallRule -DisplayName "HTTP 8000" -Direction Inbound -Protocol TCP -LocalPort 8000 -Action Allow
   ```
2. Сервер запускать с привязкой к `0.0.0.0`: `python -m http.server 8000 --bind 0.0.0.0`
   (по умолчанию Python слушает все интерфейсы; `--bind` уточняет).
3. Узнать IP: `ipconfig` → «IPv4-адрес», например `192.168.1.50`.
4. С телефона: `http://192.168.1.50:8000`.

---

## Типичные проблемы

| Симптом | Причина / решение |
|---|---|
| `python: не найден` | не в PATH. Попробуй `py -m http.server 8000` или `winget install Python.Python.3.12` |
| `npx: не найден` | не установлен Node.js |
| `порт уже занят` / `address already in use` | смени порт: `8000` → `8001`, или `netstat -ano \| findstr :8000` → `taskkill /PID <pid> /F` |
| Страница открылась, но стили/картинки 404 | запускать сервер надо **в корне проекта**, пути в HTML — относительные (`css/style.css`, без `/C:/...`) |
| Русский текст кракозябрами | сохранить файл в UTF-8 + `<meta charset="utf-8">` |
| Браузер показывает список файлов | в папке нет `index.html` (или он назван `index.htm` / `Index.html`) |
| «сайт не открывается» на другом ПК | брандмауэр (см. выше) или используешь `localhost` вместо IP |

---

## TL;DR

```cmd
cd C:\site
python -m http.server 8000
```
→ http://localhost:8000. Нет Python — `npx --yes http-server . -p 8000 -c-1`.
