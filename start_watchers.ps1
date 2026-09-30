$base = $PSScriptRoot

Write-Host "Starting Meeting AI pipeline..."

# 1. WhisperX watcher
Start-Process powershell.exe `
    -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$base\meeting-watcher.ps1`"" `
    -WindowStyle Minimized

Start-Sleep -Seconds 2

# 2. Prepare transcript for Qwen
Start-Process powershell.exe `
    -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$base\prepare_for_qwen.ps1`"" `
    -WindowStyle Minimized

Start-Sleep -Seconds 2

# 3. Qwen watcher
Start-Process powershell.exe `
    -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$base\qwen_watcher.ps1`"" `
    -WindowStyle Minimized

Write-Host "All three watchers started."