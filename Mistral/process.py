#!/usr/bin/env python3
"""Run the Mistral stages on prepared WhisperX transcripts."""
from __future__ import annotations
import argparse, json, logging, sys, time
from pathlib import Path
from extract_evidence import extract_evidence
from mistral import generate_notes, load_evidence, load_json, safe_filename

DEFAULT_WATCH_DIR = Path("2_Processing")
DEFAULT_OUTPUT_DIR = Path("3_Meeting Notes")

def setup_logging(log_dir: Path) -> logging.Logger:
    log_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("mistral-pipeline")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    fmt = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s", "%Y-%m-%d %H:%M:%S")
    for handler in (logging.StreamHandler(sys.stdout), logging.FileHandler(log_dir / "mistral_watcher.log", encoding="utf-8")):
        handler.setFormatter(fmt); logger.addHandler(handler)
    return logger

def find_transcripts(root: Path):
    return sorted(p for p in root.rglob("*_for_mistral.md") if p.is_file()) if root.exists() else []

def stable(path: Path, delay: float) -> bool:
    if not path.exists(): return False
    a = path.stat(); time.sleep(delay)
    if not path.exists(): return False
    b = path.stat()
    return a.st_size == b.st_size and a.st_mtime_ns == b.st_mtime_ns

def validate_notes(notes_path: Path, evidence_path: Path, participants_path: Path) -> None:
    notes_data = load_json(notes_path)
    notes = notes_data.get("notes") if isinstance(notes_data, dict) else notes_data
    if not isinstance(notes, dict):
        raise RuntimeError("Meeting notes JSON bevat geen geldig 'notes' object.")

    evidence = load_evidence(evidence_path)
    valid_timestamps = {str(item.get("timestamp")) for item in evidence if item.get("timestamp")}

    participants_data = load_json(participants_path)
    participants = participants_data.get("participants", participants_data)
    valid_names = {str(v) for v in participants.values() if str(v).strip()} if isinstance(participants, dict) else set()

    fields = (
        "key_discussion_points", "decisions", "statements_and_conclusions",
        "proposed_actions", "confirmed_action_items", "important_dates", "open_questions"
    )
    for field in fields:
        items = notes.get(field, [])
        if not isinstance(items, list):
            raise RuntimeError(f"Notes veld '{field}' moet een lijst zijn.")
        for item in items:
            if not isinstance(item, dict):
                continue
            timestamps = item.get("timestamps")
            if not isinstance(timestamps, list) or not timestamps:
                raise RuntimeError(f"Item in '{field}' mist transcript-timestamps.")
            unknown = [str(ts) for ts in timestamps if str(ts) not in valid_timestamps]
            if unknown:
                raise RuntimeError(f"Item in '{field}' bevat onbekende timestamp(s): {unknown}")
            speaker = item.get("speaker")
            if speaker and speaker not in participants and speaker not in valid_names:
                raise RuntimeError(f"Onbekende spreker in '{field}': {speaker}")

def process_one(transcript: Path, output_dir: Path, model: str, ollama_url: str, logger: logging.Logger) -> bool:
    participants = transcript.parent / "participants.json"
    if not participants.exists():
        logger.warning("Waiting for participants.json: %s", transcript.parent)
        return False
    evidence = transcript.parent / f"{transcript.stem.replace('_for_mistral','')}_evidence.json"
    base = safe_filename(transcript.stem.replace("_for_mistral",""))
    if all((output_dir / f"{base}_meeting_notes{ext}").exists() for ext in (".json",".md",".docx")):
        logger.info("Already completed: %s", transcript.name); return True
    try:
        if not evidence.exists():
            logger.info("Stage 1/2: extracting evidence: %s", transcript.name)
            extract_evidence(transcript, participants, evidence, model, ollama_url)
        else:
            logger.info("Using existing evidence: %s", evidence)
        logger.info("Stage 2/2: generating meeting notes: %s", transcript.name)
        metadata = transcript.parent / "metadata.json"
        json_path, _, _ = generate_notes(
            evidence, participants, metadata if metadata.exists() else None,
            output_dir, model, ollama_url, save_raw_response=True
        )
        logger.info("Validating meeting notes: %s", json_path.name)
        validate_notes(json_path, evidence, participants)
        logger.info("Validation passed: %s", transcript.name)
        logger.info("Completed: %s", transcript.name)
        return True
    except Exception as exc:
        failed = output_dir / "failed"; failed.mkdir(parents=True, exist_ok=True)
        (failed / f"{base}.error.json").write_text(json.dumps({
            "transcript": str(transcript), "error": str(exc),
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S")
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.exception("Processing failed: %s", transcript)
        return False

def main() -> int:
    p=argparse.ArgumentParser()
    p.add_argument("--watch-dir", type=Path, default=DEFAULT_WATCH_DIR)
    p.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    p.add_argument("--poll-seconds", type=float, default=5)
    p.add_argument("--stable-delay", type=float, default=3)
    p.add_argument("--model", default="mistral-meeting:16k")
    p.add_argument("--ollama-url", default="http://localhost:11434")
    a=p.parse_args()
    a.watch_dir.mkdir(parents=True, exist_ok=True); a.output_dir.mkdir(parents=True, exist_ok=True)
    log=setup_logging(a.output_dir/"logs")
    log.info("Mistral pipeline watcher started.")
    log.info("Watch directory: %s", a.watch_dir.resolve())
    log.info("Output directory: %s", a.output_dir.resolve())
    log.info("Model: %s", a.model)
    processed=set(); failed_signatures={}
    while True:
        try:
            for t in find_transcripts(a.watch_dir):
                t=t.resolve()
                if t in processed or not stable(t,a.stable_delay): continue
                sig=(t.stat().st_size,t.stat().st_mtime_ns)
                if failed_signatures.get(t)==sig: continue
                ok=process_one(t,a.output_dir,a.model,a.ollama_url,log)
                if ok: processed.add(t)
                else: failed_signatures[t]=sig
            time.sleep(a.poll_seconds)
        except KeyboardInterrupt:
            log.info("Mistral pipeline watcher stopped."); return 0
        except Exception:
            log.exception("Watcher error; continuing."); time.sleep(a.poll_seconds)

if __name__=="__main__":
    raise SystemExit(main())
