#!/usr/bin/env python3
"""
Watch for WhisperX evidence files and generate meeting notes with Mistral/Ollama.

The watcher processes files ending in "_evidence.json" recursively below the
watch directory. If a sibling "participants.json" exists, it is supplied to
the Mistral generator.

The watcher does not move or delete source evidence. Failed runs are logged
under the output directory so the source remains available for retry.

Example:
    python Mistral/watcher.py --watch-dir "2_Processing"

Dependencies:
    pip install requests python-docx
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

from mistral import generate_notes, infer_base_name, safe_filename


DEFAULT_WATCH_DIR = Path("2_Processing")
DEFAULT_OUTPUT_DIR = Path("3_Meeting Notes")
DEFAULT_POLL_SECONDS = 5
DEFAULT_STABLE_CHECKS = 2
DEFAULT_STABLE_DELAY = 3


def setup_logging(log_dir: Path) -> logging.Logger:
    log_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("mistral-watcher")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(message)s",
        "%Y-%m-%d %H:%M:%S",
    )

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    logger.addHandler(console)

    file_handler = logging.FileHandler(
        log_dir / "mistral_watcher.log",
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger


def find_evidence_files(watch_dir: Path) -> list[Path]:
    if not watch_dir.exists():
        return []
    return sorted(
        path
        for path in watch_dir.rglob("*_evidence.json")
        if path.is_file()
    )


def output_complete(evidence_path: Path, output_dir: Path) -> bool:
    base = safe_filename(infer_base_name(evidence_path, {}))
    return all(
        (output_dir / filename).exists()
        for filename in (
            f"{base}_meeting_notes.json",
            f"{base}_meeting_notes.md",
            f"{base}_meeting_notes.docx",
        )
    )


def wait_until_stable(
    path: Path,
    checks: int,
    delay: float,
    logger: logging.Logger,
) -> bool:
    previous_size = -1
    previous_mtime = -1.0

    for _ in range(checks):
        if not path.exists():
            return False

        stat = path.stat()
        current_size = stat.st_size
        current_mtime = stat.st_mtime

        if current_size == previous_size and current_mtime == previous_mtime:
            return True

        previous_size = current_size
        previous_mtime = current_mtime
        time.sleep(delay)

    if not path.exists():
        return False

    stat = path.stat()
    stable = stat.st_size == previous_size and stat.st_mtime == previous_mtime
    if not stable:
        logger.warning("Bestand verandert nog steeds: %s", path)
    return stable


def load_participants(evidence_path: Path) -> Path | None:
    candidate = evidence_path.parent / "participants.json"
    return candidate if candidate.exists() else None


def process_one(
    evidence_path: Path,
    output_dir: Path,
    model: str,
    ollama_url: str,
    save_raw_response: bool,
    logger: logging.Logger,
) -> bool:
    if output_complete(evidence_path, output_dir):
        logger.info("Al verwerkt, overslaan: %s", evidence_path)
        return True

    logger.info("Nieuwe evidence gevonden: %s", evidence_path)

    participants_path = load_participants(evidence_path)
    if participants_path:
        logger.info("Participants: %s", participants_path)

    try:
        generate_notes(
            evidence_path=evidence_path,
            participants_path=participants_path,
            output_dir=output_dir,
            model=model,
            ollama_url=ollama_url,
            save_raw_response=save_raw_response,
        )
    except Exception as exc:
        failed_dir = output_dir / "failed"
        failed_dir.mkdir(parents=True, exist_ok=True)

        base = safe_filename(infer_base_name(evidence_path, {}))
        failure_path = failed_dir / f"{base}.error.json"
        failure_path.write_text(
            json.dumps(
                {
                    "evidence": str(evidence_path),
                    "error": str(exc),
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        logger.exception("Verwerking mislukt: %s", evidence_path)
        return False

    logger.info("Verwerking geslaagd: %s", evidence_path)
    return True


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Watch WhisperX evidence files and generate Mistral meeting notes."
    )
    parser.add_argument("--watch-dir", type=Path, default=DEFAULT_WATCH_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--poll-seconds", type=float, default=DEFAULT_POLL_SECONDS)
    parser.add_argument("--stable-checks", type=int, default=DEFAULT_STABLE_CHECKS)
    parser.add_argument("--stable-delay", type=float, default=DEFAULT_STABLE_DELAY)
    parser.add_argument("--model", default="mistral-meeting:16k")
    parser.add_argument("--ollama-url", default="http://localhost:11434")
    parser.add_argument("--save-raw-response", action="store_true")
    args = parser.parse_args()

    if args.stable_checks < 1:
        parser.error("--stable-checks moet minimaal 1 zijn.")
    if args.poll_seconds <= 0 or args.stable_delay <= 0:
        parser.error("Polling- en stable-delay moeten groter dan 0 zijn.")

    args.watch_dir.mkdir(parents=True, exist_ok=True)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    logger = setup_logging(args.output_dir / "logs")
    logger.info("Mistral watcher gestart.")
    logger.info("Watch directory: %s", args.watch_dir.resolve())
    logger.info("Output directory: %s", args.output_dir.resolve())
    logger.info("Model: %s", args.model)

    processed: set[Path] = set()
    failed_signatures: dict[Path, tuple[int, int]] = {}

    while True:
        try:
            for evidence_path in find_evidence_files(args.watch_dir):
                evidence_path = evidence_path.resolve()

                if not evidence_path.exists():
                    continue

                signature = (evidence_path.stat().st_size, evidence_path.stat().st_mtime_ns)

                if evidence_path in processed:
                    continue

                if failed_signatures.get(evidence_path) == signature:
                    continue

                if not wait_until_stable(
                    evidence_path,
                    args.stable_checks,
                    args.stable_delay,
                    logger,
                ):
                    continue

                success = process_one(
                    evidence_path=evidence_path,
                    output_dir=args.output_dir,
                    model=args.model,
                    ollama_url=args.ollama_url,
                    save_raw_response=args.save_raw_response,
                    logger=logger,
                )

                if success:
                    processed.add(evidence_path)
                    failed_signatures.pop(evidence_path, None)
                else:
                    failed_signatures[evidence_path] = signature

            time.sleep(args.poll_seconds)

        except KeyboardInterrupt:
            logger.info("Mistral watcher gestopt.")
            return 0
        except Exception:
            logger.exception("Watcher-fout; watcher blijft actief.")
            time.sleep(args.poll_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
