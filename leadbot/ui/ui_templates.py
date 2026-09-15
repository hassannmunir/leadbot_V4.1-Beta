"""HTML templates for the local LeadBot web console."""

from __future__ import annotations

import html
import json
from typing import Any

from ..discovery.sources import load_niche_map, load_regions_map

_DEFAULT_COUNTRY = "United States"
_DEFAULT_REGION = "Texas"

# Raw strings on purpose: the JS below relies on backslash escapes (\n, \u2026)
# that must reach the browser untouched.
_CSS = r"""
:root{--sans:Arial,sans-serif;--mono:Consolas,Menlo,"Courier New",monospace;
--bg:#101b1d;--panel:#172729;--inset:#0e181a;--line:#3d625b;--line-soft:#28423e;
--gold:#d6ae59;--gold-soft:#e3bd6d;--text:#eef4e8;--muted:#a9c2b7;--faint:#8ba398;
--ok:#8fd49a;--err:#e39a9a}
*{box-sizing:border-box}
body{margin:0;min-height:100vh;background:var(--bg);background-image:radial-gradient(1100px 520px at 50% -140px,#1c3134 0%,var(--bg) 62%);color:var(--text);font:16px Georgia,serif;-webkit-font-smoothing:antialiased}
.shell{max-width:1080px;margin:0 auto;padding:46px 28px 60px}
.eyebrow{color:var(--gold);letter-spacing:3px;text-transform:uppercase;font:12px var(--sans);margin-bottom:14px}
h1{font-size:34px;line-height:1.2;margin:0 0 12px;font-weight:normal}
.lede{color:var(--muted);font:15px/1.7 var(--sans);max-width:660px;margin:0}
.masthead{padding-bottom:26px}
.alert{margin:0 0 22px;padding:14px 18px;background:rgba(224,139,139,.08);border:1px solid #7a4545;border-left:4px solid var(--err);border-radius:12px;color:var(--err);font:14px/1.6 var(--sans)}
.panels{display:grid;grid-template-columns:5fr 6fr;gap:22px;align-items:start}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:18px;padding:24px 28px 26px;box-shadow:0 20px 60px rgba(8,16,17,.55)}
.panel-head{display:flex;align-items:center;justify-content:space-between;gap:12px;border-bottom:1px solid var(--line-soft);padding-bottom:14px}
.panel-title{font:13px var(--sans);letter-spacing:2.4px;text-transform:uppercase;color:var(--faint);margin:0}
.panel-sub{font:12px var(--sans);color:var(--faint)}
label{display:block;color:var(--muted);font:12px var(--sans);letter-spacing:1px;text-transform:uppercase;margin:20px 0 8px}
label .soft{text-transform:none;letter-spacing:0;color:var(--faint)}
input,select{width:100%;padding:13px 14px;background:var(--inset);color:#fff;border:1px solid var(--line);border-radius:9px;font:15px var(--sans);transition:border-color .15s ease,box-shadow .15s ease}
select{text-transform:capitalize}
input::placeholder{color:#5b756c}
input:focus-visible,select:focus-visible{outline:none;border-color:var(--gold);box-shadow:0 0 0 3px rgba(214,174,89,.16)}
.field-hint{color:var(--faint);font:12.5px/1.55 var(--sans);margin:8px 0 0}
.run-button{margin-top:26px;width:100%;display:inline-flex;align-items:center;justify-content:center;gap:9px;padding:15px 22px;background:linear-gradient(180deg,var(--gold-soft),var(--gold));border:0;border-radius:10px;color:#17272a;font:bold 15px var(--sans);letter-spacing:.4px;cursor:pointer;transition:transform .12s ease,box-shadow .12s ease,filter .12s ease}
.run-button:hover:not(:disabled){filter:brightness(1.06);transform:translateY(-1px);box-shadow:0 10px 24px rgba(214,174,89,.22)}
.run-button:active:not(:disabled){transform:translateY(0)}
.run-button:focus-visible{outline:2px solid var(--gold);outline-offset:3px}
.run-button:disabled{cursor:not-allowed;filter:saturate(.45) brightness(.8)}
.spinner{display:none;width:14px;height:14px;border:2px solid rgba(23,39,42,.35);border-top-color:#17272a;border-radius:50%;animation:spin .8s linear infinite}
.run-button.is-running .spinner{display:inline-block}
.form-foot{margin-top:20px;padding-top:16px;border-top:1px solid var(--line-soft)}
.hint{color:var(--faint);font:13px/1.6 var(--sans);margin:0}
.hidden{display:none!important}
#region-custom{margin-top:8px}
"""

_CSS += r"""
.badge{display:inline-flex;align-items:center;gap:7px;padding:5px 12px;border-radius:999px;border:1px solid var(--line);background:var(--inset);font:11px var(--sans);letter-spacing:1.4px;text-transform:uppercase;color:var(--muted)}
.badge::before{content:"";width:8px;height:8px;border-radius:50%;background:#6d8a80}
.badge[data-state="running"]{color:var(--gold);border-color:#8a6f35}
.badge[data-state="running"]::before{background:var(--gold);animation:pulse 1.4s ease-in-out infinite}
.badge[data-state="complete"]{color:var(--ok);border-color:#3f6b46}
.badge[data-state="complete"]::before{background:var(--ok)}
.badge[data-state="error"]{color:var(--err);border-color:#7a4545}
.badge[data-state="error"]::before{background:var(--err)}
.status-row{display:flex;align-items:baseline;justify-content:space-between;gap:14px;margin-top:16px;min-height:22px}
.status-message{font:14px var(--sans);color:var(--text);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.elapsed{font:12px var(--mono);color:var(--faint);white-space:nowrap}
.progress-track{position:relative;height:10px;margin:12px 0 8px;background:var(--inset);border:1px solid var(--line-soft);border-radius:999px;overflow:hidden}
.progress-bar{position:relative;height:100%;width:0%;background:linear-gradient(90deg,#b8934a,var(--gold));border-radius:999px;transition:width .4s ease}
.progress-track.is-active .progress-bar::after{content:"";position:absolute;inset:0;background-image:linear-gradient(45deg,rgba(255,255,255,.22) 25%,transparent 25%,transparent 50%,rgba(255,255,255,.22) 50%,rgba(255,255,255,.22) 75%,transparent 75%);background-size:18px 18px;animation:stripes .7s linear infinite}
.progress-meta{display:flex;justify-content:space-between;align-items:baseline}
.progress-label{font:bold 13px var(--mono);color:var(--gold)}
.progress-note{font:12px var(--sans);color:var(--faint)}
.log-head{display:flex;align-items:center;justify-content:space-between;margin-top:20px}
.log-title{font:12px var(--sans);letter-spacing:1.6px;text-transform:uppercase;color:var(--faint)}
.copy-button{background:transparent;border:1px solid var(--line);border-radius:8px;padding:5px 12px;color:var(--muted);font:12px var(--sans);cursor:pointer;transition:color .12s,border-color .12s}
.copy-button:hover{color:var(--gold);border-color:var(--gold)}
.copy-button:focus-visible{outline:2px solid var(--gold);outline-offset:2px}
.log{margin-top:10px;padding:14px 16px;background:var(--inset);border:1px solid var(--line-soft);border-left:3px solid var(--gold);border-radius:10px;font:12.5px/1.7 var(--mono);color:#c7d6cd;white-space:pre-wrap;word-break:break-word;max-height:300px;overflow-y:auto}
.log .line-error{color:var(--err)}
.log .line-warn{color:var(--gold)}
.log .line-dim{color:#5b756c}
.log .line-empty{color:var(--faint);font-family:var(--sans);font-style:italic}
.log::-webkit-scrollbar{width:10px}
.log::-webkit-scrollbar-thumb{background:#2a423c;border-radius:999px}
.log::-webkit-scrollbar-track{background:transparent}
@media (max-width:880px){.shell{padding:28px 16px 44px}.panels{grid-template-columns:1fr}h1{font-size:28px}input,select{font-size:16px}}
@keyframes spin{to{transform:rotate(360deg)}}
@keyframes pulse{0%,100%{box-shadow:0 0 0 0 rgba(214,174,89,.45)}50%{box-shadow:0 0 0 6px rgba(214,174,89,0)}}
@keyframes stripes{to{background-position:18px 0}}
@media (prefers-reduced-motion:reduce){.badge[data-state="running"]::before,.progress-track.is-active .progress-bar::after,.spinner{animation:none}.progress-bar,.run-button{transition:none}}
"""

_JS = r"""
(function(){
var badge=document.getElementById('status-badge');
var statusMessage=document.getElementById('status-message');
var elapsed=document.getElementById('elapsed');
var track=document.getElementById('progress-track');
var bar=document.getElementById('progress-bar');
var progressLabel=document.getElementById('progress-label');
var log=document.getElementById('log');
var button=document.getElementById('run-button');
var runLabel=document.getElementById('run-label');
var copyButton=document.getElementById('copy-log');
var countrySelect=document.getElementById('country');
var regionSelect=document.getElementById('region-select');
var regionCustom=document.getElementById('region-custom');
var regionValue=document.getElementById('region-value');
var runForm=document.getElementById('run-form');
var CUSTOM='__custom__';
var lastStatus=null;
var startedAt=null;
var BADGES={idle:'Idle',running:'Running',complete:'Complete',error:'Failed'};

function fmtDuration(totalSeconds){
var s=Math.max(0,Math.floor(totalSeconds));
var m=Math.floor(s/60);
s=s%60;
if(m>=60){var h=Math.floor(m/60);m=m%60;return h+'h '+m+'m '+s+'s';}
if(m){return m+'m '+s+'s';}
return s+'s';
}

function lineClass(text){
if(/^(error|traceback|exception|failed|could not|fatal)/i.test(text)){return 'line-error';}
if(/^warn/i.test(text)){return 'line-warn';}
if(/^PROGRESS /.test(text)){return 'line-dim';}
return '';
}

function renderLog(lines){
var nearBottom=log.scrollHeight-log.clientHeight-log.scrollTop<48;
var frag=document.createDocumentFragment();
if(!lines||!lines.length){
var empty=document.createElement('div');
empty.className='line-empty';
empty.textContent='No activity yet \u2014 run a collection to see live output here.';
frag.appendChild(empty);
}else{
lines.forEach(function(text){
var div=document.createElement('div');
var cls=lineClass(text);
if(cls){div.className=cls;}
div.textContent=text;
frag.appendChild(div);
});
}
log.replaceChildren(frag);
if(nearBottom){log.scrollTop=log.scrollHeight;}
}

function render(x){
var state=x.status||'idle';
badge.dataset.state=state;
badge.textContent=BADGES[state]||state;
statusMessage.textContent=x.message||'';
var progress=x.progress||0;
progressLabel.textContent=progress+'%';
bar.style.width=progress+'%';
var running=state==='running';
track.classList.toggle('is-active',running);
button.disabled=running;
button.classList.toggle('is-running',running);
runLabel.textContent=running?'Collection running\u2026':'Run lead collection';
if(running){
if(lastStatus!=='running'){startedAt=Date.now();}
elapsed.textContent='Elapsed '+fmtDuration((Date.now()-startedAt)/1000);
}else{
elapsed.textContent='';
startedAt=null;
}
renderLog(x.log);
lastStatus=state;
}

function poll(){
fetch('/status').then(function(r){return r.json();}).then(render).catch(function(){});
}

copyButton.addEventListener('click',function(){
var text=Array.prototype.map.call(log.children,function(node){return node.textContent;}).join('\n');
if(navigator.clipboard&&navigator.clipboard.writeText){
navigator.clipboard.writeText(text).then(function(){
copyButton.textContent='Copied \u2713';
setTimeout(function(){copyButton.textContent='Copy';},1500);
}).catch(function(){});
}
});

function fillRegions(country,keep){
var regions=REGIONS[country]||[];
var frag=document.createDocumentFragment();
regions.forEach(function(name){
var opt=document.createElement('option');
opt.value=name;opt.textContent=name;
frag.appendChild(opt);
});
var optCustom=document.createElement('option');
optCustom.value=CUSTOM;optCustom.textContent='Other (type manually)\u2026';
frag.appendChild(optCustom);
regionSelect.replaceChildren(frag);
if(keep&&regions.indexOf(keep)!==-1){regionSelect.value=keep;}
else if(keep){regionSelect.value=CUSTOM;regionCustom.value=keep;}
else{regionSelect.selectedIndex=0;regionCustom.value='';}
syncRegion();
}

function syncRegion(){
var custom=regionSelect.value===CUSTOM;
regionCustom.classList.toggle('hidden',!custom);
regionValue.value=custom?regionCustom.value:regionSelect.value;
}

countrySelect.addEventListener('change',function(){fillRegions(countrySelect.value,null);});
regionSelect.addEventListener('change',syncRegion);
regionCustom.addEventListener('input',syncRegion);
runForm.addEventListener('submit',function(e){
syncRegion();
if(!regionValue.value){e.preventDefault();(regionSelect.value===CUSTOM?regionCustom:regionSelect).focus();}
});

syncRegion();
poll();
setInterval(poll,1000);
})();
"""

def niche_options_html(selected: str | None = None) -> str:
    """Render <option> entries for every configured niche, marking ``selected``."""
    options = []
    for niche in sorted(load_niche_map().keys()):
        value = html.escape(niche, quote=True)
        label = html.escape(niche.replace("_", " "))
        chosen = " selected" if niche == selected else ""
        options.append(f'<option value="{value}"{chosen}>{label}</option>')
    return "".join(options)


def country_options_html(selected: str | None = None) -> str:
    """Render country <option> entries from the regions map, keeping unknown picks."""
    countries = sorted(load_regions_map().keys())
    if selected and selected not in countries:
        countries.append(selected)
        countries.sort()
    options = []
    for country in countries:
        value = html.escape(country, quote=True)
        chosen = " selected" if country == selected else ""
        options.append(f'<option value="{value}"{chosen}>{html.escape(country)}</option>')
    return "".join(options)


def region_options_html(country: str | None, selected: str | None = None) -> str:
    """Render region <option> entries for one country, plus a manual-entry fallback."""
    regions = sorted(load_regions_map().get(country or "", []))
    options = []
    for region in regions:
        value = html.escape(region, quote=True)
        chosen = " selected" if region == selected else ""
        options.append(f'<option value="{value}"{chosen}>{html.escape(region)}</option>')
    use_custom = selected is not None and (not regions or selected not in regions)
    chosen = " selected" if use_custom else ""
    options.append(f'<option value="__custom__"{chosen}>Other (type manually)&hellip;</option>')
    return "".join(options)


def page_html(last_query: dict[str, Any] | None = None, error_message: str | None = None) -> str:
    """Render the console page, optionally pre-filled with the last saved query."""
    last_query = last_query or {}
    country = str(last_query.get("country") or _DEFAULT_COUNTRY)
    region = str(last_query.get("region") or _DEFAULT_REGION)
    niche = last_query.get("niche") or None
    regions_json = json.dumps(load_regions_map(), ensure_ascii=False)
    custom_region = region if region not in load_regions_map().get(country, []) else ""
    error_banner = (
        f'<div class="alert" role="alert"><b>Could not start:</b> {html.escape(str(error_message))}</div>'
        if error_message
        else ""
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>LeadBot Console</title>
<style>{_CSS}</style></head>
<body><main class="shell">
<header class="masthead">
<div class="eyebrow">Lead operations &middot; local console</div>
<h1>Find businesses in your territory.</h1>
<p class="lede">Pick a country, region (city or state), and niche. LeadBot geocodes the region, tiles it if it's large, queries OpenStreetMap, checks each business's own website, and adds only new leads to your Google Sheet.</p>
</header>
{error_banner}<div class="panels">
<section class="panel">
<div class="panel-head"><h2 class="panel-title">Search criteria</h2><span class="panel-sub">one query per run</span></div>
<form method="post" id="run-form">
<label for="country">Country</label>
<select id="country" name="country" required>{country_options_html(country)}</select>
<label for="region-select">Region <span class="soft">(city or state)</span></label>
<select id="region-select">{region_options_html(country, region)}</select>
<input type="text" id="region-custom" class="hidden" value="{html.escape(custom_region, quote=True)}" placeholder="Type any city or state&hellip;" autocomplete="off">
<input type="hidden" name="region" id="region-value" value="{html.escape(region, quote=True)}">
<p class="field-hint">City-level regions run much faster than whole states.</p>
<label for="niche">Niche</label>
<select id="niche" name="niche">{niche_options_html(niche)}</select>
<button class="run-button" id="run-button" type="submit"><span class="spinner"></span><span id="run-label">Run lead collection</span></button>
<div class="form-foot"><p class="hint">Missing options? Add niches to <b>leadbot/discovery/niche_map.json</b> and regions to <b>leadbot/discovery/regions_map.json</b>, then restart this page.</p></div>
</form>
</section>
<section class="panel">
<div class="panel-head"><h2 class="panel-title">Run monitor</h2><span class="badge" id="status-badge" data-state="idle" role="status">Idle</span></div>
<div class="status-row"><div class="status-message" id="status-message" aria-live="polite">Ready</div><div class="elapsed" id="elapsed"></div></div>
<div class="progress-track" id="progress-track"><div class="progress-bar" id="progress-bar"></div></div>
<div class="progress-meta"><span class="progress-label" id="progress-label">0%</span><span class="progress-note">geocode &rarr; discover &rarr; verify &rarr; sheet</span></div>
<div class="log-head"><span class="log-title">Activity log</span><button class="copy-button" id="copy-log" type="button">Copy</button></div>
<div class="log" id="log"></div>
</section>
</div>
</main>
<script>var REGIONS={regions_json};</script>
<script>{_JS}</script>
</body></html>"""

