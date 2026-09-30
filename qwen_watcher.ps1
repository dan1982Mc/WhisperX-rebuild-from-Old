$OutputRoot = "$PSScriptRoot\2_Processing"
$MeetingNotesRoot = "$PSScriptRoot\3_Meeting Notes"
$OllamaUrl = "http://localhost:11434/api/generate"
$Model = "qwen3:30b"

Write-Host "Qwen watcher started."
Write-Host "Watching: $OutputRoot"
Write-Host "Model: $Model"
Write-Host ""

$processed = @{}

while ($true) {

    $files = Get-ChildItem $OutputRoot `
        -Filter "*_for_qwen.md" `
        -Recurse `
        -File

    foreach ($file in $files) {

        if ($processed.ContainsKey($file.FullName)) {
            continue
        }

        try {

            # -------------------------------------------------
            # Find participant file
            # -------------------------------------------------

            $participantsFile = Join-Path `
                $file.DirectoryName `
                "participants.json"

            if (-not (Test-Path $participantsFile)) {

                Write-Host "Waiting for participants.json: $($file.DirectoryName)" `
                    -ForegroundColor Yellow

                continue
            }

            $participants = Get-Content `
                $participantsFile `
                -Raw |
                ConvertFrom-Json

            # -------------------------------------------------
            # Check whether all names have been filled in
            # -------------------------------------------------

            $missingNames = @()

            foreach ($property in $participants.PSObject.Properties) {

                if ([string]::IsNullOrWhiteSpace([string]$property.Value)) {

                    $missingNames += $property.Name
                }
            }

            if ($missingNames.Count -gt 0) {

                Write-Host "Waiting for participant names: $($missingNames -join ', ')" `
                    -ForegroundColor Yellow

                continue
            }

            # -------------------------------------------------
            # Make sure the Markdown file is finished
            # -------------------------------------------------

            $before = $file.Length

            Start-Sleep -Milliseconds 500

            $after = (Get-Item $file.FullName).Length

            if ($before -ne $after) {
                continue
            }

            Write-Host "Sending to Qwen: $($file.Name)"

            $transcript = Get-Content `
                $file.FullName `
                -Raw

            # -------------------------------------------------
            # Build participant mapping
            # -------------------------------------------------

            $participantText = ""

            foreach ($property in $participants.PSObject.Properties) {

                $participantText += `
                    "$($property.Name) = $($property.Value)`n"
            }

            # -------------------------------------------------
            # Stage 1: extract structured evidence
            # -------------------------------------------------

            $ExtractionPromptFile = Join-Path $PSScriptRoot "Qwen\extraction_prompt.txt"
            $NotesPromptFile = Join-Path $PSScriptRoot "Qwen\meeting_notes_prompt.txt"

            if (-not (Test-Path $ExtractionPromptFile)) {
                throw "Missing prompt file: $ExtractionPromptFile"
            }

            if (-not (Test-Path $NotesPromptFile)) {
                throw "Missing prompt file: $NotesPromptFile"
            }

            if (Test-Path $evidenceFile) {

                Write-Host "Existing evidence found: $evidenceFile" -ForegroundColor DarkGray

                $evidence = Get-Content $evidenceFile -Raw | ConvertFrom-Json

                if (-not $evidence.evidence) {
                    throw "Existing evidence file contains no evidence items."
                }

            }
            else {

                $transcript = Get-Content $file.FullName -Raw

                $extractionPrompt = Get-Content $ExtractionPromptFile -Raw
                $extractionPrompt = $extractionPrompt.Replace("{{PARTICIPANTS}}", $participantText)
                $extractionPrompt = $extractionPrompt.Replace("{{TRANSCRIPT}}", $transcript)

                Write-Host "Sending to Qwen: $($file.Name)"
                Write-Host "Stage 1: extracting structured evidence..."

                $body = @{
                    model = $Model
                    prompt = $extractionPrompt
                    stream = $false
                    keep_alive = "10m"
                } | ConvertTo-Json -Depth 10

                $extractionResponse = Invoke-RestMethod -Uri $OllamaUrl -Method Post -ContentType "application/json" -Body $body

                $evidenceText = $extractionResponse.response.Trim()
                $fence = ([char]96).ToString()
                $evidenceText = $evidenceText.Replace($fence + $fence + $fence + "json", "").Replace($fence + $fence + $fence, "").Trim()

                $evidence = $evidenceText | ConvertFrom-Json

                if (-not $evidence.evidence) {
                    throw "Stage 1 returned no evidence items."
                }

                $evidence | ConvertTo-Json -Depth 20 | Set-Content -Path $evidenceFile -Encoding UTF8

                Write-Host "Created evidence: $evidenceFile" -ForegroundColor Yellow
            }

            # -------------------------------------------------
            # Stage 2: generate meeting notes from evidence
            # -------------------------------------------------

            $evidenceJson = Get-Content $evidenceFile -Raw

            $prompt = Get-Content $NotesPromptFile -Raw
            $prompt = $prompt.Replace("{{PARTICIPANTS}}", $participantText)
            $prompt = $prompt.Replace("{{EVIDENCE}}", $evidenceJson)

            Write-Host "Stage 2: generating meeting notes..."
            # -------------------------------------------------
            # Call Ollama
            # -------------------------------------------------

            $body = @{
                model = $Model
                prompt = $prompt
                stream = $false
                keep_alive = "10m"
            } |
            ConvertTo-Json -Depth 10

            $response = Invoke-RestMethod `
                -Uri $OllamaUrl `
                -Method Post `
                -ContentType "application/json" `
                -Body $body

            # -------------------------------------------------
            # Save ONLY final Qwen response
            # -------------------------------------------------

            $outputFile = Join-Path `
                $MeetingNotesRoot `
                ($file.BaseName -replace "_for_qwen$","_meeting_notes.txt")

            New-Item -ItemType Directory -Force $MeetingNotesRoot | Out-Null

            $response.response |
                Set-Content `
                    -Path $outputFile `
                    -Encoding UTF8

            $processed[$file.FullName] = $true

            Write-Host "Created: $outputFile" `
                -ForegroundColor Green

            Write-Host ""

        }
        catch {

            Write-Host "ERROR processing $($file.Name)" `
                -ForegroundColor Red

            Write-Host $_.Exception.Message `
                -ForegroundColor Red

            Write-Host ""
        }
    }

    Start-Sleep -Seconds 5
}