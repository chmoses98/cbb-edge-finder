"""Self-contained market-family research dashboard (one HTML file, data embedded gzip+base64).

Rows are one per (settled contract, entry point). All filtering is client-side; headline numbers
are cluster-weighted (one game = one vote) so correlated ladders cannot inflate sample size.
"""

from __future__ import annotations

import base64
import gzip
import json
from typing import Any


def slim(
    summaries: list[dict[str, Any]], rows: list[dict[str, Any]], max_contract_rows: int = 30000
) -> dict[str, Any]:
    close_mid: dict[str, float | None] = {}
    first_date: dict[str, str | None] = {}
    for r in rows:
        if r["entry"] == "CLOSE":
            close_mid[r["ticker"]] = r["mid"]
    contracts = []
    for c in summaries[: max_contract_rows * 2]:
        d = (c["game_start"] or c["close_time"] or "")[:10]
        contracts.append(
            {
                "k": c["ticker"], "f": c["family"], "s": c["series"], "c": c["cluster"], "d": d,
                "r": c["result"], "fl": c["status_flags"], "t": c["title"] or c["yes_sub_title"],
                "m": close_mid.get(c["ticker"]), "mo": c["status"]["model"],
                "mg": c["status"]["model_missing_capability"], "oc": c["status"]["official_check"],
                "n": c["n_snapshots"], "mp": c["status"]["mapping"],
            }
        )  # fmt: skip
        first_date[c["ticker"]] = d
    out_rows = []
    for r in rows:
        if r["y"] is None:
            continue
        yf, nf = r["yes"], r["no"]
        out_rows.append(
            {
                "k": r["ticker"], "f": r["family"], "s": r["series"], "c": r["cluster"],
                "e": r["entry"], "h": None if r["hours_before_ref"] is None else round(r["hours_before_ref"], 2),
                "m": None if r["mid"] is None else round(r["mid"], 4), "y": r["y"],
                "sp": None if r["spread"] is None else round(r["spread"], 3), "q": r["tier"],
                "d": first_date.get(r["ticker"], ""), "tv": r["tip_verified"],
                "Y": [round(yf["net_pnl"], 4), round(yf["total_cost"], 4)] if "net_pnl" in yf else None,
                "N": [round(nf["net_pnl"], 4), round(nf["total_cost"], 4)] if "net_pnl" in nf else None,
                "cy": None if "clv_net" not in yf else round(yf["clv_net"], 4),
                "cn": None if "clv_net" not in nf else round(nf["clv_net"], 4),
                "mo": {v: [round(m["p"], 4), round(m.get("ev_yes", float("nan")), 4) if "ev_yes" in m else None,
                           round(m["ev_no"], 4) if "ev_no" in m else None] for v, m in r["model"].items()},
            }
        )  # fmt: skip
    return {"contracts": contracts, "rows": out_rows}


def render(matrix: dict[str, Any], data: dict[str, Any], meta: dict[str, Any]) -> str:
    blob = base64.b64encode(
        gzip.compress(json.dumps({"matrix": matrix, "meta": meta, **data}, default=str).encode(), 9)
    ).decode()
    return _TEMPLATE.replace("__DATA__", blob)


_TEMPLATE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>CBB Market Research</title>
<style>
:root{--bg:#fafaf8;--fg:#1c1c1a;--mut:#6b6b66;--line:#dddcd5;--card:#fff;--acc:#2a5db0;--bad:#b3261e;--good:#1b7a43}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#151514;--fg:#ecebe6;--mut:#9a9992;--line:#34332f;--card:#1e1e1c;--acc:#7aa7ee;--bad:#f2766d;--good:#5cc98a}}
:root[data-theme="dark"]{--bg:#151514;--fg:#ecebe6;--mut:#9a9992;--line:#34332f;--card:#1e1e1c;--acc:#7aa7ee;--bad:#f2766d;--good:#5cc98a}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.45 system-ui,sans-serif}
main{max-width:1200px;margin:0 auto;padding:16px}
h1{font-size:20px;margin:0 0 4px}h2{font-size:15px;margin:22px 0 8px}
.sub{color:var(--mut);font-size:12px}
.bar{display:flex;flex-wrap:wrap;gap:10px;background:var(--card);border:1px solid var(--line);border-radius:8px;padding:10px;margin:12px 0}
.bar label{display:flex;flex-direction:column;font-size:11px;color:var(--mut);gap:2px}
select,input{background:var(--bg);color:var(--fg);border:1px solid var(--line);border-radius:5px;padding:4px 6px;font:inherit;min-width:90px}
.wrap{overflow-x:auto;border:1px solid var(--line);border-radius:8px;background:var(--card)}
table{border-collapse:collapse;width:100%;font-size:12.5px}
th,td{padding:6px 8px;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap}
th:first-child,td:first-child{text-align:left}th{color:var(--mut);font-weight:600;position:sticky;top:0;background:var(--card)}
tr.fam{cursor:pointer}tr.fam:hover{background:color-mix(in srgb,var(--acc) 8%,transparent)}
.neg{color:var(--good)}.pos{color:var(--bad)}.low{color:var(--mut);font-style:italic}
.note{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:10px;font-size:12px;color:var(--mut)}
td.l{text-align:left;max-width:360px;overflow:hidden;text-overflow:ellipsis}
</style></head><body><main>
<h1>CBB market research</h1>
<div class="sub" id="meta"></div>
<div class="bar" id="bar"></div>
<div class="note" id="note"></div>
<h2>Market-family matrix <span class="sub">(click a family to drill down)</span></h2>
<div class="wrap"><table id="fam"></table></div>
<h2 id="dtitle">Contracts</h2>
<div class="wrap" style="max-height:480px"><table id="det"></table></div>
</main>
<script>
const B64="__DATA__";
const FL={ENTRY:['OPEN','H24','H6','H1','CLOSE']};
let D,state={fam:null};
const $=id=>document.getElementById(id);
async function load(){
  const bin=Uint8Array.from(atob(B64),c=>c.charCodeAt(0));
  const s=new Response(new Blob([bin]).stream().pipeThrough(new DecompressionStream('gzip')));
  D=await s.json(); init();
}
function opts(a){return a.map(x=>`<option>${x}</option>`).join('')}
function init(){
  const m=D.meta;
  $('meta').textContent=`generated ${m.generated_at} · ${m.snapshots} snapshots · ${D.contracts.length.toLocaleString()} contracts · ${D.rows.length.toLocaleString()} scored entry rows · authority RESEARCH_ONLY`;
  $('note').textContent=m.fill_assumption+' Fee schedule: '+m.fee_schedule+'. Means are cluster-weighted (one game = one observation); +/- is 1.645 cluster standard errors (approximate 90% interval). Model-vs-market uses paired contracts at the same quote; negative Brier diff = model better.';
  const vers=[...new Set(D.rows.flatMap(r=>Object.keys(r.mo)))].sort();
  const fams=[...new Set(D.contracts.map(c=>c.f))].sort();
  $('bar').innerHTML=`
   <label>Family<select id="ffam"><option value="">all</option>${opts(fams)}</select></label>
   <label>Entry point<select id="fent">${opts(FL.ENTRY)}</select></label>
   <label>Game date from<input id="fd0" type="date"></label><label>to<input id="fd1" type="date"></label>
   <label>Price min<input id="fp0" type="number" step="0.05" min="0" max="1" placeholder="0"></label>
   <label>Price max<input id="fp1" type="number" step="0.05" min="0" max="1" placeholder="1"></label>
   <label>Hours before tip &le;<input id="fh" type="number" step="1" placeholder="any"></label>
   <label>Model version<select id="fver">${opts(vers.length?vers:['(none)'])}</select></label>
   <label>Quality tier<select id="ftier"><option value="">all</option><option>A</option><option>B</option><option>C</option></select></label>`;
  document.querySelectorAll('#bar select,#bar input').forEach(e=>e.addEventListener('input',draw));
  $('fent').value='CLOSE'; if(vers.includes('pure-0.5.0'))$('fver').value='pure-0.5.0';
  draw();
}
function filt(){return{fam:$('ffam').value,ent:$('fent').value,d0:$('fd0').value,d1:$('fd1').value,
  p0:parseFloat($('fp0').value),p1:parseFloat($('fp1').value),h:parseFloat($('fh').value),
  ver:$('fver').value,tier:$('ftier').value}}
function cok(c,f){return(!f.fam||c.f===f.fam)&&(!f.d0||c.d>=f.d0)&&(!f.d1||c.d<=f.d1)}
function rok(r,f){
  if(r.e!==f.ent||!cok(r,f))return false;
  if(!isNaN(f.p0)&&(r.m===null||r.m<f.p0))return false;
  if(!isNaN(f.p1)&&(r.m===null||r.m>f.p1))return false;
  if(!isNaN(f.h)&&(r.h===null||r.h>f.h))return false;
  if(f.tier&&r.q!==f.tier)return false; return true}
function cm(pairs){ // cluster-weighted mean and SE
  const by={};for(const[k,v]of pairs)(by[k]=by[k]||[]).push(v);
  const ms=Object.values(by).map(a=>a.reduce((x,y)=>x+y,0)/a.length),n=ms.length;
  if(!n)return null; const mu=ms.reduce((x,y)=>x+y,0)/n;
  const se=n>1?Math.sqrt(ms.reduce((x,y)=>x+(y-mu)**2,0)/(n-1)/n):null;
  return{mu,se,n,k:pairs.length}}
function fmt(o,d=4,pct=false){if(!o)return'<span class=low>–</span>';
  const v=pct?o.mu*100:o.mu,e=o.se===null?'':` ±${((pct?100:1)*1.645*o.se).toFixed(d)}`;
  return`${v.toFixed(d)}${e} <span class=sub>(${o.n}g/${o.k})</span>`}
function ratio(items){const by={};let a=0,b=0;for(const[k,x,y]of items){a+=x;b+=y}
  return b?{mu:a/b,se:null,n:new Set(items.map(i=>i[0])).size,k:items.length}:null}
function draw(){
  const f=filt(),ff={...f,fam:''};
  const famList=[...new Set(D.contracts.map(c=>c.f))].sort();
  let h='<tr><th>Family</th><th>Contracts</th><th>Snapshots</th><th>Modeled</th><th>Settled</th><th>Mkt Brier</th><th>Mkt logloss</th><th>Model Brier</th><th>Δ Brier (model−mkt)</th><th>YES-buy net ROI</th><th>NO-buy net ROI</th><th>Net CLV</th><th>Confidence</th></tr>';
  for(const fam of famList){
    if(f.fam&&f.fam!==fam)continue;
    const cs=D.contracts.filter(c=>c.f===fam&&cok(c,f));
    if(!cs.length)continue;
    const rs=D.rows.filter(r=>r.f===fam&&rok(r,f)&&r.m!==null&&(r.tv||fam.startsWith('FUT')));
    const mb=cm(rs.map(r=>[r.c,(r.m-r.y)**2]));
    const ml=cm(rs.map(r=>{const q=Math.min(Math.max(r.m,1e-4),1-1e-4);return[r.c,-(r.y?Math.log(q):Math.log(1-q))]}));
    const pr=rs.filter(r=>r.mo[f.ver]);
    const mdl=cm(pr.map(r=>[r.c,(r.mo[f.ver][0]-r.y)**2]));
    const df=cm(pr.map(r=>[r.c,(r.mo[f.ver][0]-r.y)**2-(r.m-r.y)**2]));
    const allr=D.rows.filter(r=>r.f===fam&&rok(r,f));
    const ry=ratio(allr.filter(r=>r.Y).map(r=>[r.c,r.Y[0],r.Y[1]]));
    const rn=ratio(allr.filter(r=>r.N).map(r=>[r.c,r.N[0],r.N[1]]));
    const cl=cm(allr.flatMap(r=>[r.cy,r.cn].filter(x=>x!==null).map(x=>[r.c,x])));
    const modeled=cs.filter(c=>c.mo==='MODELED').length,settled=cs.filter(c=>c.r==='yes'||c.r==='no').length;
    const cls=new Set(cs.map(c=>c.c)).size,conf=mb?(mb.n<30?'LOW':mb.n<100?'MEDIUM':'HIGH'):'—';
    const sd=df&&df.se!==null?(df.mu+1.645*df.se<0?'neg':df.mu-1.645*df.se>0?'pos':''):'';
    h+=`<tr class=fam data-f="${fam}"><td>${fam}</td><td>${cs.length.toLocaleString()} <span class=sub>(${cls}g)</span></td><td>${cs.reduce((a,c)=>a+c.n,0).toLocaleString()}</td><td>${modeled}/${cs.length}</td><td>${settled}/${cs.length}</td><td>${fmt(mb)}</td><td>${fmt(ml)}</td><td>${fmt(mdl)}</td><td class="${sd}">${fmt(df)}</td><td>${ry?(ry.mu*100).toFixed(1)+'%':'–'}</td><td>${rn?(rn.mu*100).toFixed(1)+'%':'–'}</td><td>${cl?cl.mu.toFixed(4):'–'}</td><td>${conf}</td></tr>`}
  $('fam').innerHTML=h;
  document.querySelectorAll('tr.fam').forEach(tr=>tr.onclick=()=>{state.fam=tr.dataset.f;drill()});
  drill()}
function drill(){
  const f=filt(),fam=state.fam||f.fam; if(!fam){$('det').innerHTML='';$('dtitle').textContent='Contracts (select a family)';return}
  $('dtitle').textContent='Contracts · '+fam;
  const cs=D.contracts.filter(c=>c.f===fam&&cok(c,f)).slice(0,500);
  let h='<tr><th>Ticker</th><th>Title</th><th>Date</th><th>Snaps</th><th>Result</th><th>Close mid</th><th>Model</th><th>Official check</th><th>Flags</th></tr>';
  for(const c of cs)h+=`<tr><td class=l>${c.k}</td><td class=l>${c.t||''}</td><td>${c.d}</td><td>${c.n}</td><td>${c.r||'–'}</td><td>${c.m===null?'–':c.m.toFixed(3)}</td><td class=l>${c.mo==='MODELED'?'modeled':(c.mg||'unmodeled')}</td><td>${c.oc}</td><td class=l>${c.fl.join(' ')}</td></tr>`;
  $('det').innerHTML=h}
load();
</script></body></html>
"""
