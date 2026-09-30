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

SYSTEM_PROMPT = """Je bent een nauwkeurige informatie-extractor voor Nederlandstalige vergadertranscripten.

Je schrijft GEEN vergadernotulen. Je extraheert alleen bewijs uit het transcript voor een tweede stap die later de vergadernotities maakt.

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
      "id": "E001",
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

Maak één evidence-item per betekenisvolle uitspraak. Verlies geen relevante informatie door te veel samen te voegen.

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

def call_ollama(model: str, ollama_url: str, participants: dict[str, str], transcript: str) -> dict[str, Any]:
    participant_text = "\n".join(f"{key} = {value}" for key, value in participants.items()) or "Geen namen beschikbaar."
    system = SYSTEM_PROMPT.replace("{{PARTICIPANTS}}", participant_text)

    payload = {
        "model": model,
        "stream": False,
        "format": "json",
        "options": {"temperature": 0.1},
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": transcript},
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
        result = json.loads(content)
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise RuntimeError("Ollama gaf geen geldig evidence JSON-resultaat terug.") from exc

    if not isinstance(result, dict) or not isinstance(result.get("evidence"), list):
        raise RuntimeError("Evidence-resultaat moet een object met een 'evidence' lijst zijn.")

    return result

def extract_evidence(transcript_path: Path, participants_path: Path | None, output_path: Path, model: str = DEFAULT_MODEL, ollama_url: str = DEFAULT_OLLAMA_URL) -> Path:
    transcript = transcript_path.read_text(encoding="utf-8-sig")
    participants = load_participants(participants_path)

    print(f"Transcript       : {transcript_path}")
    print(f"Evidence model   : {model}")
    print("Mistral evidence-extractie gestart...")

    evidence = call_ollama(model, ollama_url, participants, transcript)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Evidence         : {output_path}")
    print(f"Evidence entries : {len(evidence['evidence'])}")
    return output_path

def main() -> int:
    parser = argparse.ArgumentParser(description="Extract meeting evidence with Mistral.")
    parser.add_argument("--transcript", required=True, type=Path)
    parser.add_argument("--participants", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--ollama-url", default=DEFAULT_OLLAMA_URL)
    args = parser.parse_args()

    extract_evidence(args.transcript, args.participants, args.output, args.model, args.ollama_url)
    return 0

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(f"ERROR: {exc}")
        raise SystemExit(1)
