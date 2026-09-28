"""Unified lab hub: one URL — an Agent dropdown plus Telemetry.

Run: uv run uvicorn serve_unified:app --host 0.0.0.0 --port 7940
Open: http://localhost:7940  (single dashboard entry: Pydantic AI Lab)

Dropdown lazy-loads each agent UI in an iframe (same origins, no proxy):
  Research      -> http://localhost:7933 (Researcher chat, fresh prompts)
  Research Plan -> http://localhost:7934 (agree the workflow, approve it)
  Research Exec -> http://localhost:7935 (runs the approved workflow)
  Research Flow -> http://localhost:7936 (orchestrator: plan+exec as sub-agents)
  Approval      -> http://localhost:7932 (HITL approval chat)
  ACP Test      -> http://localhost:7941 (drive ACP backends one by one)
Telemetry tab -> Phoenix (trace collector + viewer, http://127.0.0.1:6006).
Phoenix is NOT auto-started (its cold boot pegs a core for minutes): the
Telemetry tab has Start/Stop buttons (/api/telemetry/*) and loads the UI
only once it answers. Spans emitted while it is down are lost — in this lab
only explicit 12_telemetry.py runs emit spans, so nothing is missed.
Backends are started/stopped from the Service Dashboard entries.
"""
import os
from contextlib import asynccontextmanager
from pathlib import Path

BACKENDS = {
    "research": os.getenv("HUB_RESEARCH_URL", "http://localhost:7933"),
    "researchplan": os.getenv("HUB_RESEARCHPLAN_URL", "http://localhost:7934/?v=3"),
    "researchexecute": os.getenv("HUB_RESEARCHEXECUTE_URL", "http://localhost:7935/?v=3"),
    "researchflow": os.getenv("HUB_RESEARCHFLOW_URL", "http://localhost:7936"),
    "approval": os.getenv("HUB_APPROVAL_URL", "http://localhost:7932"),
    "acptest": os.getenv("HUB_ACPTEST_URL", "http://localhost:7941"),
    "telemetry": os.getenv("HUB_TELEMETRY_URL", "http://127.0.0.1:6006"),
}

# --- On-demand Phoenix -----------------------------------------------------
# Phoenix is both halves of telemetry: the OpenTelemetry collector backend
# (OTLP gRPC :4317 + HTTP :6006/v1/traces -> local sqlite) AND the trace
# viewer UI. Nothing in the lab needs it running: agents keep working with
# it down (exporters just drop spans), so it boots only on user request.
_TELEMETRY_PORT = 6006
_TELEMETRY_LOG = "/tmp/phoenix-6006.log"
_TELEMETRY_PIDFILE = "/tmp/phoenix-ondemand.pid"
_LAB_DIR = str(Path(__file__).parent)
_TELEMETRY_UV = "/home/ubu/.local/bin/uv"
_telemetry_proc = None  # subprocess.Popen while hub-spawned instance lives


def _telemetry_pid() -> int | None:
    try:
        pid = int(Path(_TELEMETRY_PIDFILE).read_text().strip())
    except Exception:
        return None
    try:
        import os as _os

        _os.kill(pid, 0)
        return pid
    except Exception:
        return None


def _telemetry_port_open() -> bool:
    import socket as _sock

    try:
        with _sock.create_connection(("127.0.0.1", _TELEMETRY_PORT), timeout=2):
            return True
    except Exception:
        return False


def _telemetry_state() -> dict:
    pid = _telemetry_pid()
    if _telemetry_port_open():
        return {"state": "running", "pid": pid, "note": "answering on :6006"}
    if pid is not None:
        note = "warming up (cold boot takes minutes)"
        try:
            lines = Path(_TELEMETRY_LOG).read_text().splitlines()
            if lines:
                note = lines[-1][:160]
        except Exception:
            pass
        return {"state": "starting", "pid": pid, "note": note}
    return {"state": "stopped", "pid": None, "note": "start it to view traces"}


def _telemetry_start() -> dict:
    global _telemetry_proc
    st = _telemetry_state()
    if st["state"] in ("running", "starting"):
        return st
    import subprocess as _sp

    # Fresh boot log per start so the status tail tracks THIS boot.
    log = open(_TELEMETRY_LOG, "wb")
    _telemetry_proc = _sp.Popen(
        ["nice", "-n", "10", _TELEMETRY_UV, "run", "phoenix", "serve",
         "--port", str(_TELEMETRY_PORT)],
        cwd=_LAB_DIR, stdout=log, stderr=_sp.STDOUT, stdin=_sp.DEVNULL,
        start_new_session=False)
    Path(_TELEMETRY_PIDFILE).write_text(str(_telemetry_proc.pid))
    return _telemetry_state()


def _telemetry_stop() -> dict:
    global _telemetry_proc
    import signal as _sig
    import time as _time

    pid = _telemetry_pid()
    if pid is None and _telemetry_port_open():
        import subprocess as _sp2  # noqa: PLC0415

        # Not ours (e.g. autostarted before the on-demand switch): stop by
        # pattern. Bracket form never matches our own command line.
        _sp2.run(["pkill", "-f", "[p]hoenix serve --port 6006"],
                 capture_output=True)
        return _telemetry_state()
    if pid is not None:
        try:
            os.kill(pid, _sig.SIGTERM)
            for _ in range(20):
                _time.sleep(0.5)
                if _telemetry_pid() is None or not _telemetry_port_open():
                    break
            else:
                os.kill(pid, _sig.SIGKILL)
        except Exception:
            pass
    try:
        Path(_TELEMETRY_PIDFILE).unlink(missing_ok=True)
    except Exception:
        pass
    _telemetry_proc = None
    return _telemetry_state()


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
#t-bar{display:none;position:absolute;top:0;left:0;right:0;z-index:5;gap:8px;align-items:center;padding:8px 14px;background:#11151d;border-bottom:1px solid #232a38;font-size:13px}
#t-bar.show{display:flex}
#t-state{color:#e6e9f0}
#t-note{color:#8b93a7;font-size:12px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:60%}
#t-bar button{border:1px solid #2a3345;background:#1a2130;color:#cfd6e4;border-radius:8px;padding:6px 14px;cursor:pointer;font-size:13px}
#t-bar button:disabled{opacity:.4;cursor:default}
#t-start{border-color:#2563eb !important}
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
<option value="researchplan">Research Plan</option>
<option value="researchexecute">Research Exec</option>
<option value="researchflow">Research Flow</option>
<option value="approval">Approval</option>
<option value="acptest">ACP Test</option>
</select>
<button class="tab" data-t="direct">Direct</button>
<button class="tab" data-t="telemetry">Telemetry</button>
<span class="hint">backends managed in Service Dashboard</span></header>
<main>
<iframe id="f-research" allow="clipboard-read; clipboard-write" class="active"></iframe>
<iframe id="f-researchplan" allow="clipboard-read; clipboard-write"></iframe>
<iframe id="f-researchexecute" allow="clipboard-read; clipboard-write"></iframe>
<iframe id="f-researchflow" allow="clipboard-read; clipboard-write"></iframe>
<iframe id="f-approval" allow="clipboard-read; clipboard-write"></iframe>
<iframe id="f-acptest" allow="clipboard-read; clipboard-write"></iframe>
<div id="t-bar"><span id="t-state">Telemetry: …</span><button id="t-start">Start</button><button id="t-stop">Stop</button><span id="t-note"></span></div>
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
const loaded = {research: false, researchplan: false, researchexecute: false, researchflow: false, approval: false, acptest: false, telemetry: false};
let dBackend = null;
let tTimer = null;
async function tRefresh(){
  let s;
  try{ s = await (await fetch('/api/telemetry/status')).json(); }
  catch(e){ s = {state:'unknown', note:String(e).slice(0,120)}; }
  document.getElementById('t-state').textContent =
    'Telemetry: ' + s.state + (s.pid ? ' (pid ' + s.pid + ')' : '');
  document.getElementById('t-note').textContent = s.note || '';
  document.getElementById('t-start').disabled = (s.state === 'running' || s.state === 'starting');
  document.getElementById('t-stop').disabled = !(s.state === 'running' || s.state === 'starting');
  const f = document.getElementById('f-telemetry');
  if(s.state === 'running'){
    if(!loaded.telemetry){ f.src = URLS.telemetry; loaded.telemetry = true; }
  } else if(loaded.telemetry){ f.src = 'about:blank'; loaded.telemetry = false; }
}
async function tStart(){ await fetch('/api/telemetry/start', {method:'POST'}); tRefresh(); }
async function tStop(){ await fetch('/api/telemetry/stop', {method:'POST'}); tRefresh(); }
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
  try{
    if(URLS[name]) localStorage.setItem('labHubAgent', name);
  }catch(e){}
  const bar = document.getElementById('t-bar');
  if(name === 'telemetry'){
    bar.classList.add('show');
    document.querySelectorAll('iframe').forEach(f=>f.classList.remove('active'));
    document.getElementById('v-direct').classList.remove('active');
    document.getElementById('f-telemetry').classList.add('active');
    tRefresh();
    if(tTimer) clearInterval(tTimer);
    tTimer = setInterval(tRefresh, 3000);
    return;
  }
  bar.classList.remove('show');
  if(tTimer){ clearInterval(tTimer); tTimer = null; }
  showFrame(name);
  // Park the Phoenix SPA when hidden: it polls GraphQL continuously (~30%
  // server CPU idle). Traces persist server-side; chats keep their state.
  const t = document.getElementById('f-telemetry');
  if(loaded.telemetry){ t.src = 'about:blank'; loaded.telemetry = false; }
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
document.getElementById('t-start').onclick=()=>tStart();
document.getElementById('t-stop').onclick=()=>tStop();
dInit();
try{
  const saved = localStorage.getItem('labHubAgent');
  show(saved && URLS[saved] && saved !== 'telemetry' ? saved : 'research');
}catch(e){ show('research'); }
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


async def telemetry_status(request):
    return JSONResponse(_telemetry_state())


async def telemetry_start(request):
    try:
        return JSONResponse(_telemetry_start())
    except Exception as e:  # noqa: BLE001 - surfaced in the tab
        return JSONResponse({"state": "error", "note": f"{type(e).__name__}: {str(e)[:200]}"})


async def telemetry_stop(request):
    try:
        return JSONResponse(_telemetry_stop())
    except Exception as e:  # noqa: BLE001 - surfaced in the tab
        return JSONResponse({"state": "error", "note": f"{type(e).__name__}: {str(e)[:200]}"})


async def _maybe_await(value):
    import inspect

    if inspect.isawaitable(value):
        return await value
    return value


@asynccontextmanager
async def _lifespan(app):
    yield
    try:
        if _telemetry_pid() is not None:
            _telemetry_stop()
    except Exception:
        pass


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
    Route("/api/telemetry/status", telemetry_status),
    Route("/api/telemetry/start", telemetry_start, methods=["POST"]),
    Route("/api/telemetry/stop", telemetry_stop, methods=["POST"]),
], lifespan=_lifespan)
