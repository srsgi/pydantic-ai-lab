"""Build lab_web_ui.html: pinned ai-chat-ui bundle + lab patches.

Patches (single source of truth — edit here, rebuild, restart backend):
  CSS: wrap long <pre>/code, widen chat column, LEFT-ALIGN user messages.
  JS:  Copy buttons on user messages; persist model/effort dropdowns.

Usage:
    uv run python build_lab_ui.py                       # download pinned bundle
    uv run python build_lab_ui.py --src /path/bundle.html
    uv run python build_lab_ui.py --src /path/bundle.html --out lab_web_ui.html

Pin must match installed pydantic-ai (ui/_web/app.py CHAT_UI_VERSION).
"""
import argparse
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).parent
PINNED_URL = "https://cdn.jsdelivr.net/npm/@pydantic/ai-chat-ui@2.1.0/offline/index.html"

LAB_CSS = """<style>
/* Pydantic AI Lab overrides (researchflow). */
/* 1. Wrap long lines so code/ASCII never gets cut off. */
pre{white-space:pre-wrap!important;overflow-wrap:anywhere!important;overflow-x:auto!important;max-width:100%}
code{overflow-wrap:anywhere!important}
.markdown-body table,article table{display:block;overflow-x:auto;max-width:100%}
/* 2. Widen the chat column (bundle default max-w-4xl = 56rem). */
.max-w-4xl{max-width:100rem!important}
/* 3. Left-align user messages (bundle default: right via justify-end). */
div.is-user.justify-end{justify-content:flex-start!important}
div[class*="user-message"] div.mt-1.justify-end{justify-content:flex-start!important}
</style>"""

LAB_JS = """<script>
/* Pydantic AI Lab additions: user-message Copy buttons + dropdown persistence. */
(function(){
'use strict';
function umText(um){var p=um.querySelector('p');return ((p?p.innerText:um.innerText)||'').trim();}
var COPY_SVG='<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-copy size-4" aria-hidden="true"><rect width="14" height="14" x="8" y="8" rx="2" ry="2"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/></svg>';
var CHECK_SVG='<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-check size-4" aria-hidden="true"><path d="M20 6 9 17l-5-5"/></svg>';
function ensureCopy(){
  document.querySelectorAll('[class*="user-message"]').forEach(function(um){
    if(um.querySelector('button.lab-copy'))return;
    var edit=null;
    um.querySelectorAll('button').forEach(function(b){
      if((b.innerText||'').indexOf('Edit message')>-1)edit=b;});
    if(!edit||!edit.parentElement)return;
    var btn=document.createElement('button');
    btn.className=edit.className+' lab-copy';btn.innerHTML=COPY_SVG;
    btn.title='Copy';btn.setAttribute('aria-label','Copy message');
    btn.addEventListener('click',function(ev){ev.stopPropagation();
      var txt=umText(um);
      var done=function(ok){
        if(ok){btn.innerHTML=CHECK_SVG;setTimeout(function(){btn.innerHTML=COPY_SVG;},1200);}
        else{btn.title='Copy failed - clipboard blocked';
          setTimeout(function(){btn.title='Copy';},1500);}};
      if(navigator.clipboard&&navigator.clipboard.writeText){
        navigator.clipboard.writeText(txt).then(function(){done(true);},function(){fallback();});}
      else{fallback();}
      function fallback(){var ta=document.createElement('textarea');ta.value=txt;
        ta.style.cssText='position:fixed;opacity:0;';
        document.body.appendChild(ta);ta.select();
        try{done(document.execCommand('copy'));}catch(e){done(false);}ta.remove();}});
    edit.parentElement.appendChild(btn);
  });
}
var KEY='lab-combobox-v1',ready=false,restoring=false,cancelled=false;
document.addEventListener('click',function(e){
  if(e.isTrusted&&e.target&&e.target.closest&&
     e.target.closest('button[role="combobox"],[role="option"],[role="listbox"]')){cancelled=true;}
},true);
function wait(ms){return new Promise(function(r){setTimeout(r,ms);});}
function combos(){return Array.prototype.slice.call(document.querySelectorAll('button[role="combobox"]'));}
function loadSaved(){try{return JSON.parse(localStorage.getItem(KEY)||'[]');}catch(e){return[];}}
function saveNow(){if(!ready||restoring)return;
  try{localStorage.setItem(KEY,JSON.stringify(combos().map(function(b){return (b.innerText||'').trim();})));}catch(e){}}
async function restore(){
  if(restoring)return;restoring=true;
  try{
    var saved=loadSaved();
    var deadline=Date.now()+30000;
    while(Date.now()<deadline&&!cancelled){
      var cs=combos();
      if(!cs.length){await wait(500);continue;}
      var need=false;
      for(var i=0;i<cs.length&&i<saved.length;i++){
        var cur=(cs[i].innerText||'').trim();
        if(saved[i]&&saved[i]!==cur){need=true;
          cs[i].click();var want=saved[i],opt=null;
          for(var k=0;k<20&&!opt&&!cancelled;k++){await wait(200);
            var opts=Array.prototype.slice.call(document.querySelectorAll('[role="option"]'));
            opt=opts.find(function(o){return (o.innerText||'').trim()===want;})||null;}
          if(opt){opt.click();await wait(600);}
          else{document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape'}));await wait(300);}
        }
      }
      var ok=true,cs2=combos();
      for(var j=0;j<cs2.length&&j<saved.length;j++){
        if(saved[j]&&(cs2[j].innerText||'').trim()!==saved[j]){ok=false;break;}}
      if(ok||!need)break;
      await wait(2000);
    }
  }finally{restoring=false;ready=true;}
}
function autoCollapse(){
  var all=document.querySelectorAll('[class*="tool-part"]');
  var real=[];
  for(var i=0;i<all.length;i++){
    if(all[i].querySelector('button[aria-label="Hide this tool"]'))real.push(all[i]);
  }
  for(var j=0;j+1<real.length;j++){
    var g=real[j];
    if(g.dataset.labCollapsed)continue;
    var txt=g.innerText||'';
    if(!/Completed|Error/.test(txt))continue;
    if(g.querySelectorAll('div').length===0){g.dataset.labCollapsed='1';continue;}
    var btn=g.querySelector('button[aria-label="Hide this tool"]');
    if(btn)btn.click();
    g.dataset.labCollapsed='1';
  }
}
var mo=new MutationObserver(function(){ensureCopy();saveNow();autoCollapse();});
mo.observe(document.documentElement,{childList:true,subtree:true,characterData:true});
var tries=0;var iv=setInterval(function(){ensureCopy();autoCollapse();
  if(combos().length||++tries>40){clearInterval(iv);restore();}
},500);
})();
</script>"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=None, help="Bundle path or URL (default: pinned CDN URL)")
    ap.add_argument("--out", default=str(HERE / "lab_web_ui.html"))
    args = ap.parse_args()

    src = args.src or PINNED_URL
    if src.startswith(("http://", "https://")):
        print(f"downloading {src} ...")
        with urllib.request.urlopen(src, timeout=120) as r:
            html = r.read().decode("utf-8")
    else:
        html = Path(src).read_text(encoding="utf-8")

    # Anchor on the LAST </head> (the real one): earlier occurrences live
    # inside JS string literals — patching there breaks the bundle.
    idx = html.rfind("</head>")
    if idx < 0 or "<body>" not in html[idx:idx + 200]:
        print("ERROR: no real </head><body> anchor found", file=sys.stderr)
        return 1
    html = html[:idx] + LAB_CSS + "\n" + html[idx:]

    # Script goes right before </body> (last occurrence = real markup).
    bidx = html.rfind("</body>")
    html = html[:bidx] + LAB_JS + "\n" + html[bidx:]

    Path(args.out).write_text(html, encoding="utf-8")
    print(f"wrote {args.out} ({len(html)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
