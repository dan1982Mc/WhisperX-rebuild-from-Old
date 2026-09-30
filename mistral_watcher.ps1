$base = $PSScriptRoot
$watcher = Join-Path $base "Mistral\watcher.py"

Write-Host "Starting Mistral watcher..."
Write-Host "Script: $watcher"

& python $watcher

if ($LASTEXITCODE -ne 0) {
    Write-Host "Mistral watcher exited with code $LASTEXITCODE." -ForegroundColor Red
    exit $LASTEXITCODE
}
