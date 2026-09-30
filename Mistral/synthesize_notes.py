#!/usr/bin/env python3
"""Hierarchical synthesis: temporal evidence blocks -> discussion summaries -> final notes."""
from __future__ import annotations
import argparse,json
from datetime import datetime
from pathlib import Path
import requests
from mistral import load_json,load_evidence,load_mapping,render_markdown,write_docx,safe_filename,infer_base_name

DEFAULT_MODEL="mistral-meeting:16k"; DEFAULT_OLLAMA_URL="http://localhost:11434"; DEFAULT_EVIDENCE_PER_BLOCK=120
SUMMARY_SCHEMA={"type":"object","properties":{"discussion":{"type":"object","properties":{
"title":{"type":"string"},"summary":{"type":"string"},"key_points":{"type":"array","items":{"type":"string"}},
"decisions":{"type":"array","items":{"type":"string"}},"actions":{"type":"array","items":{"type":"string"}},
"questions":{"type":"array","items":{"type":"string"}},"important_dates":{"type":"array","items":{"type":"string"}},
"source_timestamps":{"type":"array","items":{"type":"string"}}},"required":["title","summary","key_points","decisions","actions","questions","important_dates","source_timestamps"],"additionalProperties":False}},
"required":["discussion"],"additionalProperties":False}
SUMMARY_PROMPT="""Vat één chronologisch gedeelte van een vergadering samen uit de evidence.
Gebruik uitsluitend de evidence. Verzin geen verbanden, besluiten, acties of verantwoordelijkheden.
Behoud verschillende standpunten, concrete cijfers/data/voorwaarden en belangrijke vragen.
Een voorstel is geen besluit; een suggestie is geen bevestigde actie.
Gebruik source_timestamps uitsluitend uit de aangeleverde evidence. Maak de samenvatting inhoudelijk, niet als transcriptverkorting."""
FINAL_PROMPT="""Maak rijke Nederlandse vergadernotities uit metadata, deelnemers en chronologische discussion summaries.
Gebruik uitsluitend aangeleverde informatie. Verzin niets en voeg geen nieuwe oorzaak-gevolgrelaties toe.
Een individueel standpunt is geen besluit. Een voorstel/suggestie is geen bevestigd actiepunt.
Neem alleen inhoudelijke onopgeloste vragen op. Behoud concrete data, namen, cijfers, voorwaarden en verschillen van inzicht.
Gebruik uitsluitend timestamps uit de discussion summaries.
Geef exact JSON met:
summary,
key_discussion_points[{topic,details,timestamps}],
decisions[{decision,timestamps}],
statements_and_conclusions[{statement,speaker,timestamps}],
proposed_actions[{action,responsible,deadline,timestamps}],
confirmed_action_items[{action,responsible,deadline,timestamp,timestamps}],
important_dates[{date,description,timestamps}],
open_questions[{question,timestamps}],
additional_notes[].
"""
def call(model,url,system,data,schema=None):
    payload={"model":model,"stream":False,"format":schema or "json","options":{"temperature":0.1,"num_predict":5000},
      "messages":[{"role":"system","content":system},{"role":"user","content":json.dumps(data,ensure_ascii=False,indent=2)}]}
    try:r=requests.post(url.rstrip("/")+"/api/chat",json=payload,timeout=1800)
    except requests.RequestException as exc:raise RuntimeError(f"Kan Ollama niet bereiken: {exc}") from exc
    if r.status_code!=200:raise RuntimeError(f"Ollama HTTP {r.status_code}: {r.text}")
    try:return json.loads(r.json()["message"]["content"])
    except Exception as exc:raise RuntimeError("Ollama gaf geen geldig JSON-resultaat.") from exc
def synthesize(evidence_path,participants_path,metadata_path,output_dir,model=DEFAULT_MODEL,ollama_url=DEFAULT_OLLAMA_URL,evidence_per_block=DEFAULT_EVIDENCE_PER_BLOCK):
    evidence=load_evidence(evidence_path); participants=load_mapping(participants_path,"participants"); metadata=load_json(metadata_path) if metadata_path else {}
    base=safe_filename(infer_base_name(evidence_path,metadata)); block_dir=output_dir/f"{base}_discussion_blocks"; block_dir.mkdir(parents=True,exist_ok=True)
    blocks=[evidence[i:i+evidence_per_block] for i in range(0,len(evidence),evidence_per_block)]; discussions=[]
    for i,b in enumerate(blocks,1):
        cp=block_dir/f"part{i:04d}.json"
        if cp.exists():d=load_json(cp)
        else:
            d=call(model,ollama_url,SUMMARY_PROMPT,{"evidence":b},SUMMARY_SCHEMA); cp.write_text(json.dumps(d,ensure_ascii=False,indent=2),encoding="utf-8")
        discussions.append(d["discussion"]); print(f"Discussion block {i}/{len(blocks)}")
    final=call(model,ollama_url,FINAL_PROMPT,{"meeting_metadata":metadata,"participants":participants,"discussion_summaries":discussions})
    if not isinstance(final,dict):raise RuntimeError("Finale synthese is geen JSON-object.")
    output_dir.mkdir(parents=True,exist_ok=True)
    result={"generated_date":datetime.now().isoformat(timespec="seconds"),"model":model,"project_number":metadata.get("project_number"),"project_name":metadata.get("project_name"),"meeting_details":metadata.get("meeting_details"),"filename_base":metadata.get("filename_base"),"processed_date":metadata.get("processed_date"),"participants":participants,"notes":final}
    jp=output_dir/f"{base}_meeting_notes.json"; mp=output_dir/f"{base}_meeting_notes.md"; dp=output_dir/f"{base}_meeting_notes.docx"
    jp.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8"); mp.write_text(render_markdown(final,metadata,participants),encoding="utf-8"); write_docx(dp,final,metadata,participants)
    return jp,mp,dp
def main():
    p=argparse.ArgumentParser();p.add_argument("--evidence",required=True,type=Path);p.add_argument("--participants",type=Path);p.add_argument("--metadata",type=Path);p.add_argument("--output-dir",type=Path,default=Path("3_Meeting Notes"));p.add_argument("--model",default=DEFAULT_MODEL);p.add_argument("--ollama-url",default=DEFAULT_OLLAMA_URL);p.add_argument("--evidence-per-block",type=int,default=DEFAULT_EVIDENCE_PER_BLOCK)
    a=p.parse_args();synthesize(a.evidence,a.participants,a.metadata,a.output_dir,a.model,a.ollama_url,a.evidence_per_block)
if __name__=="__main__":main()
