$Base = $PSScriptRoot

$Incoming  = "$Base\1_Incoming"
$Processing = "$Base\2_Processing"
$Failed    = "$Base\Failed"
$LogFile   = "$Base\Logs\meeting-watcher.log"

$WhisperX = "$Base\.venv\Scripts\whisperx.exe"

$Prompt = "Nederlandstalig overleg over architectuur, stedenbouw, bouwplannen en gemeentelijke procedures. Namen en termen: Vlietpoort, Gert-Jan, Ron van der Meer, Erwin Westra, Jos van Boxtel, Ferry Adema, Ingeborg, Richard Koek, NVU."

Write-Host "WhisperX Meeting Watcher started."
Write-Host "Watching: $Incoming"

while ($true) {

    $files = Get-ChildItem $Incoming -File |
        Where-Object { $_.Extension -in ".mp3", ".wav", ".m4a", ".flac" }

    foreach ($file in $files) {

        Write-Host ""
        Write-Host "Found: $($file.Name)"

        # Wait until the recording is completely copied
        $size1 = $file.Length
        Start-Sleep -Seconds 5

        if (-not (Test-Path $file.FullName)) {
            continue
        }

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

            $OutputDir = $ProcessingDir

            Add-Content $LogFile "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') START $($file.Name)"

            Write-Host "Processing: $($file.Name)"

            & $WhisperX `
                $ProcessingFile `
                --model large-v3 `
                --device cuda `
                --compute_type float16 `
                --language nl `
                --vad_method silero `
                --initial_prompt $Prompt `
                --diarize `
                --hf_token $env:HF_TOKEN `
                --output_dir $OutputDir `
                --output_format json

            if ($LASTEXITCODE -eq 0) {

                Move-Item $ProcessingFile $ProcessingDir -Force

                Add-Content $LogFile "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') SUCCESS $($file.Name)"

                Write-Host "Completed: $($file.Name)"
                Write-Host "Output: $OutputDir"
            }
            else {

                Move-Item $ProcessingFile $Failed -Force

                Add-Content $LogFile "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') FAILED $($file.Name) ExitCode=$LASTEXITCODE"

                Write-Host "FAILED: $($file.Name)"
            }
        }
        catch {

            if (Test-Path $ProcessingFile) {
                Move-Item $ProcessingFile $Failed -Force
            }

            Add-Content $LogFile "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') ERROR $($file.Name) $($_.Exception.Message)"

            Write-Host "ERROR: $($_.Exception.Message)"
        }
    }

    Start-Sleep -Seconds 5
}