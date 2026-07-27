"""SA Copilot — presenter-only webinar demo app. Runs locally; never deployed.

Run:  uvicorn copilot.app:app --port 8801
Env:  DO_INFERENCE_KEY (webinar key) · DO_API_TOKEN (READ-ONLY) · COPILOT_MODEL (kimi-k3)
      COMPARATOR_MODEL (e.g. anthropic-claude-opus-5) · COPILOT_REPO_DIR (customer repo)
      COPILOT_SITE_URL · PRICE_IN_<MODEL>/PRICE_OUT_<MODEL> per-mtok (optional, for cost lines)
"""
from __future__ import annotations

import json
import os

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel

from engine import Copilot
from tools import Toolbox

app = FastAPI(title="SA Copilot (webinar)")

BASE_URL = os.environ.get("DO_INFERENCE_URL", "https://inference.do-ai.run/v1")


def _price(model: str, direction: str) -> float:
    key = f"PRICE_{direction}_{model.upper().replace('-', '_').replace('.', '_')}"
    try:
        return float(os.environ.get(key, "0"))
    except ValueError:
        return 0.0


def build(model: str) -> Copilot:
    tb = Toolbox(
        api_token=os.environ.get("DO_API_TOKEN", ""),
        repo_dir=os.environ.get("COPILOT_REPO_DIR", "./sample-repo"),
        site_url=os.environ.get("COPILOT_SITE_URL", "https://www.digitalocean.com"),
    )
    return Copilot(
        base_url=BASE_URL,
        api_key=os.environ["DO_INFERENCE_KEY"],
        model=model,
        toolbox=tb,
        price_in=_price(model, "IN"),
        price_out=_price(model, "OUT"),
        price_cached=_price(model, "CACHED"),
    )


class RunReq(BaseModel):
    task: str
    model: str | None = None


@app.post("/run")
def run(req: RunReq):
    allowed = {os.environ.get("COPILOT_MODEL", "kimi-k3"),
               os.environ.get("COMPARATOR_MODEL", "")} - {""}
    model = req.model or os.environ.get("COPILOT_MODEL", "kimi-k3")
    if model not in allowed:
        model = os.environ.get("COPILOT_MODEL", "kimi-k3")
    pilot = build(model)

    def gen():
        try:
            for ev in pilot.run(req.task[:4000]):
                yield f"data: {json.dumps(ev)}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'ev': 'error', 'error': str(e)[:400]})}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")


@app.get("/", response_class=HTMLResponse)
def ui():
    k3 = os.environ.get("COPILOT_MODEL", "kimi-k3")
    cmp_ = os.environ.get("COMPARATOR_MODEL", "")
    return HTML.replace("__K3__", k3).replace("__CMP__", cmp_)


HTML = """<!doctype html><html><head><meta charset="utf-8"><title>SA Copilot — K3 on DigitalOcean</title>
<style>
 body{margin:0;font:14px/1.5 -apple-system,Segoe UI,sans-serif;background:#0b1220;color:#dbe4f0;display:grid;grid-template-rows:auto 1fr auto;height:100vh}
 header{padding:10px 16px;background:#101a2e;display:flex;gap:10px;align-items:center}
 header b{color:#4da3ff} select,input,button{background:#182742;border:1px solid #2a3c60;color:#dbe4f0;border-radius:6px;padding:6px 10px}
 input{flex:1} button{cursor:pointer;background:#1d4ed8;border:0} button:disabled{opacity:.5}
 main{display:grid;grid-template-columns:1.2fr .8fr;gap:1px;background:#1c2a44;overflow:hidden}
 section{background:#0b1220;overflow-y:auto;padding:14px 16px}
 .step{color:#7fa8d9;font-size:12px;margin:8px 0 2px}
 .tool{background:#0f1b31;border-left:3px solid #22c55e;border-radius:4px;padding:6px 10px;margin:6px 0;font-family:ui-monospace,monospace;font-size:12px;white-space:pre-wrap}
 .tool .nm{color:#22c55e;font-weight:600}
 .txt{white-space:pre-wrap;margin:6px 0}
 footer{padding:8px 16px;background:#101a2e;font-family:ui-monospace,monospace;font-size:12px;color:#9fb6d4}
 .thinking{color:#f59e0b}
</style></head><body>
<header><b>SA&nbsp;Copilot</b>
 <select id=model><option>__K3__</option><option>__CMP__</option></select>
 <input id=task value="Our app is in this repo. Get it running on DigitalOcean: read the repo and the architecture diagram, pick region and size with live pricing, validate an app spec, and give me the monthly number. Then screenshot the deployed site and confirm it looks healthy.">
 <button id=go onclick="run()">Run</button>
</header>
<main><section id=out></section><section id=log></section></main>
<footer id=totals>ready</footer>
<script>
async function run(){
 const out=document.getElementById('out'),log=document.getElementById('log'),tot=document.getElementById('totals');
 out.innerHTML='';log.innerHTML='';tot.textContent='running…';document.getElementById('go').disabled=true;
 const r=await fetch('/run',{method:'POST',headers:{'Content-Type':'application/json'},
   body:JSON.stringify({task:document.getElementById('task').value,model:document.getElementById('model').value})});
 const rd=r.body.getReader(),dec=new TextDecoder();let buf='';
 while(true){const{done,value}=await rd.read();if(done)break;buf+=dec.decode(value,{stream:true});
  let i;while((i=buf.indexOf('\\n\\n'))>=0){const line=buf.slice(0,i);buf=buf.slice(i+2);
   if(!line.startsWith('data: '))continue;const ev=JSON.parse(line.slice(6));
   if(ev.ev==='step'){const d=document.createElement('div');d.className='step';
     d.textContent=`step ${ev.n} · ${ev.model} · ${ev.sec}s · in ${ev.prompt_tokens}${ev.cached_tokens?` (cached ${ev.cached_tokens})`:''} · out ${ev.completion_tokens}${ev.reasoning_tokens?` (thinking ${ev.reasoning_tokens})`:''}`;
     log.appendChild(d);}
   else if(ev.ev==='tool'){const d=document.createElement('div');d.className='tool';
     d.innerHTML=`<span class=nm>⚙ ${ev.name}</span> ${JSON.stringify(ev.args)} · ${ev.ms}ms\\n${ev.result_preview.replace(/</g,'&lt;')}`;
     log.appendChild(d);log.scrollTop=log.scrollHeight;}
   else if(ev.ev==='text'){const d=document.createElement('div');d.className='txt';d.textContent=ev.delta;out.appendChild(d);out.scrollTop=out.scrollHeight;}
   else if(ev.ev==='done'){const t=ev.totals;
     tot.textContent=`DONE · ${t.steps} steps · ${t.tool_calls} tool calls · ${t.wall_s}s · in ${t.prompt_tokens} (cached ${t.cached_tokens}) · out ${t.completion_tokens} (thinking ${t.reasoning_tokens})`+(t.cost_usd!=null?` · $${t.cost_usd}`:'');}
   else if(ev.ev==='error'){tot.textContent='ERROR: '+ev.error;}
 }}
 document.getElementById('go').disabled=false;
}
</script></body></html>"""
