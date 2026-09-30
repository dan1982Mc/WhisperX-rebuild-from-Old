#!/usr/bin/env python3
"""Source-linked evidence extraction in bounded WhisperX segment batches."""
from __future__ import annotations
import argparse,json,re
from pathlib import Path
from typing import Any
import requests

DEFAULT_MODEL="mistral-meeting:16k"; DEFAULT_OLLAMA_URL="http://localhost:11434"; DEFAULT_SEGMENTS_PER_BATCH=80
SCHEMA={"type":"object","properties":{"evidence":{"type":"array","items":{"type":"object","properties":{
"type":{"type":"string"},"speaker_id":{"type":"string"},"speaker":{"type":"string"},"timestamp":{"type":"string"},
"content":{"type":"string"},"status":{"type":"string"},"source_segments":{"type":"array","items":{"type":"string"}}
},"required":["type","speaker_id","speaker","timestamp","content","status","source_segments"],"additionalProperties":False}}},
"required":["evidence"],"additionalProperties":False}
SYSTEM_PROMPT="""Je bent een brongetrouwe informatie-extractor voor een Nederlandstalig vergadertranscript.
Je schrijft geen vergadernotulen. Extraheer betekenisvolle bronuitingen voor een latere synthese.
Gebruik uitsluitend de aangeleverde transcriptsegmenten. Verzin niets.
Types: statement, opinion, proposal, question, decision, action, conclusion, disagreement, information, date_time.
Een voorstel is geen besluit. Een suggestie is geen bevestigde actie. Een vraag is geen antwoord.
Een individuele uitspraak is geen groepsbesluit. Behoud cijfers, namen, data, tijden, voorwaarden, alternatieven en meningsverschillen.
Behoud correcte attributie: de spreker van het huidige segment blijft de spreker, ook als die iemand anders citeert.
Raad nooit een identiteit; gebruik de mapping. Corrigeer alleen evidente WhisperX-fouten wanneer de directe context dat ondubbelzinnig ondersteunt.
Bewaar relevante onbeantwoorde vragen. Laat alleen filler en betekenisloze bevestigingen weg.
Maak één compact item per betekenisvolle bronuiting.
source_segments bevat uitsluitend segment_id's die de inhoud rechtstreeks ondersteunen, zo weinig mogelijk.
De timestamp is de timestamp van het eerste relevante bronsegment.
Geef uitsluitend geldig JSON volgens het schema. Status is explicit, reported of uncertain."""
function load_json(path:Path)->Any:
    try:return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as exc:raise RuntimeError(f"Ongeldige JSON in {path}: {exc}") from exc
function load_participants(path):
    if not path:return {}
    data=load_json(path); data=data.get("participants",data) if isinstance(data,dict) else data
    if not isinstance(data,dict):raise RuntimeError("participants.json moet een object zijn.")
    return {str(k):str(v) for k,v in data.items()}
function parse_transcript(path):
    text=path.read_text(encoding="utf-8-sig").split("\n---\n\n## Instructions for Mistral",1)[0]
    matches=list(re.finditer(r"(?m)^### \[(\d{2}:\d{2}:\d{2})\] ([^\n]+)\n",text))
    if not matches:raise RuntimeError(f"Geen transcriptsegmenten gevonden in {path}")
    out=[]
    for i,m in enumerate(matches):
        end=matches[i+1].start() if i+1<len(matches) else len(text); body=text[m.end():end].strip()
        if body:out.append({"segment_id":f"seg_{i+1:06d}","timestamp":m.group(1),"speaker_id":m.group(2).strip(),"text":body})
    return out
def call(model,url,participants,segments,raw_path=None):
    ptext="\n".join(f"{k} = {v}" for k,v in participants.items()) or "Geen namen beschikbaar."
    payload={"model":model,"stream":False,"format":SCHEMA,"options":{"temperature":0.1,"num_predict":5000},
      "messages":[{"role":"system","content":SYSTEM_PROMPT+"\nDEELNEMERS:\n"+ptext},
                  {"role":"user","content":"EXTRACTION INPUT:\n"+json.dumps(segments,ensure_ascii=False,indent=2)}]}
    try:r=requests.post(url.rstrip("/")+"/api/chat",json=payload,timeout=1800)
    except requests.RequestException as exc:raise RuntimeError(f"Kan Ollama niet bereiken: {exc}") from exc
    if r.status_code!=200:raise RuntimeError(f"Ollama HTTP {r.status_code}: {r.text}")
    try:content=r.json()["message"]["content"]; result=json.loads(content)
    except Exception as exc:
        if raw_path:raw_path.parent.mkdir(parents=True,exist_ok=True); raw_path.write_text(r.text if "content" not in locals() else content,encoding="utf-8")
        raise RuntimeError("Ollama gaf geen geldig evidence JSON-resultaat.") from exc
    if raw_path:raw_path.parent.mkdir(parents=True,exist_ok=True); raw_path.write_text(content,encoding="utf-8")
    if not isinstance(result,dict) or not isinstance(result.get("evidence"),list):raise RuntimeError("Evidence-resultaat heeft niet het verwachte schema.")
    return result
def extract_evidence(transcript_path,participants_path,output_path,model=DEFAULT_MODEL,ollama_url=DEFAULT_OLLAMA_URL,segments_per_batch=DEFAULT_SEGMENTS_PER_BATCH,raw_response_dir=None):
    participants=load_participants(participants_path); segments=parse_transcript(transcript_path)
    checkpoint_dir=output_path.parent/(output_path.stem+"_batches"); checkpoint_dir.mkdir(parents=True,exist_ok=True)
    batches=[segments[i:i+segments_per_batch] for i in range(0,len(segments),segments_per_batch)]
    all_evidence=[]; print(f"Transcript segments: {len(segments)}"); print(f"Extraction batches: {len(batches)}")
    for n,batch in enumerate(batches,1):
        cp=checkpoint_dir/f"part{n:04d}.json"
        if cp.exists():
            result=load_json(cp); print(f"Extraction batch {n}/{len(batches)}: checkpoint")
        else:
            print(f"Extraction batch {n}/{len(batches)}: {len(batch)} segments")
            raw=Path(raw_response_dir)/f"{output_path.stem}_part{n:04d}_raw.txt" if raw_response_dir else None
            result=call(model,ollama_url,participants,batch,raw)
            valid={x["segment_id"] for x in batch}
            for item in result["evidence"]:
                refs=item.get("source_segments",[])
                if not isinstance(refs,list) or not refs or any(str(x) not in valid for x in refs):
                    raise RuntimeError(f"Batch {n} bevat ongeldige source_segments.")
            cp.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
        all_evidence.extend(result["evidence"])
    output_path.parent.mkdir(parents=True,exist_ok=True)
    output_path.write_text(json.dumps({"schema_version":2,"evidence":all_evidence},ensure_ascii=False,indent=2),encoding="utf-8")
    print(f"Evidence entries: {len(all_evidence)}"); return output_path
def main():
    p=argparse.ArgumentParser(); p.add_argument("--transcript",required=True,type=Path); p.add_argument("--participants",type=Path); p.add_argument("--output",required=True,type=Path)
    p.add_argument("--model",default=DEFAULT_MODEL); p.add_argument("--ollama-url",default=DEFAULT_OLLAMA_URL); p.add_argument("--segments-per-batch",type=int,default=DEFAULT_SEGMENTS_PER_BATCH); p.add_argument("--raw-response-dir",type=Path)
    a=p.parse_args(); extract_evidence(a.transcript,a.participants,a.output,a.model,a.ollama_url,a.segments_per_batch,a.raw_response_dir)
if __name__=="__main__":
    try:main()
    except RuntimeError as exc:print(f"ERROR: {exc}");raise SystemExit(1)
