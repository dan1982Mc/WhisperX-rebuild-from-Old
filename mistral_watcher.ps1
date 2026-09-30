$base = $PSScriptRoot
$processor = Join-Path $base "Mistral\process.py"

Write-Host "Starting Mistral watcher..."
Write-Host "Script: $processor"

& python $processor

if ($LASTEXITCODE -ne 0) {
    Write-Host "Mistral watcher exited with code $LASTEXITCODE." -ForegroundColor Red
    exit $LASTEXITCODE
}
