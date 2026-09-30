$base = $PSScriptRoot

Write-Host "Starting Meeting AI pipeline..."

Start-Process powershell.exe -ArgumentList @(
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-File", "$base\meeting-watcher.ps1"
) -WindowStyle Minimized

Start-Sleep -Seconds 2

Start-Process powershell.exe -ArgumentList @(
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-File", "$base\prepare_for_mistral.ps1"
) -WindowStyle Minimized

Start-Sleep -Seconds 2

Start-Process powershell.exe -ArgumentList @(
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-File", "$base\mistral_watcher.ps1"
) -WindowStyle Minimized

Write-Host "All WhisperX + Mistral watchers started."
