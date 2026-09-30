$OutputRoot = "$PSScriptRoot\2_Processing"
$MeetingNotesRoot = "$PSScriptRoot\3_Meeting Notes"
$OllamaUrl = "http://localhost:11434/api/generate"
$Model = "qwen3:30b"
$Python = "$PSScriptRoot\.venv\Scripts\python.exe"
$DocxScript = "$PSScriptRoot\Qwen\create_meeting_docx.py"

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

            # Ignore the helper file created for participant mapping.
            if ($file.Name -eq "participants_for_qwen.md") {
                $processed[$file.FullName] = $true
                continue
            }

            $outputBase = Join-Path $MeetingNotesRoot ($file.BaseName -replace "_for_qwen$","_meeting_notes")
            $outputJsonFile = "$outputBase.json"
            $outputDocxFile = "$outputBase.docx"
            $evidenceFile = Join-Path $file.DirectoryName ($file.BaseName -replace "_for_qwen$","_evidence.json")

            # Completed meetings must not be processed again after watcher restart.
            if (Test-Path $outputJsonFile) {
                Write-Host "Already completed: $($file.Name)" -ForegroundColor DarkGray
                $processed[$file.FullName] = $true
                continue
            }

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

            $ExtractionPromptFile = Join-Path $PSScriptRoot "Qwen\extraction_prompt.txt"
            $NotesPromptFile = Join-Path $PSScriptRoot "Qwen\meeting_notes_prompt.txt"

            if (-not (Test-Path $ExtractionPromptFile)) {
                throw "Missing prompt file: $ExtractionPromptFile"
            }
            if (-not (Test-Path $NotesPromptFile)) {
                throw "Missing prompt file: $NotesPromptFile"
            }

            if (-not (Test-Path $Python)) {
                throw "Missing Python environment: $Python"
            }
            if (-not (Test-Path $DocxScript)) {
                throw "Missing DOCX script: $DocxScript"
            }

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

                $bodyBytes = [System.Text.Encoding]::UTF8.GetBytes($body)
                $extractionResponse = Invoke-RestMethod -Uri $OllamaUrl -Method Post -ContentType "application/json; charset=utf-8" -Body $bodyBytes

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

            if (Test-Path $outputJsonFile) {
                Write-Host "Existing meeting notes JSON found: $outputJsonFile" -ForegroundColor DarkGray
                $notesData = Get-Content $outputJsonFile -Raw | ConvertFrom-Json
                $finalNotes = [string]$notesData.markdown
                if ([string]::IsNullOrWhiteSpace($finalNotes)) {
                    throw "Existing meeting notes JSON contains no markdown source."
                }
            }
            else {
                $evidenceJson = Get-Content $evidenceFile -Raw

                $prompt = Get-Content $NotesPromptFile -Raw
                $prompt = $prompt.Replace("{{PARTICIPANTS}}", $participantText)
                $prompt = $prompt.Replace("{{EVIDENCE}}", $evidenceJson)

                Write-Host "Stage 2: generating meeting notes..."

                $body = @{
                    model = $Model
                    prompt = $prompt
                    stream = $false
                    keep_alive = "10m"
                    options = @{
                        num_ctx = 16384
                    }
                } | ConvertTo-Json -Depth 10

                try {
                    $bodyBytes = [System.Text.Encoding]::UTF8.GetBytes($body)
                    $response = Invoke-RestMethod -Uri $OllamaUrl -Method Post -ContentType "application/json; charset=utf-8" -Body $bodyBytes
                }
                catch {
                    $serverError = $_.ErrorDetails.Message
                    if ([string]::IsNullOrWhiteSpace($serverError)) {
                        $serverError = $_.Exception.Message
                    }
                    throw "Ollama Stage 2 error: $serverError"
                }

                $finalNotes = $response.response
                if ([string]::IsNullOrWhiteSpace($finalNotes)) {
                    throw "Stage 2 returned empty meeting notes."
                }
            }

            # -------------------------------------------------
            # Save machine-readable meeting notes JSON
            # -------------------------------------------------


            $meetingName = $file.BaseName -replace "_for_qwen$",""
            $jsonSections = [ordered]@{}
            $currentSection = $null
            $sectionLines = New-Object System.Collections.Generic.List[string]

            foreach ($line in ($finalNotes -split "`n")) {
                $trimmed = $line.TrimEnd("`r")

                if ($trimmed -match "^## (.+)$") {
                    if ($null -ne $currentSection) {
                        $jsonSections[$currentSection] = @($sectionLines.ToArray())
                    }
                    $currentSection = $Matches[1].Trim()
                    $sectionLines = New-Object System.Collections.Generic.List[string]
                    continue
                }

                if ($null -ne $currentSection) {
                    [void]$sectionLines.Add($trimmed)
                }
            }

            if ($null -ne $currentSection) {
                $jsonSections[$currentSection] = @($sectionLines.ToArray())
            }

            $notesJson = [ordered]@{
                meeting = $meetingName
                generated_at = (Get-Date).ToString("o")
                sections = $jsonSections
                markdown = $finalNotes
            }

            $notesJson |
                ConvertTo-Json -Depth 20 |
                Set-Content -Path $outputJsonFile -Encoding UTF8

            # -------------------------------------------------
            # Create formatted DOCX from the generated meeting notes
            # -------------------------------------------------

            $audioFile = Get-ChildItem $file.DirectoryName -File |
                Where-Object { $_.Extension -in @(".wav",".mp3",".m4a",".flac",".mp4",".aac",".ogg",".wma") } |
                Select-Object -First 1

            if ($audioFile) {
                $meetingDate = $audioFile.LastWriteTime.ToString("dd-MM-yyyy")
            }
            else {
                $meetingDate = (Get-Date).ToString("dd-MM-yyyy")
            }

            & $Python $DocxScript `
                --input-text $finalNotes `
                --output $outputDocxFile `
                --project "WhisperX" `
                --meeting $meetingName `
                --date $meetingDate

            if ($LASTEXITCODE -ne 0 -or -not (Test-Path $outputDocxFile)) {
                throw "DOCX creation failed for $meetingName"
            }

            $processed[$file.FullName] = $true

            Write-Host "Created: $outputJsonFile" -ForegroundColor Green
            Write-Host "Created: $outputDocxFile" -ForegroundColor Green


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