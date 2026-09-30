$Base = $PSScriptRoot

$Incoming   = Join-Path $Base "1_Incoming"
$Processing = Join-Path $Base "2_Processing"
$Failed     = Join-Path $Base "Failed"
$LogsDir    = Join-Path $Base "Logs"
$LogFile    = Join-Path $LogsDir "meeting-watcher.log"
$WhisperX   = Join-Path $Base ".venv\Scripts\whisperx.exe"

New-Item -ItemType Directory -Force $Incoming, $Processing, $Failed, $LogsDir | Out-Null

Write-Host "WhisperX Meeting Watcher started."
Write-Host "Watching: $Incoming"
Write-Host "WhisperX: $WhisperX"

if (-not (Test-Path $WhisperX)) {
    Write-Host "ERROR: WhisperX executable not found: $WhisperX" -ForegroundColor Red
    exit 1
}

while ($true) {
    try {
        $files = Get-ChildItem $Incoming -File -ErrorAction Stop |
            Where-Object { $_.Extension.ToLowerInvariant() -in ".mp3", ".wav", ".m4a", ".flac" }

        foreach ($file in $files) {
            Write-Host ""
            Write-Host "Found: $($file.Name)"

            $size1 = $file.Length
            Start-Sleep -Seconds 5
            if (-not (Test-Path $file.FullName)) { continue }
            $size2 = (Get-Item $file.FullName).Length
            if ($size1 -ne $size2) {
                Write-Host "File is still being copied. Waiting..."
                continue
            }

            $Name = [System.IO.Path]::GetFileNameWithoutExtension($file.Name)
            $ProcessingDir = Join-Path $Processing $Name
            $ProcessingFile = Join-Path $ProcessingDir $file.Name

            try {
                New-Item -ItemType Directory -Force $ProcessingDir | Out-Null
                Move-Item $file.FullName $ProcessingFile -ErrorAction Stop
                Add-Content $LogFile "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') START $($file.Name)"

                & $WhisperX $ProcessingFile --model large-v3 --device cuda --compute_type float16 --language nl --vad_method silero --initial_prompt "Nederlandstalig overleg over architectuur, stedenbouw, bouwplannen en gemeentelijke procedures. Namen en termen: Vlietpoort, Gert-Jan, Ron van der Meer, Erwin Westra, Jos van Boxtel, Ferry Adema, Ingeborg, Richard Koek, NVU." --diarize --hf_token $env:HF_TOKEN --output_dir $ProcessingDir --output_format json

                if ($LASTEXITCODE -eq 0) {
                    Add-Content $LogFile "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') SUCCESS $($file.Name)"
                    Write-Host "Completed: $($file.Name)"
                } else {
                    Add-Content $LogFile "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') FAILED $($file.Name) ExitCode=$LASTEXITCODE"
                    Write-Host "FAILED: $($file.Name)" -ForegroundColor Red
                    Move-Item $ProcessingFile $Failed -Force
                }
            } catch {
                Write-Host "ERROR: $($_.Exception.Message)" -ForegroundColor Red
                if (Test-Path $ProcessingFile) { Move-Item $ProcessingFile $Failed -Force }
                Add-Content $LogFile "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') ERROR $($file.Name) $($_.Exception.Message)"
            }
        }
    } catch {
        Write-Host "Watcher error: $($_.Exception.Message)" -ForegroundColor Red
        Add-Content $LogFile "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') WATCHER_ERROR $($_.Exception.Message)"
    }
    Start-Sleep -Seconds 5
}