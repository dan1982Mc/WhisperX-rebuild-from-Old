#!/usr/bin/env python3
"""Extract structured meeting evidence from a prepared WhisperX transcript using Mistral/Ollama."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import requests

DEFAULT_MODEL = "mistral-meeting:16k"
DEFAULT_OLLAMA_URL = "http://localhost:11434"
DEFAULT_MAX_CHARS_PER_CHUNK = 24000

EVIDENCE_SCHEMA = {
    "type": "object",
    "properties": {
        "evidence": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "type": {"type": "string"},
                    "speaker_id": {"type": "string"},
                    "speaker": {"type": "string"},
                    "timestamp": {"type": "string"},
                    "content": {"type": "string"},
                    "status": {"type": "string"},
                    "source_text": {"type": "string"},
                },
                "required": [
                    "type", "speaker_id", "speaker", "timestamp",
                    "content", "status", "source_text"
                ],
                "additionalProperties": False,
            },
        }
    },
    "required": ["evidence"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = """Je bent een nauwkeurige informatie-extractor voor Nederlandstalige vergadertranscripten.

Je schrijft GEEN vergadernotulen. Je bouwt een zo volledig mogelijke, brongetrouwe tussenlaag voor een tweede stap die later de echte vergadernotities maakt.

Doel:
- Bewaar inhoudelijke informatie uit het transcript.
- Verlies geen relevante informatie alleen omdat iets kort of informeel lijkt.
- Laat de tweede stap bepalen wat uiteindelijk in de vergadernotities thuishoort.
- Voeg zelf geen betekenis, oorzaak, gevolg of conclusie toe.

Het transcript is de enige bron van waarheid.

DEELNEMERS:
{{PARTICIPANTS}}

Gebruik de deelnemersmapping voor SPEAKER_XX. Raad nooit een identiteit.

Extraheer inhoudelijk relevante informatie zonder voortijdig samen te vatten.

Gebruik uitsluitend deze types:
- statement
- opinion
- proposal
- question
- decision
- action
- conclusion
- disagreement
- information
- date_time

Regels:
- Een voorstel is geen besluit.
- Een suggestie is geen bevestigde actie.
- Een vraag is geen antwoord.
- Een individuele uitspraak is geen groepsbesluit.
- Behoud meningsverschillen en alternatieve standpunten.
- Behoud relevante cijfers, namen, data, tijden en voorwaarden.
- Bewaar attribution: als A rapporteert wat B zei of deed, blijft A de spreker die dit rapporteert.
- Corrigeer alleen evidente WhisperX-fouten wanneer de directe context dit ondubbelzinnig ondersteunt.
- Gebruik geen algemene kennis.
- Vul geen ontbrekende informatie in.
- Bij onzekerheid: status "uncertain".
- Bewaar relevante onbeantwoorde vragen.
- Maak geen volledige vraag van een onafgemaakt fragment.

Geef uitsluitend één geldig JSON-object, zonder Markdown fences:

{
  "evidence": [
    {
      "type": "statement",
      "speaker_id": "SPEAKER_00",
      "speaker": "Naam",
      "timestamp": "00:00:00",
      "content": "Feitelijk geëxtraheerde inhoud.",
      "status": "explicit",
      "source_text": "Relevante oorspronkelijke transcripttekst"
    }
  ]
}

Status:
- explicit = rechtstreeks uit het transcript
- reported = door een spreker gerapporteerd over iets dat iemand anders zei/deed
- uncertain = betekenis of formulering blijft onzeker

Maak één item per betekenisvolle bronuiting. Verlies geen relevante informatie door te veel samen te voegen.
Voeg geen evidence-ID toe; de timestamp is de bronverwijzing.
Bewaar korte uitspraken wanneer ze inhoudelijk relevant zijn.
Laat alleen filler, begroetingen en betekenisloze bevestigingen weg.

Controleer vóór output:
- Zijn voorstellen voorstellen gebleven?
- Zijn alleen expliciete besluiten als decision gemarkeerd?
- Zijn vragen behouden?
- Is attributie behouden?
- Zijn cijfers, data en voorwaarden behouden?
- Staat er niets in content dat niet door source_text wordt ondersteund?
"""

def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError as exc:
        raise RuntimeError(f"Bestand niet gevonden: {path}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Ongeldige JSON in {path}: {exc}") from exc

def load_participants(path: Path | None) -> dict[str, str]:
    if path is None:
        return {}
    data = load_json(path)
    if isinstance(data, dict) and isinstance(data.get("participants"), dict):
        data = data["participants"]
    if not isinstance(data, dict):
        raise RuntimeError(f"Participants moet een JSON object zijn: {path}")
    return {str(k): str(v) for k, v in data.items()}

def call_ollama(
    model: str,
    ollama_url: str,
    participants: dict[str, str],
    transcript: str,
    raw_response_path: Path | None = None,
) -> dict[str, Any]:
    participant_text = "\n".join(
        f"{key} = {value}" for key, value in participants.items()
    ) or "Geen namen beschikbaar."

    system = SYSTEM_PROMPT.replace("{{PARTICIPANTS}}", participant_text)

    payload = {
        "model": model,
        "stream": False,
        # Use Ollama structured output instead of generic JSON mode.
        # Generic JSON mode only guarantees valid JSON, not the required schema.
        "format": EVIDENCE_SCHEMA,
        "options": {"temperature": 0.1},
        "messages": [
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": (
                    "EXTRACTION INPUT. Analyseer uitsluitend de onderstaande "
                    "WhisperX-transcripttekst. Geef uitsluitend het gevraagde "
                    "evidence-object terug.\n\n"
                    + transcript
                ),
            },
        ],
    }

    endpoint = ollama_url.rstrip("/") + "/api/chat"
    try:
        response = requests.post(endpoint, json=payload, timeout=1800)
    except requests.RequestException as exc:
        raise RuntimeError(f"Kan Ollama niet bereiken op {endpoint}: {exc}") from exc

    if response.status_code != 200:
        raise RuntimeError(f"Ollama gaf HTTP {response.status_code}: {response.text}")

    try:
        content = response.json()["message"]["content"]
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise RuntimeError("Ollama-response bevat geen geldig message.content veld.") from exc

    if raw_response_path is not None:
        raw_response_path.parent.mkdir(parents=True, exist_ok=True)
        raw_response_path.write_text(content, encoding="utf-8")

    try:
        result = json.loads(content)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"Ollama gaf geen geldig evidence JSON-resultaat terug. "
            f"Ruwe response opgeslagen in: {raw_response_path}"
        ) from exc

    if not isinstance(result, dict) or not isinstance(result.get("evidence"), list):
        raise RuntimeError(
            "Evidence-resultaat moet een object met een 'evidence' lijst zijn. "
            f"Ruwe response opgeslagen in: {raw_response_path}"
        )

    return result

def prepare_transcript_text(transcript: str) -> str:
    """Keep only the actual transcript and remove the generated instruction footer."""
    marker = "\n---\n\n## Instructions for Mistral"
    if marker in transcript:
        transcript = transcript.split(marker, 1)[0]
    return transcript.strip()

def split_transcript(transcript: str, max_chars: int) -> list[str]:
    """Split at WhisperX segment boundaries, never in the middle of a segment."""
    transcript = prepare_transcript_text(transcript)
    if len(transcript) <= max_chars:
        return [transcript]

    import re

    matches = list(re.finditer(r"(?m)^### \[\d{2}:\d{2}:\d{2}\] ", transcript))
    if not matches:
        raise RuntimeError(
            f"Transcript is {len(transcript)} characters long and contains no "
            "recognizable WhisperX segment boundaries."
        )

    prefix = transcript[:matches[0].start()].strip()
    chunks: list[str] = []
    current = prefix

    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(transcript)
        segment = transcript[match.start():end].strip()
        candidate = f"{current}\n\n{segment}".strip() if current else segment

        if current and len(candidate) > max_chars:
            chunks.append(current)
            current = f"{prefix}\n\n{segment}".strip() if prefix else segment
        else:
            current = candidate

    if current:
        chunks.append(current)

    return chunks


def extract_evidence(
    transcript_path: Path,
    participants_path: Path | None,
    output_path: Path,
    model: str = DEFAULT_MODEL,
    ollama_url: str = DEFAULT_OLLAMA_URL,
    raw_response_path: Path | None = None,
    max_chars_per_chunk: int = DEFAULT_MAX_CHARS_PER_CHUNK,
) -> Path:
    transcript = transcript_path.read_text(encoding="utf-8-sig")
    participants = load_participants(participants_path)
    chunks = split_transcript(transcript, max_chars_per_chunk)

    print(f"Transcript       : {transcript_path}")
    print(f"Evidence model   : {model}")
    print(f"Transcript chars : {len(prepare_transcript_text(transcript))}")
    print(f"Evidence chunks  : {len(chunks)}")
    print("Mistral evidence-extractie gestart...")

    all_evidence: list[dict[str, Any]] = []

    for index, chunk in enumerate(chunks, start=1):
        if raw_response_path is not None:
            if len(chunks) == 1:
                chunk_raw_path = raw_response_path
            else:
                chunk_raw_path = raw_response_path.with_name(
                    f"{raw_response_path.stem}_part{index:03d}{raw_response_path.suffix}"
                )
        else:
            chunk_raw_path = None

        print(f"Evidence chunk   : {index}/{len(chunks)} ({len(chunk)} chars)")
        result = call_ollama(
            model,
            ollama_url,
            participants,
            chunk,
            chunk_raw_path,
        )
        all_evidence.extend(result["evidence"])

    combined = {"evidence": all_evidence}
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(combined, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"Evidence         : {output_path}")
    print(f"Evidence entries : {len(all_evidence)}")
    return output_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract meeting evidence with Mistral.")
    parser.add_argument("--transcript", required=True, type=Path)
    parser.add_argument("--participants", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--ollama-url", default=DEFAULT_OLLAMA_URL)
    parser.add_argument("--max-chars-per-chunk", type=int, default=DEFAULT_MAX_CHARS_PER_CHUNK)
    args = parser.parse_args()

    extract_evidence(\n        args.transcript, args.participants, args.output, args.model, args.ollama_url,\n        max_chars_per_chunk=args.max_chars_per_chunk\n    )
    return 0

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(f"ERROR: {exc}")
        raise SystemExit(1)
