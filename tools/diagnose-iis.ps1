# Диагностика IIS для папки расписания (info_panel_1.html).
# Запуск в PowerShell ОТ АДМИНИСТРАТОРА:
#   powershell -ExecutionPolicy Bypass -File diagnose-iis.ps1
#   powershell -ExecutionPolicy Bypass -File diagnose-iis.ps1 -SitePath C:\inetpub\wwwroot\raspisanie
#
# Скрипт ничего не меняет в системе, только смотрит и печатает:
#  - установлены ли нужные компоненты IIS;
#  - что IIS реально считает корнем сайта;
#  - какие привязки (bindings) у сайта;
#  - что отдаёт сервер по нужным URL и какой код ошибки.

param(
    [string]$SitePath = "C:\inetpub\wwwroot\raspisanie",
    [string]$File = "info_panel_1.html"
)

$ErrorActionPreference = "Continue"
function Line { Write-Host ("-" * 70) -ForegroundColor DarkGray }

Write-Host "`n=== 1. Служба IIS ===" -ForegroundColor Cyan
Get-Service W3SVC, WAS -ErrorAction SilentlyContinue |
    Select-Object Name, Status, StartType | Format-Table -AutoSize
if (-not (Get-Service W3SVC -ErrorAction SilentlyContinue)) {
    Write-Host "W3SVC отсутствует: IIS не установлен!" -ForegroundColor Red
    Write-Host "Установить: Enable-WindowsOptionalFeature -Online -FeatureName IIS-WebServerRole,IIS-WebServer,IIS-StaticContent,IIS-DefaultDocument,IIS-HttpErrors -All"
    return
}

Write-Host "`n=== 2. Компоненты IIS (нужны StaticContent + DefaultDocument) ===" -ForegroundColor Cyan
$features = @("IIS-WebServerRole", "IIS-WebServer", "IIS-StaticContent", "IIS-DefaultDocument", "IIS-HttpErrors", "IIS-HttpLogging")
foreach ($f in $features) {
    $state = (Get-WindowsOptionalFeature -Online -FeatureName $f -ErrorAction SilentlyContinue).State
    if (-not $state) { $state = (Get-WindowsFeature -Name $f -ErrorAction SilentlyContinue).InstallState }
    $mark = if ("$state" -match "Enabled|Installed") { "OK  " } else { "НЕТ " }
    $color = if ($mark -eq "OK  ") { "Green" } else { "Red" }
    Write-Host ("{0} {1} : {2}" -f $mark, $f, $state) -ForegroundColor $color
}

Write-Host "`n=== 3. Сайты и корневые каталоги ===" -ForegroundColor Cyan
try {
    Import-Module WebAdministration -ErrorAction Stop
    $report = Get-ChildItem IIS:\Sites | ForEach-Object {
        [pscustomobject]@{
            Name     = $_.Name
            State    = $_.State
            Path     = $_.PhysicalPath
            Bindings = ($_.Bindings.Collection | ForEach-Object { "$($_.protocol)://$($_.bindingInformation)" }) -join "; "
            AppPool  = $_.applicationPool
        }
    }
    $report | Format-List
} catch {
    Write-Host "Не удалось прочитать конфигурацию IIS: $($_.Exception.Message)" -ForegroundColor Yellow
    Write-Host "Попробуйте: %windir%\system32\inetsrv\appcmd.exe list sites"
}

Write-Host "`n=== 4. Файлы в папке ===" -ForegroundColor Cyan
if (Test-Path $SitePath) {
    Write-Host "Папка существует: $SitePath"
    Get-ChildItem $SitePath | Where-Object { -not $_.PSIsContainer } |
        Select-Object Name, Length | Format-Table -AutoSize
    foreach ($need in @($File, "schedule_panel.js", "web.config")) {
        $p = Join-Path $SitePath $need
        if (Test-Path $p) { Write-Host "  OK  $need" -ForegroundColor Green }
        else { Write-Host "  НЕТ $need" -ForegroundColor Red }
    }
    if (Test-Path (Join-Path $SitePath "images")) {
        Write-Host "  OK  images\ ($((Get-ChildItem (Join-Path $SitePath 'images') -File -ErrorAction SilentlyContinue).Count) файлов)" -ForegroundColor Green
    } else {
        Write-Host "  НЕТ images\ — не будут грузиться шрифты" -ForegroundColor Yellow
    }
    $aclUsers = @("IIS_IUSRS", "IUSR")
    $acl = Get-Acl $SitePath
    foreach ($u in $aclUsers) {
        if ($acl.Access | Where-Object { $_.IdentityReference -like "*$u" }) { Write-Host "  OK  права для $u" -ForegroundColor Green }
        else { Write-Host "  НЕТ явных прав для $u (обычно наследуются от wwwroot)" -ForegroundColor Yellow }
    }
} else {
    Write-Host "Папки нет: $SitePath" -ForegroundColor Red
}

Write-Host "`n=== 5. Что реально отдаёт сервер ===" -ForegroundColor Cyan
$urls = @(
    "http://127.0.0.1/",
    "http://127.0.0.1/raspisanie/",
    "http://127.0.0.1/raspisanie/$File",
    "http://localhost/raspisanie/"
)
foreach ($u in $urls) {
    try {
        $r = Invoke-WebRequest -Uri $u -UseBasicParsing -TimeoutSec 10 -MaximumRedirection 3
        Write-Host ("{0} -> {1} {2}  [{3} байт]" -f $u, [int]$r.StatusCode, $r.StatusDescription, $r.RawContentLength) -ForegroundColor Green
        if ($r.Content -match "<title>(.*?)</title>") { Write-Host "     title: $($Matches[1])" -ForegroundColor DarkGray }
        if ($r.Content -match "Не удается отобразить расписание") { Write-Host "     страница открылась, но расписание не отрисовалось (нет .js/данных?)" -ForegroundColor Yellow }
    } catch {
        $resp = $_.Exception.Response
        if ($resp) {
            $msg = $_.Exception.Message
            Write-Host ("{0} -> ОШИБКА: {1}" -f $u, $msg) -ForegroundColor Red
            try {
                $sr = New-Object IO.StreamReader($resp.GetResponseStream())
                $body = $sr.ReadToEnd()
                if ($body -match "<title>(.*?)</title>") { Write-Host "     IIS error: $($Matches[1])" -ForegroundColor Yellow }
                if ($body -match "id=""httpErrorSubTitle"">(.*?)</p>") { Write-Host "     detail: $($Matches[1])" -ForegroundColor Yellow }
            } catch { }
        } else {
            Write-Host ("{0} -> НЕТ ОТВЕТА: {1}" -f $u, $_.Exception.Message) -ForegroundColor Red
        }
        if ($u -eq "http://127.0.0.1/") { Write-Host "     (сам IIS на порту 80 не отвечает — служба/порт/брандмауэр)" -ForegroundColor Yellow }
    }
}

Write-Host "`n=== 6. Слушает ли кто-то порт 80 ===" -ForegroundColor Cyan
Get-NetTCPConnection -LocalPort 80 -State Listen -ErrorAction SilentlyContinue |
    Select-Object LocalAddress, LocalPort, OwningProcess,
        @{n = "Process"; e = { (Get-Process -Id $_.OwningProcess -ErrorAction SilentlyContinue).ProcessName } } |
    Format-Table -AutoSize

Write-Host "`n=== 7. Привязки приложений (appcmd) ===" -ForegroundColor Cyan
$appcmd = "$env:windir\system32\inetsrv\appcmd.exe"
if (Test-Path $appcmd) {
    & $appcmd list apps
    Line
    & $appcmd list vdirs
} else {
    Write-Host "appcmd не найден (IIS не установлен?)" -ForegroundColor Yellow
}

Write-Host "`n=== Подсказка по кодам ошибок ===" -ForegroundColor Cyan
$hint = @(
    '403.14 Forbidden        -> файла info_panel_1.html нет в папке ЛИБО defaultDocument не подхватился.'
    '                           Проверка: открыть http://127.0.0.1/raspisanie/info_panel_1.html напрямую.'
    '404.0 Not Found         -> папка не там, где ждёт сайт, или опечатка в URL.'
    '                           Сравните PhysicalPath сайта (раздел 3) с п.4.'
    '404.3 Not Found         -> не установлен компонент "Статическое содержимое" (IIS-StaticContent).'
    '500.19 Internal Server  -> ошибка в web.config (недоступная секция/опечатка). Временно'
    '                           переименуйте web.config в web.config.bak и проверьте снова.'
    '500.21 / 500.22         -> проблема App Pool (.NET CLR), для статики не нужна; пул "DefaultAppPool".'
    '401.3 Unauthorized      -> нет прав NTFS на папку:'
    '                           icacls C:\inetpub\wwwroot\raspisanie /grant "IIS_IUSRS:(OI)(CI)R"'
    '503 Service Unavailable -> остановлен пул приложений или служба WAS.'
)
$hint | ForEach-Object { Write-Host $_ -ForegroundColor DarkGray }
Write-Host "`nГотово. Пришлите вывод разделов 3, 5 и 7 — по нему видно точную причину." -ForegroundColor Green
