# E:\vertex-model-bench\start-bench.ps1
# Levanta la API (8015) y la UI (4200) en dos ventanas de PowerShell visibles.
$ErrorActionPreference = "Stop"

$RootDir = $PSScriptRoot
$ApiDir  = Join-Path $RootDir "vertex-model-bench-api"
$UiDir   = Join-Path $RootDir "vertex-model-bench-ui"
$VenvPy  = Join-Path $ApiDir ".venv\Scripts\python.exe"

function Test-PortBusy([int]$Port) {
    $conn = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    if ($conn) { return (Get-Process -Id $conn[0].OwningProcess).ProcessName }
    return $null
}

if (-not (Test-Path $VenvPy)) {
    Write-Error "No se encontró el entorno virtual en: $VenvPy"
}
if (-not (Test-Path (Join-Path $UiDir "node_modules"))) {
    Write-Error "Falta node_modules en $UiDir. Corre 'npm install' ahí primero."
}

# LM Studio tiene que estar sirviendo en 1234
try {
    $lm = Invoke-RestMethod "http://127.0.0.1:1234/v1/models" -TimeoutSec 4
    Write-Host "LM Studio OK: $($lm.data.Count) modelos disponibles." -ForegroundColor Green
} catch {
    Write-Warning "LM Studio no responde en http://127.0.0.1:1234. Arranca el servidor local antes de medir."
}

$apiBusy = Test-PortBusy 8015
if ($apiBusy) {
    Write-Warning "El puerto 8015 ya está ocupado por '$apiBusy'. No arranco otra API."
} else {
    Write-Host "Iniciando Backend FastAPI (http://127.0.0.1:8015)..." -ForegroundColor Cyan
    $ApiCommand = @"
Set-Location '$ApiDir'
& '$VenvPy' -m uvicorn app.main:app --host 127.0.0.1 --port 8015 --reload
"@
    Start-Process powershell -ArgumentList "-NoExit", "-Command", $ApiCommand
    Start-Sleep -Seconds 2
}

$uiBusy = Test-PortBusy 4200
if ($uiBusy) {
    Write-Warning "El puerto 4200 ya está ocupado por '$uiBusy'. No arranco otra UI."
} else {
    Write-Host "Iniciando Frontend Angular (http://127.0.0.1:4200)..." -ForegroundColor Cyan
    $UiCommand = @"
Set-Location '$UiDir'
npx ng serve --host 127.0.0.1 --port 4200
"@
    Start-Process powershell -ArgumentList "-NoExit", "-Command", $UiCommand
}

Write-Host "Listo. API: http://127.0.0.1:8015/health  |  UI: http://127.0.0.1:4200" -ForegroundColor Green
