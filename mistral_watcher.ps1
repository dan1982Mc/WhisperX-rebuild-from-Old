$base = $PSScriptRoot
$processor = Join-Path $base "Mistral\process.py"
$python = Join-Path $base ".venv\Scripts\python.exe"

Write-Host "Starting Mistral watcher..."
Write-Host "Python: $python"
Write-Host "Script: $processor"

if (-not (Test-Path $python)) {
    Write-Host "ERROR: Python executable not found: $python" -ForegroundColor Red
    exit 1
}

if (-not (Test-Path $processor)) {
    Write-Host "ERROR: Mistral processor not found: $processor" -ForegroundColor Red
    exit 1
}

Set-Location $base

& $python $processor

if ($LASTEXITCODE -ne 0) {
    Write-Host "Mistral watcher exited with code $LASTEXITCODE." -ForegroundColor Red
    exit $LASTEXITCODE
}
