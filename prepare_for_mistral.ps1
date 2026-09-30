$OutputRoot = "$PSScriptRoot\2_Processing"

Write-Host "Stage 2 transcript preparation started."
Write-Host "Watching: $OutputRoot"
Write-Host ""

$processed = @{}

while ($true) {
    $files = Get-ChildItem $OutputRoot -Filter "*.json" -Recurse -File |
        Where-Object {
            $_.Name -ne "participants.json" -and
            $_.Name -notlike "*_evidence.json" -and
            $_.Name -notlike "*_meeting_notes.json"
        }

    foreach ($file in $files) {
        if ($processed.ContainsKey($file.FullName)) { continue }

        try {
            $before = $file.Length
            Start-Sleep -Seconds 2
            $after = (Get-Item $file.FullName).Length
            if ($before -ne $after) { continue }

            $json = Get-Content $file.FullName -Raw | ConvertFrom-Json
            if (-not $json.segments) { continue }

            $outputDirectory = $file.DirectoryName
            $outputFile = Join-Path $outputDirectory ($file.BaseName + "_for_mistral.md")

            if (Test-Path $outputFile) {
                $processed[$file.FullName] = $true
                continue
            }

            $participantsFile = Join-Path $outputDirectory "participants.json"
            if (-not (Test-Path $participantsFile)) {
                Write-Host "Waiting for participants.json: $participantsFile" -ForegroundColor Yellow
                continue
            }

            $speakers = @(
                $json.segments |
                Where-Object { $_.speaker } |
                Select-Object -ExpandProperty speaker -Unique |
                Sort-Object
            )

            $lines = New-Object System.Collections.Generic.List[string]
            $lines.Add("# Meeting transcript")
            $lines.Add("")
            $lines.Add("Source: $($file.Name)")
            $lines.Add("Language: $($json.language)")
            $lines.Add("")
            $lines.Add("## Participants")
            $lines.Add("")
            foreach ($speaker in $speakers) { $lines.Add("- $speaker") }
            $lines.Add("")
            $lines.Add("## Transcript")
            $lines.Add("")

            foreach ($segment in $json.segments) {
                $start = [TimeSpan]::FromSeconds([double]$segment.start)
                $timestamp = $start.ToString("hh\:mm\:ss")
                $speaker = $segment.speaker
                if ([string]::IsNullOrWhiteSpace($speaker)) { $speaker = "UNKNOWN" }
                $text = ([string]$segment.text).Trim()

                if (-not [string]::IsNullOrWhiteSpace($text)) {
                    $lines.Add("### [$timestamp] $speaker")
                    $lines.Add($text)
                    $lines.Add("")
                }
            }

            $lines.Add("---")
            $lines.Add("")
            $lines.Add("## Instructions for Mistral")
            $lines.Add("")
            $lines.Add("This is an automatic WhisperX transcript.")
            $lines.Add("Use participants.json as the only source for participant names.")
            $lines.Add("Do not guess participant identities.")
            $lines.Add("Preserve timestamps and speaker attribution.")
            $lines.Add("Extract evidence only when supported by the transcript.")
            $lines.Add("Do not invent information.")
            $lines.Add("Do not write meeting notes at this stage.")
            $lines.Add("")

            $lines | Set-Content -Path $outputFile -Encoding UTF8
            $processed[$file.FullName] = $true
            Write-Host "Created: $outputFile" -ForegroundColor Green
        }
        catch {
            Write-Host "ERROR processing $($file.Name): $($_.Exception.Message)" -ForegroundColor Red
        }
    }

    Start-Sleep -Seconds 3
}
