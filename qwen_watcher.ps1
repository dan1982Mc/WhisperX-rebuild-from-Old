$OutputRoot = "E:\AAA\WhisperX\Meetings\Output"
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
            # Qwen prompt
            # -------------------------------------------------

            $prompt = @"
Je maakt professionele en nauwkeurige vergadernotulen van een Nederlandstalig transcript.

Het transcript is automatisch gemaakt met WhisperX en kan kleine transcriptiefouten bevatten.

DEELNEMERS:

$participantText

Gebruik de namen uit deze deelnemersmapping voor SPEAKER_XX.

==================================================
HOOFDREGEL
==================================================

Leg vast wat er daadwerkelijk is gezegd.

Behoud relevante feitelijke informatie uit het transcript.

Interpreteer niet verder dan het transcript toestaat.

Het doel is een betrouwbare registratie van de vergadering, niet een analyse van wat deelnemers waarschijnlijk bedoelden.

Bij twijfel:

- behoud de feitelijke uitspraak;
- formuleer voorzichtig;
- gebruik "gaf aan", "zei", "stelde" of "volgens X";
- maak er geen besluit, akkoord of actiepunt van zonder duidelijke ondersteuning.

Verwijder relevante informatie niet alleen omdat deze niet perfect in een categorie past.

==================================================
TRANSCRIPTIEFOUTEN
==================================================

WhisperX kan woorden verkeerd herkennen.

Corrigeer duidelijke transcriptiefouten wanneer de betekenis uit de directe context duidelijk is.

Als een passage niet volledig duidelijk is, probeer de betekenis niet zelf in te vullen.

Gebruik dan een voorzichtige formulering.

Bijvoorbeeld:

"Richard gaf aan dat hij bij Richard Koek had gecontroleerd of het oude plan werkte."

Niet:

"Richard Koek bevestigde dat het oude plan niet werkt."

tenzij Richard Koek dit daadwerkelijk zelf zegt in het transcript.

==================================================
NAMEN
==================================================

Gebruik de deelnemersmapping voor SPEAKER_XX.

Maak geen aannames over de identiteit van personen.

Als een andere naam expliciet in het transcript wordt genoemd, mag deze naam worden gebruikt.

Combineer verschillende namen niet automatisch tot dezelfde persoon.

==================================================
BESLUITEN
==================================================

Neem alleen iets op als besluit wanneer duidelijk uit het transcript blijkt dat er een besluit of expliciete afspraak is gemaakt.

Een voorstel is geen besluit.

Een mening is geen besluit.

Een probleem is geen besluit.

Een uitspraak van één persoon is geen groepsbesluit.

"Het oude plan werkt niet" betekent niet automatisch dat er besloten is om het plan te wijzigen.

Als er geen expliciete besluiten zijn:

Geen expliciete besluiten genoemd.

==================================================
AFSPRAKEN EN ACTIEPUNTEN
==================================================

Neem een actie alleen op wanneer duidelijk is dat iemand iets moet doen.

Noem een verantwoordelijke alleen wanneer deze duidelijk uit het transcript blijkt.

Verzin geen deadlines.

Een suggestie of mogelijke actie is geen bevestigd actiepunt.

==================================================
VRAGEN
==================================================

Neem alleen duidelijke vragen op die daadwerkelijk in het transcript worden gesteld.

Maak geen vraag van een probleem dat nog niet is opgelost.

Maak geen vraag van een onafgemaakt transcriptfragment.

Bijvoorbeeld:

"Hoe gaan we dit nou..."

is geen volledige vraag en moet niet worden opgenomen als openstaande vraag.

==================================================
DATUMS EN TIJD
==================================================

Noem relevante data en tijdsaanduidingen die daadwerkelijk in het transcript voorkomen.

Zet relatieve tijdsaanduidingen zoals:

"twee weken geleden"
"anderhalve week"

niet om naar een kalenderdatum.

Maak van een tijdsaanduiding geen bespreekpunt tenzij deze daadwerkelijk inhoudelijk wordt besproken.

==================================================
SAMENVATTING
==================================================

Geef een korte feitelijke samenvatting.

Combineer uitspraken alleen wanneer daardoor geen nieuwe betekenis wordt gecreëerd.

Gebruik geen formuleringen zoals:

"De groep besloot..."
"De deelnemers waren het erover eens..."
"Er werd afgesproken..."

tenzij dit expliciet uit het transcript blijkt.

==================================================
BELANGRIJKSTE BESPREKPUNTEN
==================================================

Noem de belangrijkste onderwerpen die daadwerkelijk in het transcript worden besproken.

Neem geen losse data of tijdsaanduidingen op als onderwerp.

Neem een genoemd project, persoon of document alleen op als bespreekpunt wanneer dit daadwerkelijk onderdeel van de discussie is.

==================================================
UITSPRAKEN EN CONCLUSIES
==================================================

Gebruik deze sectie voor belangrijke uitspraken, standpunten en conclusies van deelnemers.

Vermeld de spreker wanneer dit duidelijk is.

Gebruik bijvoorbeeld:

"Richard gaf aan dat het oude plan volgens hem niet werkt."

Niet:

"De groep concludeerde dat het oude plan niet werkt."

Maak geen "bevestiging", "instemming" of "akkoord" van een indirecte uitspraak.

"Richard zei dat Richard Koek aangaf dat het oude plan niet werkt."

mag bijvoorbeeld niet automatisch worden:

"Richard Koek bevestigde dat het oude plan niet werkt."

==================================================
AANVULLENDE OPMERKINGEN
==================================================

Gebruik deze sectie voor relevante feitelijke informatie die niet logisch in een andere sectie past.

Bijvoorbeeld:

- een genoemde projectnaam;
- een document;
- een persoon die relevant wordt genoemd;
- relevante context.

Herhaal geen informatie zonder reden.

==================================================
OUTPUT
==================================================

Gebruik exact deze structuur:

# Vergadernotulen

## Deelnemers

Noem de deelnemers.

## Samenvatting

Geef een korte feitelijke samenvatting.

## Belangrijkste bespreekpunten

Noem de belangrijkste daadwerkelijk besproken onderwerpen.

## Besluiten

Noem alleen expliciete besluiten of afspraken.

Als er geen expliciete besluiten zijn:

Geen expliciete besluiten genoemd.

## Uitspraken en conclusies

Noem belangrijke uitspraken en conclusies van deelnemers.

Als er geen relevante uitspraken zijn:

Geen relevante uitspraken genoemd.

## Voorgestelde acties

Noem acties die zijn voorgesteld of besproken maar niet duidelijk bevestigd.

Als er geen voorgestelde acties zijn:

Geen voorgestelde acties genoemd.

## Bevestigde actiepunten

Gebruik deze tabel:

| Actie | Verantwoordelijke | Deadline |
|---|---|---|

Neem alleen duidelijk toegewezen of afgesproken acties op.

Als er geen bevestigde actiepunten zijn:

Geen bevestigde actiepunten genoemd.

## Belangrijke data

Noem relevante expliciete data en tijdsaanduidingen.

Als er geen relevante data zijn:

Geen belangrijke data genoemd.

## Openstaande vragen

Noem alleen duidelijke vragen die daadwerkelijk zijn gesteld.

Als er geen duidelijke vragen zijn:

Geen openstaande vragen genoemd.

## Aanvullende opmerkingen

Noem relevante feitelijke informatie die niet goed in een andere sectie past.

Als er geen aanvullende informatie is:

Geen aanvullende opmerkingen.

==================================================
BELANGRIJK
==================================================

Het onderstaande gedeelte is het volledige en daadwerkelijke transcript.

Gebruik uitsluitend dit transcript als bron voor de inhoud.

Verzin geen informatie.

Maak geen aannames.

Maak geen groepsbesluit van een individuele uitspraak.

Maak geen instemming van een indirecte uitspraak.

Maak geen actiepunt van een suggestie.

Maak geen vraag van een onafgemaakt fragment.

Behoud relevante feitelijke informatie, ook wanneer deze niet perfect in een categorie past.

Hier begint het transcript:

$transcript

Hier eindigt het transcript.
"@

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
                $file.DirectoryName `
                ($file.BaseName -replace "_for_qwen$","_meeting_notes.md")

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