#!/usr/bin/env python3
"""Unattended hierarchical Mistral meeting pipeline."""
from __future__ import annotations
import argparse,json,logging,sys,time
from pathlib import Path
from extract_evidence import extract_evidence
from synthesize_notes import synthesize
from mistral import load_evidence,load_json,safe_filename

DEFAULT_WATCH_DIR=Path("2_Processing"); DEFAULT_OUTPUT_DIR=Path("3_Meeting Notes")
def setup_logging(d):
    d.mkdir(parents=True,exist_ok=True); logger=logging.getLogger("mistral-pipeline"); logger.setLevel(logging.INFO); logger.handlers.clear()
    fmt=logging.Formatter("%(asctime)s | %(levelname)s | %(message)s","%Y-%m-%d %H:%M:%S")
    for h in (logging.StreamHandler(sys.stdout),logging.FileHandler(d/"mistral_watcher.log",encoding="utf-8")):h.setFormatter(fmt);logger.addHandler(h)
    return logger
def find_transcripts(root):return sorted(p for p in root.rglob("*_for_mistral.md") if p.is_file()) if root.exists() else []
def stable(p,delay):
    if not p.exists():return False
    a=p.stat();time.sleep(delay)
    if not p.exists():return False
    b=p.stat();return a.st_size==b.st_size and a.st_mtime_ns==b.st_mtime_ns
def validate_notes(path,evidence_path,participants_path):
    data=load_json(path);notes=data.get("notes") if isinstance(data,dict) else None
    if not isinstance(notes,dict):raise RuntimeError("Meeting notes JSON bevat geen notes-object.")
    evidence=load_evidence(evidence_path);valid_ts={str(x.get("timestamp")) for x in evidence if x.get("timestamp")}
    participants=load_json(participants_path).get("participants",{})
    fields=("key_discussion_points","decisions","statements_and_conclusions","proposed_actions","confirmed_action_items","important_dates","open_questions")
    for field in fields:
        for item in notes.get(field,[]):
            if not isinstance(item,dict):continue
            ts=item.get("timestamps");ts=ts if isinstance(ts,list) else ([ts] if ts else [])
            if not ts:raise RuntimeError(f"Item in '{field}' mist timestamps.")
            if any(str(x) not in valid_ts for x in ts):raise RuntimeError(f"Item in '{field}' bevat onbekende timestamp.")
            speaker=item.get("speaker")
            if speaker and speaker not in participants.values():raise RuntimeError(f"Onbekende spreker: {speaker}")
def process_one(t,out,model,url,logger):
    participants=t.parent/"participants.json"
    if not participants.exists():logger.warning("Waiting for participants.json: %s",t.parent);return False
    base=safe_filename(t.stem.replace("_for_mistral",""));evidence=t.parent/f"{base}_evidence.json"
    if all((out/f"{base}_meeting_notes{e}").exists() for e in (".json",".md",".docx")):return True
    try:
        if not evidence.exists():
            logger.info("Stage 1/3: extracting source-linked evidence")
            extract_evidence(t,participants,evidence,model,url,segments_per_batch=80,raw_response_dir=out/"failed")
        logger.info("Stage 2/3: synthesizing temporal discussion blocks")
        logger.info("Stage 3/3: generating final meeting notes")
        metadata=t.parent/"metadata.json"
        jp,_,_=synthesize(evidence,participants,metadata if metadata.exists() else None,out,model,url,evidence_per_block=120)
        validate_notes(jp,evidence,participants);logger.info("Completed: %s",t.name);return True
    except Exception as exc:
        failed=out/"failed";failed.mkdir(parents=True,exist_ok=True)
        (failed/f"{base}.error.json").write_text(json.dumps({"transcript":str(t),"error":str(exc),"timestamp":time.strftime("%Y-%m-%dT%H:%M:%S")},ensure_ascii=False,indent=2),encoding="utf-8")
        logger.exception("Processing failed: %s",t);return False
def main():
    p=argparse.ArgumentParser();p.add_argument("--watch-dir",type=Path,default=DEFAULT_WATCH_DIR);p.add_argument("--output-dir",type=Path,default=DEFAULT_OUTPUT_DIR);p.add_argument("--poll-seconds",type=float,default=5);p.add_argument("--stable-delay",type=float,default=3);p.add_argument("--model",default="mistral-meeting:16k");p.add_argument("--ollama-url",default="http://localhost:11434");a=p.parse_args()
    a.watch_dir.mkdir(parents=True,exist_ok=True);a.output_dir.mkdir(parents=True,exist_ok=True);log=setup_logging(a.output_dir/"logs");log.info("Mistral hierarchical watcher started.")
    processed=set();failed_signatures={}
    while True:
        try:
            for t in find_transcripts(a.watch_dir):
                t=t.resolve()
                if t in processed or not stable(t,a.stable_delay):continue
                sig=(t.stat().st_size,t.stat().st_mtime_ns)
                if failed_signatures.get(t)==sig:continue
                ok=process_one(t,a.output_dir,a.model,a.ollama_url,log)
                if ok:processed.add(t)
                else:failed_signatures[t]=sig
            time.sleep(a.poll_seconds)
        except KeyboardInterrupt:log.info("Watcher stopped.");return 0
        except Exception:log.exception("Watcher error; continuing.");time.sleep(a.poll_seconds)
if __name__=="__main__":raise SystemExit(main())
