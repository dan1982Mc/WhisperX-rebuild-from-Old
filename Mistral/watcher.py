#!/usr/bin/env python3
"""Watch prepared WhisperX transcripts and run the complete Mistral pipeline."""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

from extract_evidence import extract_evidence
from mistral import generate_notes, infer_base_name, safe_filename

DEFAULT_WATCH_DIR = Path("2_Processing")
DEFAULT_OUTPUT_DIR = Path("3_Meeting Notes")

def setup_logging(log_dir: Path) -> logging.Logger:
    log_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("mistral-watcher")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s", "%Y-%m-%d %H:%M:%S")
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    logger.addHandler(console)
    file_handler = logging.FileHandler(log_dir / "mistral_watcher.log", encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    return logger

def find_transcripts(watch_dir: Path) -> list[Path]:
    if not watch_dir.exists():
        return []
    return sorted(p for p in watch_dir.rglob("*_for_mistral.md") if p.is_file())

def stable(path: Path, delay: float) -> bool:
    if not path.exists():
        return False
    first = path.stat()
    time.sleep(delay)
    if not path.exists():
        return False
    second = path.stat()
    return first.st_size == second.st_size and first.st_mtime_ns == second.st_mtime_ns

def participants_path(transcript: Path) -> Path | None:
    p = transcript.parent / "participants.json"
    return p if p.exists() else None

def evidence_path(transcript: Path) -> Path:
    return transcript.parent / f"{transcript.stem.replace('_for_mistral', '')}_evidence.json"

def notes_complete(transcript: Path, output_dir: Path) -> bool:
    base = safe_filename(transcript.stem.replace("_for_mistral", ""))
    return all((output_dir / f"{base}_meeting_notes{ext}").exists() for ext in (".json", ".md", ".docx"))

def process_one(transcript: Path, output_dir: Path, model: str, ollama_url: str, logger: logging.Logger) -> bool:
    if notes_complete(transcript, output_dir):
        logger.info("Already completed: %s", transcript)
        return True

    pfile = participants_path(transcript)
    if pfile is None:
        logger.warning("Waiting for participants.json: %s", transcript.parent)
        return False

    efile = evidence_path(transcript)

    try:
        if not efile.exists():
            logger.info("Stage 1/2: extracting evidence: %s", transcript.name)
            extract_evidence(transcript, pfile, efile, model, ollama_url)
        else:
            logger.info("Using existing evidence: %s", efile)

        logger.info("Stage 2/2: generating meeting notes: %s", transcript.name)
        generate_notes(
            evidence_path=efile,
            participants_path=pfile,
            output_dir=output_dir,
            model=model,
            ollama_url=ollama_url,
            save_raw_response=True,
        )
        logger.info("Completed: %s", transcript)
        return True
    except Exception as exc:
        failed_dir = output_dir / "failed"
        failed_dir.mkdir(parents=True, exist_ok=True)
        base = safe_filename(transcript.stem.replace("_for_mistral", ""))
        (failed_dir / f"{base}.error.json").write_text(
            json.dumps(
                {"transcript": str(transcript), "error": str(exc), "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S")},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        logger.exception("Processing failed: %s", transcript)
        return False

def main() -> int:
    parser = argparse.ArgumentParser(description="Run the complete Mistral meeting pipeline.")
    parser.add_argument("--watch-dir", type=Path, default=DEFAULT_WATCH_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--poll-seconds", type=float, default=5)
    parser.add_argument("--stable-delay", type=float, default=3)
    parser.add_argument("--model", default="mistral-meeting:16k")
    parser.add_argument("--ollama-url", default="http://localhost:11434")
    args = parser.parse_args()

    args.watch_dir.mkdir(parents=True, exist_ok=True)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    logger = setup_logging(args.output_dir / "logs")

    logger.info("Mistral pipeline watcher started.")
    logger.info("Watch directory: %s", args.watch_dir.resolve())
    logger.info("Output directory: %s", args.output_dir.resolve())
    logger.info("Model: %s", args.model)

    processed: set[Path] = set()

    while True:
        try:
            for transcript in find_transcripts(args.watch_dir):
                transcript = transcript.resolve()
                if transcript in processed:
                    continue
                if not stable(transcript, args.stable_delay):
                    continue

                success = process_one(transcript, args.output_dir, args.model, args.ollama_url, logger)
                if success:
                    processed.add(transcript)

            time.sleep(args.poll_seconds)
        except KeyboardInterrupt:
            logger.info("Mistral pipeline watcher stopped.")
            return 0
        except Exception:
            logger.exception("Watcher error; continuing.")
            time.sleep(args.poll_seconds)

if __name__ == "__main__":
    raise SystemExit(main())
