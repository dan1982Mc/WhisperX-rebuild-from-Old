$base = $PSScriptRoot

Write-Host "Starting Meeting AI pipeline..."
Write-Host "Base: $base"
Write-Host ""

$watchers = @(
    @{ Name = "WhisperX"; Script = "$base\meeting-watcher.ps1" },
    @{ Name = "Preparation"; Script = "$base\prepare_for_mistral.ps1" },
    @{ Name = "Mistral"; Script = "$base\mistral_watcher.ps1" }
)

foreach ($watcher in $watchers) {
    if (-not (Test-Path $watcher.Script)) {
        Write-Host "ERROR: Script not found: $($watcher.Script)" -ForegroundColor Red
        continue
    }

    Write-Host "Starting $($watcher.Name): $($watcher.Script)"

    $process = Start-Process powershell.exe -ArgumentList @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", $watcher.Script
    ) -WindowStyle Normal -PassThru

    Write-Host "$($watcher.Name) process started. PID: $($process.Id)" -ForegroundColor Green
    Start-Sleep -Seconds 2

    if ($process.HasExited) {
        Write-Host "$($watcher.Name) EXITED. Exit code: $($process.ExitCode)" -ForegroundColor Red
    } else {
        Write-Host "$($watcher.Name) is running." -ForegroundColor Green
    }

    Write-Host ""
}

Write-Host "Startup check complete."
