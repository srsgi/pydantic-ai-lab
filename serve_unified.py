"""Unified lab hub: one URL — an Agent dropdown plus Telemetry.

Run: uv run uvicorn serve_unified:app --host 0.0.0.0 --port 7940
Open: http://localhost:7940  (single dashboard entry: Pydantic AI Lab)

Dropdown lazy-loads each agent UI in an iframe (same origins, no proxy):
  Research  -> http://localhost:7933 (Researcher chat, fresh prompts)
  Approval  -> http://localhost:7932 (HITL approval chat)
  ACP Test  -> http://localhost:7941 (drive ACP backends one by one)
Telemetry tab -> http://127.0.0.1:6006 (Phoenix traces, parked when hidden).
Backends are started/stopped from the Service Dashboard entries.
"""
import os

BACKENDS = {
    "research": os.getenv("HUB_RESEARCH_URL", "http://localhost:7933"),
    "approval": os.getenv("HUB_APPROVAL_URL", "http://localhost:7932"),
    "acptest": os.getenv("HUB_ACPTEST_URL", "http://localhost:7941"),
    "telemetry": os.getenv("HUB_TELEMETRY_URL", "http://127.0.0.1:6006"),
}

HUB_HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Pydantic AI Lab</title>
<style>
:root{color-scheme:dark}*{box-sizing:border-box}
body{margin:0;font-family:system-ui,sans-serif;background:#0b0e14;color:#e6e9f0;height:100vh;display:flex;flex-direction:column}
header{display:flex;gap:8px;align-items:center;padding:10px 14px;background:#11151d;border-bottom:1px solid #232a38}
header h1{font-size:15px;margin:0 12px 0 0;font-weight:600}
.tab{border:1px solid #2a3345;background:transparent;color:#cfd6e4;border-radius:8px;padding:8px 16px;cursor:pointer;font-size:14px}
.tab.active{background:#2563eb;border-color:#2563eb;color:#fff}
select.tab option{background:#11151d;color:#e6e9f0}
main{flex:1;position:relative}
iframe{position:absolute;inset:0;width:100%;height:100%;border:0;display:none;background:#fff}
iframe.active{display:block}
.hint{margin-left:auto;font-size:12px;color:#8b93a7}
#v-direct{display:none;position:absolute;inset:0;flex-direction:column;background:#0b0e14}
#v-direct.active{display:flex}
#d-log{flex:1;overflow-y:auto;padding:16px;display:flex;flex-direction:column;gap:10px}
.msg{max-width:75%;padding:10px 14px;border-radius:10px;font-size:14px;line-height:1.5;white-space:pre-wrap}
.msg.user{align-self:flex-end;background:#2563eb;color:#fff}
.msg.cli{align-self:flex-start;background:#1a2130;border:1px solid #2a3345}
.msg .who{font-size:11px;color:#8b93a7;margin-bottom:4px}
.msg .tools{font-size:11px;color:#8b93a7;margin-top:6px}
details.steps{margin-top:8px;font-size:12px}
details.steps summary{cursor:pointer;color:#8b93a7}
.step{border-top:1px solid #232a38;padding:6px 2px;font-family:monospace;font-size:11px;word-break:break-word}
.step b{color:#7dd3fc;font-weight:600}
#d-bar{display:flex;gap:8px;padding:12px 14px;border-top:1px solid #232a38;align-items:center}
#d-backend{background:#11151d;color:#e6e9f0;border:1px solid #2a3345;border-radius:8px;padding:8px}
#d-backend option{background:#11151d}
#d-input{flex:1;background:#11151d;color:#e6e9f0;border:1px solid #2a3345;border-radius:8px;padding:10px 12px;font-size:14px}
#d-send{background:#2563eb;color:#fff;border:0;border-radius:8px;padding:10px 18px;cursor:pointer;font-size:14px}
#d-send:disabled{opacity:.5}
</style></head><body>
<header><h1>Pydantic AI Lab</h1>
<select id="agent" class="tab active">
<option value="research">Research</option>
<option value="approval">Approval</option>
<option value="acptest">ACP Test</option>
</select>
<button class="tab" data-t="direct">Direct</button>
<button class="tab" data-t="telemetry">Telemetry</button>
<span class="hint">backends managed in Service Dashboard</span></header>
<main>
<iframe id="f-research" class="active"></iframe>
<iframe id="f-approval"></iframe>
<iframe id="f-acptest"></iframe>
<iframe id="f-telemetry"></iframe>
<div id="v-direct">
<div id="d-log"></div>
<div id="d-bar">
<select id="d-backend"></select>
<input id="d-input" placeholder="Message the CLI directly — no parent model…" />
<button id="d-send">Send</button>
</div>
</div>
</main>
<script>
const URLS = __URLS__;
const loaded = {research: false, approval: false, acptest: false, telemetry: false};
let dBackend = null;
function showFrame(name){
  document.querySelectorAll('iframe').forEach(f=>f.classList.remove('active'));
  document.getElementById('v-direct').classList.remove('active');
  if(name === 'direct'){ document.getElementById('v-direct').classList.add('active'); return; }
  const f = document.getElementById('f-'+name);
  f.classList.add('active');
  if(!loaded[name]){ f.src = URLS[name]; loaded[name]=true; }
}
function markActive(name){
  const sel = document.getElementById('agent');
  document.querySelectorAll('[data-t]').forEach(b=>b.classList.remove('active'));
  if(name === 'telemetry' || name === 'direct'){
    sel.classList.remove('active');
    document.querySelector('[data-t="'+name+'"]').classList.add('active');
  } else {
    sel.value = name; sel.classList.add('active');
  }
}
function show(name){
  markActive(name);
  showFrame(name);
  // Park the Phoenix SPA when hidden: it polls GraphQL continuously (~30%
  // server CPU idle). Traces persist server-side; chats keep their state.
  const t = document.getElementById('f-telemetry');
  if(name !== 'telemetry' && loaded.telemetry){ t.src = 'about:blank'; loaded.telemetry = false; }
}
async function dInit(){
  const r = await fetch('/api/direct/backends'); const j = await r.json();
  const sel = document.getElementById('d-backend');
  j.backends.forEach(b=>{ const o=document.createElement('option'); o.value=b; o.textContent=b; sel.appendChild(o); });
  dBackend = sel.value = j.backends[0];
  sel.onchange = ()=>{ dBackend = sel.value; dRender(); };
  document.getElementById('d-send').onclick = dSend;
  document.getElementById('d-input').onkeydown = (e)=>{ if(e.key==='Enter') dSend(); };
}
async function dRender(){
  const r = await fetch('/api/direct/history?backend='+encodeURIComponent(dBackend));
  const turns = await r.json();
  const log = document.getElementById('d-log'); log.innerHTML = '';
  turns.forEach(t=>{
    const d = document.createElement('div');
    d.className = 'msg ' + (t.role === 'user' ? 'user' : 'cli');
    d.innerHTML = '<div class="who">'+t.role+'</div><div class="txt"></div>' +
      (t.tools && t.tools.length ? '<div class="tools">tools: '+t.tools.join(', ')+'</div>' : '') +
      (t.steps && t.steps.length ? '<details class="steps"><summary>steps ('+t.steps.length+')</summary><div class="steplist"></div></details>' : '');
    d.querySelector('.txt').textContent = t.text;
    const sl = d.querySelector('.steplist');
    if(sl) t.steps.forEach(s=>{
      const r = document.createElement('div'); r.className = 'step';
      r.innerHTML = '<b></b><span></span>';
      r.querySelector('b').textContent = s.kind + ' ';
      r.querySelector('span').textContent = s.detail;
      sl.appendChild(r);
    });
    log.appendChild(d);
  });
  log.scrollTop = log.scrollHeight;
}
function stepRow(s){
  const r = document.createElement('div'); r.className = 'step';
  r.innerHTML = '<b></b><span></span>';
  r.querySelector('b').textContent = s.kind + ' ';
  r.querySelector('span').textContent = s.detail || '';
  return r;
}
async function dSend(){
  const inp = document.getElementById('d-input');
  const btn = document.getElementById('d-send');
  const text = inp.value.trim(); if(!text) return;
  inp.value = ''; btn.disabled = true;
  const log = document.getElementById('d-log');
  const u = document.createElement('div'); u.className = 'msg user';
  u.innerHTML = '<div class="who">user</div><div class="txt"></div>';
  u.querySelector('.txt').textContent = text; log.appendChild(u);
  const w = document.createElement('div'); w.className = 'msg cli';
  w.innerHTML = '<div class="who">'+dBackend+' (working…)</div><div class="txt"></div>' +
    '<details class="steps" open><summary>steps (<span class="n">0</span>)</summary><div class="steplist"></div></details>';
  log.appendChild(w); log.scrollTop = log.scrollHeight;
  const sl = w.querySelector('.steplist');
  const addStep = (s)=>{
    sl.appendChild(stepRow(s));
    w.querySelector('.n').textContent = sl.children.length;
    log.scrollTop = log.scrollHeight;
  };
  try{
    const r = await fetch('/api/direct/start', {method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({backend: dBackend, message: text})});
    const j = await r.json();
    if(j.error){ throw new Error(j.error); }
    await new Promise((resolve, reject)=>{
      const es = new EventSource('/api/direct/stream?turn='+j.turn_id);
      es.onmessage = (ev)=>{
        const m = JSON.parse(ev.data);
        if(m.step){ addStep(m.step); }
        if(m.done){
          es.close();
          w.querySelector('.who').textContent = dBackend;
          w.querySelector('.txt').textContent = m.text || ('Error: ' + (m.error || 'empty reply'));
          if(m.tools && m.tools.length){ const t=document.createElement('div'); t.className='tools'; t.textContent='tools: '+m.tools.join(', '); w.appendChild(t); }
          resolve();
        }
        if(m.error && !m.done){ es.close(); reject(new Error(m.error)); }
      };
      es.onerror = ()=>{ es.close(); reject(new Error('stream broken')); };
    });
  }catch(e){ w.querySelector('.txt').textContent = 'Error: ' + e; }
  btn.disabled = false; log.scrollTop = log.scrollHeight;
}
document.querySelector('[data-t="telemetry"]').onclick=()=>show('telemetry');
document.querySelector('[data-t="direct"]').onclick=()=>show('direct');
document.getElementById('agent').onchange=(e)=>show(e.target.value);
dInit();
show('research');
</script></body></html>
"""

HUB_HTML = HUB_HTML.replace(
    "__URLS__",
    "{"
    + ", ".join(f'"{k}": "{v}"' for k, v in BACKENDS.items())
    + "}",
)

from starlette.applications import Starlette
from starlette.responses import HTMLResponse, JSONResponse, Response, StreamingResponse
from starlette.routing import Route


async def index(request):
    return HTMLResponse(HUB_HTML)


async def favicon(request):
    return Response(status_code=204)


async def health(request):
    return JSONResponse({"ok": True, "backends": BACKENDS})


async def direct_backends(request):
    from acp_harness import BACKENDS as _B

    return JSONResponse({"backends": sorted(_B)})


async def direct_history(request):
    from acp_harness import direct_history as _h

    return JSONResponse(await _maybe_await(
        _h(request.query_params.get("backend", "opencode"))))


async def direct_send(request):
    from acp_harness import direct_send as _send

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid JSON"}, status_code=400)
    try:
        return JSONResponse(await _send(
            body.get("backend", "opencode"), body.get("message", ""),
            body.get("model")))
    except Exception as e:  # noqa: BLE001 - surfaced in chat
        return JSONResponse({"error": f"{type(e).__name__}: {str(e)[:300]}"})


async def direct_end(request):
    from acp_harness import direct_end as _end

    try:
        body = await request.json()
    except Exception:
        body = {}
    try:
        return JSONResponse({"ok": await _end(body.get("backend", "opencode"))})
    except Exception as e:  # noqa: BLE001 - surfaced in chat
        return JSONResponse({"error": f"{type(e).__name__}: {str(e)[:200]}"})


async def direct_start(request):
    from acp_harness import direct_start as _start

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid JSON"}, status_code=400)
    try:
        turn_id = await _start(body.get("backend", "opencode"),
                               body.get("message", ""), body.get("model"))
        return JSONResponse({"turn_id": turn_id})
    except Exception as e:  # noqa: BLE001 - surfaced in chat
        return JSONResponse({"error": f"{type(e).__name__}: {str(e)[:200]}"})


async def direct_stream(request):
    import asyncio
    import json as _json

    from acp_harness import _TURNS

    turn_id = request.query_params.get("turn", "")

    async def gen():
        sent = 0
        for _ in range(1200):  # ~10 min cap
            t = _TURNS.get(turn_id)
            if t is None:
                yield 'data: {"error": "unknown turn"}\n\n'
                return
            for ev in t["events"][sent:]:
                yield "data: " + _json.dumps({"step": ev}) + "\n\n"
            sent = len(t["events"])
            if t["done"]:
                yield "data: " + _json.dumps({
                    "done": True, "text": t["text"], "tools": t["tools"],
                    "error": t["error"]}) + "\n\n"
                return
            await asyncio.sleep(0.4)

    return StreamingResponse(gen(), media_type="text/event-stream")


async def _maybe_await(value):
    import inspect

    if inspect.isawaitable(value):
        return await value
    return value


app = Starlette(routes=[
    Route("/", index),
    Route("/favicon.ico", favicon),
    Route("/healthz", health),
    Route("/api/direct/backends", direct_backends),
    Route("/api/direct/history", direct_history),
    Route("/api/direct/send", direct_send, methods=["POST"]),
    Route("/api/direct/start", direct_start, methods=["POST"]),
    Route("/api/direct/stream", direct_stream),
    Route("/api/direct/end", direct_end, methods=["POST"]),
])
