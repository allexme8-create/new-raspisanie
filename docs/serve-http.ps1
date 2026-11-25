# Минимальный HTTP-сервер для Windows 10 (без установки чего-либо).
# Запуск в папке с index.html:
#   powershell -ExecutionPolicy Bypass -File serve-http.ps1
# или с параметрами:
#   powershell -ExecutionPolicy Bypass -File serve-http.ps1 -Root C:\site -Port 8080
param(
    [string]$Root = (Get-Location).Path,
    [int]$Port = 8000,
    [string]$HostName = "localhost"
)

$Root = (Resolve-Path $Root).Path
$listener = New-Object System.Net.HttpListener
$listener.Prefixes.Add("http://${HostName}:${Port}/")

function Send-File($res, $path, $types) {
    $ext = [IO.Path]::GetExtension($path).ToLower()
    $res.ContentType = if ($types.ContainsKey($ext)) { $types[$ext] } else { 'application/octet-stream' }
    $bytes = [IO.File]::ReadAllBytes($path)
    $res.ContentLength64 = $bytes.Length
    $res.OutputStream.Write($bytes, 0, $bytes.Length)
}

try {
    $listener.Start()
} catch {
    Write-Host "Не удалось открыть http://${HostName}:${Port}/ — порт занят или нужны права администратора." -ForegroundColor Red
    Write-Host $_.Exception.Message
    exit 1
}

Write-Host "Сервер запущен: http://${HostName}:${Port}/" -ForegroundColor Green
Write-Host "Каталог: $Root"
Write-Host "Остановить: Ctrl+C"

$types = @{
    '.html' = 'text/html; charset=utf-8'
    '.htm'  = 'text/html; charset=utf-8'
    '.css'  = 'text/css; charset=utf-8'
    '.js'   = 'application/javascript; charset=utf-8'
    '.mjs'  = 'application/javascript; charset=utf-8'
    '.json' = 'application/json; charset=utf-8'
    '.txt'  = 'text/plain; charset=utf-8'
    '.xml'  = 'application/xml; charset=utf-8'
    '.svg'  = 'image/svg+xml'
    '.png'  = 'image/png'
    '.jpg'  = 'image/jpeg'
    '.jpeg' = 'image/jpeg'
    '.gif'  = 'image/gif'
    '.webp' = 'image/webp'
    '.ico'  = 'image/x-icon'
    '.woff' = 'font/woff'
    '.woff2'= 'font/woff2'
    '.ttf'  = 'font/ttf'
    '.mp4'  = 'video/mp4'
    '.pdf'  = 'application/pdf'
}

try {
    while ($listener.IsListening) {
        $ctx = $listener.GetContext()
        $req = $ctx.Request
        $res = $ctx.Response
        try {
            $rel = [Uri]::UnescapeDataString($req.Url.LocalPath).TrimStart('/')
            if ([string]::IsNullOrWhiteSpace($rel)) { $rel = 'index.html' }
            $full = Join-Path $Root $rel
            $resolved = [IO.Path]::GetFullPath($full)

            # защита от выхода за пределы каталога (../)
            if (-not $resolved.StartsWith($Root, [StringComparison]::OrdinalIgnoreCase)) {
                $res.StatusCode = 403
            }
            elseif (Test-Path $resolved -PathType Container) {
                $idx = Join-Path $resolved 'index.html'
                if (Test-Path $idx -PathType Leaf) {
                    Send-File $res $idx $types
                } else {
                    $items = Get-ChildItem $resolved | ForEach-Object {
                        $name = $_.Name + $(if ($_.PSIsContainer) { '/' } else { '' })
                        "<li><a href=`"$rel$name`">$name</a></li>"
                    }
                    $html = "<!doctype html><meta charset='utf-8'><h3>$rel</h3><ul>$($items -join '')</ul>"
                    $bytes = [Text.Encoding]::UTF8.GetBytes($html)
                    $res.ContentType = 'text/html; charset=utf-8'
                    $res.OutputStream.Write($bytes, 0, $bytes.Length)
                }
            }
            elseif (Test-Path $resolved -PathType Leaf) {
                Send-File $res $resolved $types
            }
            else {
                $res.StatusCode = 404
                $bytes = [Text.Encoding]::UTF8.GetBytes("404: $rel не найден")
                $res.ContentType = 'text/plain; charset=utf-8'
                $res.OutputStream.Write($bytes, 0, $bytes.Length)
            }
            Write-Host ("{0} {1} {2}" -f $req.HttpMethod, $rel, $res.StatusCode)
        } catch {
            $res.StatusCode = 500
            Write-Host "Ошибка: $($_.Exception.Message)" -ForegroundColor Red
        } finally {
            $res.OutputStream.Close()
            $res.Close()
        }
    }
}
finally {
    $listener.Stop()
    $listener.Close()
    Write-Host "Сервер остановлен."
}
