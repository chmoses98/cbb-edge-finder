"""Self-contained market-family research dashboard (one HTML file, data embedded gzip+base64).

Rows are one per (settled contract, entry point). All filtering is client-side; headline numbers
are cluster-weighted (one game = one vote) so correlated ladders cannot inflate sample size.
"""

from __future__ import annotations

import base64
import gzip
import json
from typing import Any


def _r(x: float | None, n: int = 4) -> float | None:
    return None if x is None else round(x, n)


def _decimate(points: list[list[Any]], cap: int = 90) -> list[list[Any]]:
    if len(points) <= cap:
        return points
    step = (len(points) - 1) / (cap - 1)
    keep = sorted({round(i * step) for i in range(cap)})
    return [points[i] for i in keep]


def timelines(contracts: dict[str, Any], summaries: list[dict[str, Any]]) -> dict[str, Any]:
    """Real captured quote runs per contract (minutes since epoch, bid, ask) for game contracts.

    Only contracts tied to a verified game or already settled get a timeline; futures with
    hundreds of captures are excluded to keep the page small (they stay in the inventory)."""
    want = {s["ticker"] for s in summaries if s["game_start"] or s["result"] in ("yes", "no")}
    out: dict[str, Any] = {}
    for tk in want:
        c = contracts.get(tk)
        if c is None or len(c.obs) > 4000:
            continue
        pts = [
            [int(o.t0.timestamp() // 60), o.yes_bid, o.yes_ask, o.status[:1], o.n] for o in c.obs
        ]
        out[tk] = _decimate(pts)
    return out


def slim(
    summaries: list[dict[str, Any]],
    rows: list[dict[str, Any]],
    contracts: dict[str, Any] | None = None,
    night: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from cbb_edge.kalshi.mapping import event_date

    close_mid: dict[str, float | None] = {}
    for r in rows:
        if r["entry"] == "CLOSE":
            close_mid[r["ticker"]] = r["mid"]
    date_of: dict[str, str] = {}
    out_contracts = []
    for c in summaries:
        d = (c["game_start"] or c["close_time"] or "")[:10]
        date_of[c["ticker"]] = d
        ed = event_date(c["event"])
        out_contracts.append(
            {
                "k": c["ticker"], "f": c["family"], "s": c["series"], "c": c["cluster"], "d": d,
                "ev": ed.isoformat() if ed else None, "r": c["result"], "fl": c["status_flags"],
                "t": c["title"] or c["yes_sub_title"], "m": close_mid.get(c["ticker"]),
                "mo": c["status"]["model"], "mg": c["status"]["model_missing_capability"],
                "oc": c["status"]["official_check"], "n": c["n_snapshots"], "mp": c["status"]["mapping"],
                "rules": (c.get("rules") or "")[:420], "gs": c["game_start"], "ct": c["close_time"],
                "st": c["settlement_ts"], "sv": c["status"]["support"], "ou": c["status"]["outcome"],
                "gap": c.get("pretip_gap_reason"), "miss": c["entry_points_missing"],
                "sem": c["side_semantics"], "g": c["espn_game_id"],
            }
        )  # fmt: skip
    detail_tickers = {c["k"] for c in out_contracts if c["gs"] or c["r"] in ("yes", "no")}
    out_rows = []
    entries: dict[str, list[Any]] = {}
    for r in rows:
        yf, nf = r["yes"], r["no"]
        if r["y"] is not None:
            out_rows.append(
                {
                    "k": r["ticker"], "f": r["family"], "s": r["series"], "c": r["cluster"],
                    "e": r["entry"], "h": _r(r["hours_before_ref"], 2), "m": _r(r["mid"]),
                    "y": r["y"], "sp": _r(r["spread"], 3), "q": r["tier"],
                    "st": _r(r["staleness_min"], 0),
                    "d": date_of.get(r["ticker"], ""), "tv": r["tip_verified"],
                    "Y": [_r(yf["net_pnl"]), _r(yf["total_cost"])] if "net_pnl" in yf else None,
                    "N": [_r(nf["net_pnl"]), _r(nf["total_cost"])] if "net_pnl" in nf else None,
                    "Yg": _r(yf.get("gross_pnl")), "Ng": _r(nf.get("gross_pnl")),
                    "Yp": _r(yf.get("price")), "Np": _r(nf.get("price")),
                    "cy": _r(yf.get("clv_net")), "cn": _r(nf.get("clv_net")),
                    "cgy": _r(yf.get("clv_gross")), "cgn": _r(nf.get("clv_gross")),
                    "mo": {v: [_r(m["p"]), _r(m.get("ev_yes")), _r(m.get("ev_no"))]
                           for v, m in r["model"].items()},
                }
            )  # fmt: skip
        if r["ticker"] in detail_tickers:
            entries.setdefault(r["ticker"], []).append(
                {
                    "e": r["entry"], "t": r["t"], "h": _r(r["hours_before_ref"], 2),
                    "b": r["yes_bid"], "a": r["yes_ask"], "m": _r(r["mid"]), "q": r["tier"],
                    "sz": [r["bid_sz"], r["ask_sz"]], "st": r["staleness_min"],
                    "Y": {k: _r(v) if isinstance(v, float) else v for k, v in yf.items()},
                    "N": {k: _r(v) if isinstance(v, float) else v for k, v in nf.items()},
                    "mo": {v: {k: _r(x) for k, x in m.items()} for v, m in r["model"].items()},
                    "fb": r["fee_basis"], "fr": r["fee_rule"],
                }
            )  # fmt: skip
    return {
        "contracts": out_contracts,
        "rows": out_rows,
        "entries": entries,
        "timelines": timelines(contracts, summaries) if contracts else {},
        "night": {k: v for k, v in (night or {}).items() if k != "table"},
        "night_rows": [
            {
                "k": t["ticker"], "f": t["family"], "g": t["game"], "i": t["issues"],
                "rd": "".join(
                    "1" if t[k] else "0"
                    for k in (
                        "captured", "valid_pretip_quote", "frozen_pretip_model_prediction",
                        "closing_quote_captured", "official_result_available",
                        "official_agrees_with_kalshi", "market_accuracy_evaluable",
                        "model_accuracy_evaluable", "after_fee_profitability_evaluable",
                    )
                ),
                "gap": t["pretip_gap_reason"],
            }
            for t in (night or {}).get("table", [])
        ],
    }  # fmt: skip


def study_summary(side_study: dict[str, Any]) -> dict[str, Any]:
    """Compact, honest summary of the side study for the dashboard (full detail stays in the JSON)."""
    fams: dict[str, Any] = {}
    for name, b in side_study.get("families", {}).items():
        sl = b["slices"]
        top = sorted(
            ((k, s) for k, s in sl.items() if s["net_roi"] is not None and s["games"] >= 15),
            key=lambda kv: -kv[1]["net_roi"],
        )[:8]
        fams[name] = {
            "games": b["games_total"], "discovery_games": b["discovery_games"],
            "holdout_games": b["holdout_games"], "slices_tested": b["slices_tested"],
            "holm_lt_010": sum(1 for s in sl.values() if s.get("holm_p", 1) < 0.10),
            "top": [
                {
                    "slice": k, "games": s["games"], "net": s["net_roi"], "lo": s["net_lo"],
                    "hi": s["net_hi"], "p": s["p_le_zero"], "holm": s.get("holm_p"),
                    "disc": s["discovery"]["net_roi"], "hold": s["holdout"]["net_roi"],
                    "hold_games": s["holdout"]["games"],
                }
                for k, s in top
            ],
            "calibration": b.get("market_calibration_h1", []),
        }  # fmt: skip
    gl = side_study.get("game_level", {})
    strat = [
        {"strategy": k, "games": s["games"], "net": s["net_roi"], "lo": s["net_lo"], "hi": s["net_hi"],
         "holm": s.get("holm_p"), "disc": s["discovery"]["net_roi"], "hold": s["holdout"]["net_roi"],
         "hold_games": s["holdout"]["games"]}
        for k, s in gl.get("strategies", {}).items()
    ]  # fmt: skip
    return {"families": fams, "strategies": strat, "strategies_tested": gl.get("tested", 0),
            "design": side_study.get("design")}  # fmt: skip


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
:root{--bg:#f7f7f4;--fg:#1b1c1a;--mut:#65675f;--line:#d9d9d1;--card:#fff;--acc:#2b5db3;--bad:#b3261e;--good:#17794a;--warn:#946200}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#141513;--fg:#ebebe5;--mut:#9b9d94;--line:#33352f;--card:#1d1e1b;--acc:#7ca6ee;--bad:#f27870;--good:#5ccb8c;--warn:#e0b44c;color-scheme:dark}}
:root[data-theme="dark"]{--bg:#141513;--fg:#ebebe5;--mut:#9b9d94;--line:#33352f;--card:#1d1e1b;--acc:#7ca6ee;--bad:#f27870;--good:#5ccb8c;--warn:#e0b44c;color-scheme:dark}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.45 system-ui,sans-serif}
main{max-width:1240px;margin:0 auto;padding-block:16px;padding-left:max(16px,env(safe-area-inset-left,0px));padding-right:max(16px,env(safe-area-inset-right,0px))}
h1{font-size:20px;margin:0}h2{font-size:15px;margin:22px 0 8px}h3{font-size:13px;margin:14px 0 6px;color:var(--mut);text-transform:uppercase;letter-spacing:.05em}
.sub{color:var(--mut);font-size:12px}
nav{display:flex;gap:4px;margin:12px 0;flex-wrap:wrap}
nav button{background:var(--card);color:var(--fg);border:1px solid var(--line);border-radius:6px;padding:6px 12px;font:inherit;cursor:pointer}
nav button[aria-selected="true"]{border-color:var(--acc);color:var(--acc);font-weight:600}
button:focus-visible,select:focus-visible,input:focus-visible,a:focus-visible,tr[tabindex]:focus-visible{outline:2px solid var(--acc);outline-offset:1px}
.bar{display:flex;flex-wrap:wrap;gap:10px;background:var(--card);border:1px solid var(--line);border-radius:8px;padding:10px;margin:8px 0}
.bar label{display:flex;flex-direction:column;font-size:11px;color:var(--mut);gap:2px;min-width:0}
select,input{background:var(--bg);color:var(--fg);border:1px solid var(--line);border-radius:5px;padding:4px 6px;font:inherit;min-width:90px}
.wrap{overflow-x:auto;border:1px solid var(--line);border-radius:8px;background:var(--card)}
table{border-collapse:collapse;width:100%;font-size:12.5px;font-variant-numeric:tabular-nums}
th,td{padding:6px 8px;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap}
th:first-child,td:first-child{text-align:left}th{color:var(--mut);font-weight:600;position:sticky;top:0;background:var(--card)}
tr.click{cursor:pointer}tr.click:hover{background:color-mix(in srgb,var(--acc) 8%,transparent)}
.neg{color:var(--good)}.pos{color:var(--bad)}.low{color:var(--mut);font-style:italic}
.note{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:10px;font-size:12px;color:var(--mut);margin:8px 0}
td.l{text-align:left;max-width:380px;overflow:hidden;text-overflow:ellipsis}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px}
.card{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:10px 12px;min-width:0}
.card b{display:block;font-size:20px;font-variant-numeric:tabular-nums}.card span{font-size:12px;color:var(--mut)}
.flag{display:inline-block;border:1px solid var(--line);border-radius:10px;padding:0 7px;margin:1px 2px 1px 0;font-size:11px}
.flag.bad{border-color:var(--bad);color:var(--bad)}.flag.ok{border-color:var(--good);color:var(--good)}.flag.warn{border-color:var(--warn);color:var(--warn)}
.grid2{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:12px}
dl{margin:0;display:grid;grid-template-columns:max-content 1fr;gap:3px 12px;font-size:12.5px}dt{color:var(--mut)}dd{margin:0;overflow-wrap:anywhere}
svg text{fill:var(--mut);font-size:10px}svg .g{stroke:var(--line)}
</style></head><body><main>
<h1>CBB market research</h1>
<div class="sub" id="meta"></div>
<nav id="tabs" role="tablist"></nav>
<div id="view"></div>
</main>
<script>
const B64="__DATA__";
let D,V=sessionStorageSafe(),UI={tab:'Overview',ticker:null};
function sessionStorageSafe(){return{}}
const $=id=>document.getElementById(id);
const esc=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const ENTRIES=['OPEN','H24','H6','H1','CLOSE'];
async function load(){
  const bin=Uint8Array.from(atob(B64),c=>c.charCodeAt(0));
  const r=new Response(new Blob([bin]).stream().pipeThrough(new DecompressionStream('gzip')));
  D=await r.json();
  D.byK=new Map(D.contracts.map(c=>[c.k,c]));
  const m=D.meta;
  $('meta').textContent=`generated ${m.generated_at} · ${m.snapshots} snapshots · ${D.contracts.length.toLocaleString()} contracts · ${D.rows.length.toLocaleString()} scored entry rows · authority ${m.bet_authority}`;
  tabs(); draw();
}
function tabs(){
  $('tabs').innerHTML=['Overview','Families','Signals','Opening night','Contract'].map(t=>`<button role="tab" aria-selected="${UI.tab===t}" data-t="${t}">${t}</button>`).join('');
  $('tabs').querySelectorAll('button').forEach(b=>b.onclick=()=>{UI.tab=b.dataset.t;tabs();draw()});
}
function draw(){({'Overview':overview,'Families':families,'Signals':signals,'Opening night':night,'Contract':contract})[UI.tab]()}
function pct(x,d=1){return x==null||isNaN(x)?'–':(x*100).toFixed(d)+'%'}
function n4(x,d=4){return x==null||isNaN(x)?'–':Number(x).toFixed(d)}
function cm(pairs){const by={};for(const[k,v]of pairs)(by[k]=by[k]||[]).push(v);
  const ms=Object.values(by).map(a=>a.reduce((x,y)=>x+y,0)/a.length),n=ms.length;if(!n)return null;
  const mu=ms.reduce((x,y)=>x+y,0)/n,se=n>1?Math.sqrt(ms.reduce((x,y)=>x+(y-mu)**2,0)/(n-1)/n):null;return{mu,se,n,k:pairs.length}}
function fmt(o,d=4){if(!o)return'<span class=low>–</span>';const e=o.se==null?'':` ±${(1.645*o.se).toFixed(d)}`;return`${o.mu.toFixed(d)}${e} <span class=sub>(${o.n}g/${o.k})</span>`}
function ratio(items){let a=0,b=0;for(const[,x,y]of items){a+=x;b+=y}return b?{mu:a/b,n:new Set(items.map(i=>i[0])).size,k:items.length}:null}
function card(v,l){return`<div class=card><b>${v}</b><span>${l}</span></div>`}
function flagCls(f){return f==='EVALUATED'?'ok':f==='PARTIAL'||f==='UNSETTLED'||f==='UNMODELED'?'warn':'bad'}
function count(a,f){const o={};for(const x of a){const k=f(x);if(k!=null)o[k]=(o[k]||0)+1}return Object.entries(o).sort((a,b)=>b[1]-a[1])}
function tbl(rows,heads){return`<div class=wrap><table><tr>${heads.map(h=>`<th>${h}</th>`).join('')}</tr>${rows.map(r=>`<tr>${r.map((c,i)=>`<td${i?'':''}>${c}</td>`).join('')}</tr>`).join('')}</table></div>`}

function overview(){
  const C=D.contracts,H=D.meta.health,F=H.findings,N=C.length;
  const modeled=C.filter(c=>c.mo==='MODELED').length,settled=C.filter(c=>c.r==='yes'||c.r==='no').length;
  const noPre=C.filter(c=>c.gap).length,noClose=C.filter(c=>c.miss.includes('CLOSE')).length;
  const scored=D.rows.filter(r=>r.e==='CLOSE'&&r.m!=null).length;
  const age=F.latest_snapshot_age_minutes;
  const fams=[...new Set(C.map(c=>c.f))].length,ser=[...new Set(C.map(c=>c.s))].length;
  let h=`<div class=cards>${card(N.toLocaleString(),'contracts discovered')}${card(D.meta.snapshots,'captured snapshots')}${card(fams+' / '+ser,'families / series')}
   ${card(pct(modeled/N),`model coverage (${modeled.toLocaleString()} modeled)`)}${card(pct(settled/N),`settlement coverage (${settled.toLocaleString()} settled)`)}
   ${card(scored.toLocaleString(),'settled contracts with a scored closing quote')}${card(noPre.toLocaleString(),'no pretip quote (causes below)')}${card(noClose.toLocaleString(),'no closing quote')}
   ${card(age==null?'–':Math.round(age/60*10)/10+' h',`archive age at build · ${F.latest_snapshot_stale?'STALE':'fresh'}`)}${card(F.panel_backlog??'–','snapshots without panel partition')}</div>`;
  const G=H.grade||{status:H.healthy?'HEALTHY':'DEGRADED',critical:[],degraded:[]},CI=H.capture_intervals||{};
  const rAge=Math.round((Date.now()-Date.parse(D.meta.generated_at))/60000);
  h+=`<div class=note><b class="${G.status==='HEALTHY'?'neg':'pos'}">${G.status}</b>${[...G.critical,...G.degraded].length?' · '+esc([...G.critical,...G.degraded].join(', ')):''}<br>Research published ${rAge} min ago${rAge>180?' <span class=pos>(stale)</span>':''} · recent capture intervals (min): ${esc((CI.recent_minutes||[]).join(', '))||'–'} (median ${CI.median??'–'}, p90 ${CI.p90??'–'})<br>Fee schedule: <b>${esc((H.fee_verification||{}).status||'UNVERIFIED')}</b>${(H.fee_verification||{}).status==='MATCH'?' (official coefficients match; document '+esc(((H.fee_verification||{}).document_sha256||'').slice(0,10))+')':''}${(H.fee_verification||{}).status==='UNVERIFIED'?' (official schedule not yet archived; coefficients are assumptions)':''}<br>Latest snapshot ${esc(H.last_snapshot)} · health ${H.healthy?'<span class=neg>healthy</span>':'<span class=pos>needs attention</span>'} · fee schedule ${esc(D.meta.fee_schedule)} · ${esc(D.meta.fill_assumption)}</div>`;
  h+='<div class=grid2><div><h3>Pretip quote gaps (all contracts)</h3>'+tbl(count(C,c=>c.gap).map(([k,v])=>[esc(k),v]),['Cause','Contracts'])+
   '</div><div><h3>Health findings</h3>'+tbl(Object.entries(F).map(([k,v])=>[esc(k),esc(typeof v==='boolean'?(v?'yes':'no'):v)]),['Check','Value'])+'</div>';
  const pl=(H.pipelines&&H.pipelines.findings)||[];
  h+=`<div><h3>Pipeline monitor (24 h)</h3>${pl.length?tbl(pl.map(x=>[esc(x)]),['Finding']):'<div class=note>No pipeline findings (or monitor input unavailable).</div>'}</div>`;
  h+=`<div><h3>Fee basis of evaluated quotes</h3>${tbl(Object.entries(D.matrix.fee_basis_rows||{}).map(([k,v])=>[esc(k),v.toLocaleString()]),['Fee basis','Entry rows'])}<div class=sub>assumed_default = schedule not yet read from the Kalshi API for that series.</div></div></div>`;
  $('view').innerHTML=h}

let FF={ent:'CLOSE',ver:'',fam:'',d0:'',d1:'',p0:NaN,p1:NaN,h:NaN,tier:'',stale:120};
function families(){
  const vers=[...new Set(D.rows.flatMap(r=>Object.keys(r.mo)))].sort();
  if(!FF.ver)FF.ver=vers.includes('pure-0.5.0')?'pure-0.5.0':vers[0]||'';
  const fams=[...new Set(D.contracts.map(c=>c.f))].sort();
  const o=a=>a.map(x=>`<option${x===FF.ver||x===FF.ent?' selected':''}>${x}</option>`).join('');
  $('view').innerHTML=`<div class=bar>
   <label>Family<select id="ffam"><option value="">all</option>${fams.map(f=>`<option${f===FF.fam?' selected':''}>${f}</option>`).join('')}</select></label>
   <label>Entry point<select id="fent">${o(ENTRIES)}</select></label>
   <label>Game date from<input id="fd0" type="date" value="${FF.d0}"></label><label>to<input id="fd1" type="date" value="${FF.d1}"></label>
   <label>Price min<input id="fp0" type="number" step="0.05" min="0" max="1" value="${isNaN(FF.p0)?'':FF.p0}"></label>
   <label>Price max<input id="fp1" type="number" step="0.05" min="0" max="1" value="${isNaN(FF.p1)?'':FF.p1}"></label>
   <label>Hours before tip &le;<input id="fh" type="number" step="1" value="${isNaN(FF.h)?'':FF.h}"></label>
   <label>Model version<select id="fver">${o(vers.length?vers:['(none)'])}</select></label>
   <label>Max closing-quote age (min)<input id="fst" type="number" step="15" min="0" value="${FF.stale}"></label>
   <label>Quality tier<select id="ftier">${['','A','B','C'].map(t=>`<option value="${t}"${t===FF.tier?' selected':''}>${t||'all'}</option>`).join('')}</select></label></div>
   <div class=note>Means are cluster-weighted (one game = one observation); ± is 1.645 cluster standard errors. Model-vs-market is paired on the same contracts and quote; negative Δ Brier = model better. The pooled-leg CLV column is a cost measure (closing mid minus entry ask averaged over YES and NO legs: movement cancels, so it equals the entry half-spread plus fee); selection CLV on the model-preferred side is in matrix.json (clv_selection_model_side). ROI is a hypothetical taker fill (see assumptions above), shown gross and net of fees; it is not a performance claim.</div>
   <div class=wrap><table id="fam"></table></div><h2 id="dt"></h2><div class=wrap style="max-height:420px"><table id="det"></table></div>`;
  for(const[id,k,t]of[['ffam','fam','s'],['fent','ent','s'],['fd0','d0','s'],['fd1','d1','s'],['fp0','p0','n'],['fp1','p1','n'],['fh','h','n'],['fst','stale','n'],['fver','ver','s'],['ftier','tier','s']])
    $(id).oninput=e=>{FF[k]=t==='n'?parseFloat(e.target.value):e.target.value;famTable()};
  famTable()}
function cok(c,f){return(!f.fam||c.f===f.fam)&&(!f.d0||c.d>=f.d0)&&(!f.d1||c.d<=f.d1)}
function rok(r,f){if(r.e!==f.ent||!cok(r,f))return false;
  if(!isNaN(f.p0)&&(r.m==null||r.m<f.p0))return false;if(!isNaN(f.p1)&&(r.m==null||r.m>f.p1))return false;
  if(!isNaN(f.h)&&(r.h==null||r.h>f.h))return false;if(f.tier&&r.q!==f.tier)return false;if(r.e==='CLOSE'&&!isNaN(f.stale)&&r.st!=null&&r.st>f.stale)return false;return true}
let DRILL=null;
function famTable(){
  const f=FF;let h='<tr><th>Family</th><th>Contracts</th><th>Snapshots</th><th>Modeled</th><th>Settled</th><th>Mkt Brier</th><th>Mkt log loss</th><th>Model Brier</th><th>Δ Brier</th><th>YES gross / net ROI</th><th>NO gross / net ROI</th><th title="Closing mid minus entry ask, averaged over YES and NO legs: movement cancels, so this equals the entry half-spread plus fee. It measures the cost of crossing the spread, not selection skill.">Pooled-leg CLV (= spread cost)</th><th>Completeness</th><th>Confidence</th></tr>';
  for(const fam of[...new Set(D.contracts.map(c=>c.f))].sort()){
    if(f.fam&&f.fam!==fam)continue;const cs=D.contracts.filter(c=>c.f===fam&&cok(c,f));if(!cs.length)continue;
    const rs=D.rows.filter(r=>r.f===fam&&rok(r,f)&&r.m!=null&&(r.tv||fam.startsWith('FUT')));
    const mb=cm(rs.map(r=>[r.c,(r.m-r.y)**2])),ml=cm(rs.map(r=>{const q=Math.min(Math.max(r.m,1e-4),1-1e-4);return[r.c,-(r.y?Math.log(q):Math.log(1-q))]}));
    const pr=rs.filter(r=>r.mo[f.ver]),mdl=cm(pr.map(r=>[r.c,(r.mo[f.ver][0]-r.y)**2])),df=cm(pr.map(r=>[r.c,(r.mo[f.ver][0]-r.y)**2-(r.m-r.y)**2]));
    const all=D.rows.filter(r=>r.f===fam&&rok(r,f));
    const ry=ratio(all.filter(r=>r.Y).map(r=>[r.c,r.Y[0],r.Y[1]])),rn=ratio(all.filter(r=>r.N).map(r=>[r.c,r.N[0],r.N[1]]));
    const gy=ratio(all.filter(r=>r.Y&&r.Yg!=null).map(r=>[r.c,r.Yg,r.Yp])),gn=ratio(all.filter(r=>r.N&&r.Ng!=null).map(r=>[r.c,r.Ng,r.Np]));
    const cl=cm(all.flatMap(r=>[r.cy,r.cn].filter(x=>x!=null).map(x=>[r.c,x])));
    const modeled=cs.filter(c=>c.mo==='MODELED').length,settled=cs.filter(c=>c.r==='yes'||c.r==='no').length;
    const withEntry=cs.filter(c=>!c.miss.includes(f.ent)).length;
    const cls=new Set(cs.map(c=>c.c)).size,conf=mb?(mb.n<30?'LOW':mb.n<100?'MEDIUM':'HIGH'):'—';
    const sd=df&&df.se!=null?(df.mu+1.645*df.se<0?'neg':df.mu-1.645*df.se>0?'pos':''):'';
    h+=`<tr class=click tabindex=0 data-f="${fam}"><td>${fam}</td><td>${cs.length.toLocaleString()} <span class=sub>(${cls}g)</span></td><td>${cs.reduce((a,c)=>a+c.n,0).toLocaleString()}</td><td>${modeled}/${cs.length}</td><td>${settled}/${cs.length}</td><td>${fmt(mb)}</td><td>${fmt(ml)}</td><td>${fmt(mdl)}</td><td class="${sd}">${fmt(df)}</td><td>${pct(gy&&gy.mu)} / ${pct(ry&&ry.mu)}</td><td>${pct(gn&&gn.mu)} / ${pct(rn&&rn.mu)}</td><td>${cl?cl.mu.toFixed(4):'–'}</td><td>${pct(withEntry/cs.length,0)} have ${f.ent}</td><td>${conf}</td></tr>`}
  $('fam').innerHTML=h;$('fam').querySelectorAll('tr.click').forEach(tr=>{tr.onclick=tr.onkeydown=e=>{if(e.type==='keydown'&&e.key!=='Enter')return;DRILL=tr.dataset.f;famDrill()}});famDrill()}
function famDrill(){const f=FF,fam=DRILL||f.fam;if(!fam){$('det').innerHTML='';$('dt').textContent='Contracts (select a family)';return}
  $('dt').textContent='Contracts · '+fam;const cs=D.contracts.filter(c=>c.f===fam&&cok(c,f)).slice(0,500);
  $('det').innerHTML='<tr><th>Ticker</th><th>Title</th><th>Date</th><th>Snaps</th><th>Result</th><th>Close mid</th><th>Model</th><th>Official check</th><th>Flags</th></tr>'+cs.map(c=>`<tr class=click tabindex=0 data-k="${esc(c.k)}"><td class=l>${esc(c.k)}</td><td class=l>${esc(c.t)}</td><td>${c.d}</td><td>${c.n}</td><td>${c.r||'–'}</td><td>${c.m==null?'–':c.m.toFixed(3)}</td><td class=l>${c.mo==='MODELED'?'modeled':esc(c.mg||'unmodeled')}</td><td>${esc(c.oc)}</td><td class=l>${c.fl.join(' ')}</td></tr>`).join('');
  $('det').querySelectorAll('tr.click').forEach(tr=>tr.onclick=tr.onkeydown=e=>{if(e.type==='keydown'&&e.key!=='Enter')return;open(tr.dataset.k)})}
function open(k){UI.ticker=k;UI.tab='Contract';tabs();draw()}

const stCls=s=>s==='VALIDATED'?'ok':s==='REJECTED'?'bad':s==='SHADOW_VALIDATING'?'warn':'';
const pc=(x,d=1)=>x==null?'–':(x*100>=0?'+':'')+(x*100).toFixed(d)+'%';
function signals(){
  const C=D.candidates||{candidates:[]},S=D.study||{families:{},strategies:[]};
  let h=`<div class=note><b>Research only.</b> No signal here is an authorized bet. Retrospective results are exploratory: they can never validate a candidate. A candidate is VALIDATED only after a preregistered prospective sample (&ge; its minimum games), a positive 90% lower bound, a Bonferroni-adjusted p-value and a verified official fee schedule.</div>`;
  h+='<h2>Preregistered candidates</h2>';
  if(!C.candidates.length)h+='<div class=note>No candidates registered in this build.</div>';
  else h+=`<div class=wrap><table><tr><th>Candidate</th><th>Status</th><th>Entry</th><th>Prospective games</th><th>Prospective net ROI [90%]</th><th>Discovery net ROI (retro)</th><th>Needs (games)</th><th>Registered</th><th>Config hash</th></tr>${C.candidates.map(c=>{const p=c.prospective,r=c.discovery_retrospective;return`<tr><td class=l title="${esc(c.hypothesis)}">${esc(c.id)}</td><td><span class="flag ${stCls(c.status)}">${c.status}</span></td><td>${c.entry}</td><td>${p.games}</td><td>${p.games?pc(p.net_roi)+' ['+pc(p.net_lo)+', '+pc(p.net_hi)+']':'–'}</td><td>${pc(r.net_roi)} (${r.games} g)</td><td>${c.success_criteria.min_games}</td><td>${esc((c.registered_at||'').slice(0,16))}</td><td>${esc(c.config_sha256.slice(0,10))}</td></tr>`}).join('')}</table></div><div class=sub>Registry violations: ${(C.registry_violations||[]).length}. Hypotheses are in each row's tooltip.</div>`;
  h+='<h2>Side-aware study (exploratory)</h2>';
  h+=`<div class=note>Unit = game. ${S.strategies_tested||0} one-bet-per-game strategies and ${Object.values(S.families).reduce((a,f)=>a+f.slices_tested,0)} price/spread/role slices were examined; <b>Holm-adjusted p &lt; 0.10: ${Object.values(S.families).reduce((a,f)=>a+f.holm_lt_010,0)}</b>. Discovery = earliest 60% of games by tip, holdout = latest 40%.</div>`;
  h+=`<h3>One bet per game</h3><div class=wrap style="max-height:380px"><table><tr><th>Strategy</th><th>Games</th><th>Net ROI [90%]</th><th>Discovery</th><th>Holdout (games)</th><th>Holm p</th></tr>${[...S.strategies].sort((a,b)=>(b.net??-9)-(a.net??-9)).slice(0,24).map(x=>`<tr><td class=l>${esc(x.strategy)}</td><td>${x.games}</td><td>${pc(x.net)} [${pc(x.lo)}, ${pc(x.hi)}]</td><td>${pc(x.disc)}</td><td>${pc(x.hold)} (${x.hold_games})</td><td>${x.holm==null?'–':x.holm.toFixed(2)}</td></tr>`).join('')}</table></div>`;
  for(const[n,f]of Object.entries(S.families)){
    h+=`<h3>${n} · ${f.games} games · top slices by point estimate</h3><div class=wrap><table><tr><th>Slice</th><th>Games</th><th>Net ROI [90%]</th><th>Unadj. p</th><th>Holm p</th><th>Discovery</th><th>Holdout (games)</th></tr>${f.top.map(x=>`<tr><td class=l>${esc(x.slice)}</td><td>${x.games}</td><td>${pc(x.net)} [${pc(x.lo)}, ${pc(x.hi)}]</td><td>${x.p==null?'–':x.p.toFixed(2)}</td><td>${x.holm==null?'–':x.holm.toFixed(2)}</td><td>${pc(x.disc)}</td><td>${pc(x.hold)} (${x.hold_games})</td></tr>`).join('')}</table></div>`;
    if(f.calibration.length)h+=`<div class=sub>Market calibration at 1h before tip: ${f.calibration.map(b=>`${b.bucket}: priced ${(b.mean_mid*100).toFixed(1)}% → happened ${(b.yes_frequency*100).toFixed(1)}% (${b.contracts} contracts)`).join(' · ')}</div>`}
  $('view').innerHTML=h}
const RD=['captured','valid pretip quote','frozen pretip model','closing quote','official result available','official agrees with Kalshi','market accuracy evaluable','model accuracy evaluable','after-fee profit evaluable'];
let NF={fam:'',issue:'',only:true};
function night(){
  const N=D.night,R=D.night_rows;
  if(!R.length){$('view').innerHTML='<div class=note>No contracts dated '+esc(N.night||'')+' in this build.</div>';return}
  let h=`<div class=note>Every contract whose Kalshi event is dated ${esc(N.night)}: ${N.contracts.toLocaleString()} contracts across ${N.games} games. Recommendations play no part in this list.</div>`;
  h+=`<div class=grid2><div><h3>Evaluation readiness</h3>${tbl(RD.map((l,i)=>[l,R.filter(r=>r.rd[i]==='1').length.toLocaleString(),pct(R.filter(r=>r.rd[i]==='1').length/R.length)]),['Question','Contracts','Share'])}</div>
  <div><h3>Settlement reconciliation</h3>${tbl(Object.entries(N.official_check).map(([k,v])=>[esc(k),v.toLocaleString()]),['Official check vs Kalshi result','Contracts'])}<div class=sub>Disagreements: ${N.official_disagreements.length}. Half-game and play-by-play markets cannot be checked because period scores are not archived.</div></div>
  <div><h3>Missing pretip quote causes</h3>${tbl(Object.entries(N.pretip_gap_reasons||{}).map(([k,v])=>[esc(k),v]),['Cause','Contracts'])}</div>
  <div><h3>Missing-data categories</h3>${tbl(Object.entries(N.issue_counts).slice(0,14).map(([k,v])=>[esc(k),v.toLocaleString()]),['Issue','Contracts'])}</div></div>`;
  const fams=[...new Set(R.map(r=>r.f))].sort();
  h+=`<h2>Contracts</h2><div class=bar><label>Family<select id="nf"><option value="">all</option>${fams.map(f=>`<option${f===NF.fam?' selected':''}>${f}</option>`).join('')}</select></label>
   <label>Issue contains<input id="ni" value="${esc(NF.issue)}"></label><label>Only contracts with an issue<input id="no" type="checkbox"${NF.only?' checked':''}></label></div><div class=wrap style="max-height:480px"><table id="nt"></table></div>`;
  $('view').innerHTML=h;
  const upd=()=>{const rs=R.filter(r=>(!NF.fam||r.f===NF.fam)&&(!NF.issue||r.i.toLowerCase().includes(NF.issue.toLowerCase()))&&(!NF.only||r.i)).slice(0,600);
    $('nt').innerHTML='<tr><th>Ticker</th><th>Family</th><th>Ready (9 checks)</th><th>Issues</th></tr>'+rs.map(r=>`<tr class=click tabindex=0 data-k="${esc(r.k)}"><td class=l>${esc(r.k)}</td><td>${r.f}</td><td title="${RD.join(' | ')}">${[...r.rd].map(b=>b==='1'?'●':'○').join('')}</td><td class=l>${esc(r.i.split('|').join(' · '))}</td></tr>`).join('');
    $('nt').querySelectorAll('tr.click').forEach(tr=>tr.onclick=tr.onkeydown=e=>{if(e.type==='keydown'&&e.key!=='Enter')return;open(tr.dataset.k)})};
  $('nf').oninput=e=>{NF.fam=e.target.value;upd()};$('ni').oninput=e=>{NF.issue=e.target.value;upd()};$('no').oninput=e=>{NF.only=e.target.checked;upd()};upd()}

function timeline(k,c,entries){
  const pts=D.timelines[k];if(!pts||!pts.length)return'<div class=note>No quote timeline stored for this contract (futures and very long histories are kept in the archive only).</div>';
  const W=720,H=230,L=34,R=10,T=10,Bm=26,t0=pts[0][0],gs=c.gs?Date.parse(c.gs)/60000:null,ct=c.ct?Date.parse(c.ct)/60000:null;
  const t1=Math.max(pts[pts.length-1][0],gs||0),span=Math.max(t1-t0,1);
  const X=t=>L+(t-t0)/span*(W-L-R),Y=p=>T+(1-p)*(H-T-Bm);
  let s=`<svg viewBox="0 0 ${W} ${H}" width="100%" role="img" aria-label="Captured yes bid and ask over time for ${esc(k)}">`;
  for(const g of[0,.25,.5,.75,1])s+=`<line class=g x1="${L}" x2="${W-R}" y1="${Y(g)}" y2="${Y(g)}"/><text x="2" y="${Y(g)+3}">${g.toFixed(2)}</text>`;
  const step=(idx,col)=>{let d='',last=null;for(const p of pts){const v=p[idx];if(v==null){last=null;continue}const x=X(p[0]);d+=last==null?`M${x},${Y(v)}`:`L${x},${Y(last)}L${x},${Y(v)}`;last=v}return`<path d="${d}" fill="none" stroke="${col}" stroke-width="1.6"/>`};
  s+=step(1,'var(--acc)')+step(2,'var(--bad)');
  for(const p of pts)s+=`<circle cx="${X(p[0])}" cy="${Y(p[2]??p[1]??0)}" r="1.6" fill="var(--bad)"/>`;
  if(gs&&gs>=t0)s+=`<line x1="${X(gs)}" x2="${X(gs)}" y1="${T}" y2="${H-Bm}" stroke="var(--warn)" stroke-dasharray="4 3"/><text x="${X(gs)+3}" y="${T+10}">tip</text>`;
  if(ct&&ct>=t0&&ct<=t1)s+=`<line x1="${X(ct)}" x2="${X(ct)}" y1="${T}" y2="${H-Bm}" stroke="var(--mut)" stroke-dasharray="2 3"/><text x="${X(ct)+3}" y="${T+22}">close</text>`;
  for(const e of entries){const t=Date.parse(e.t)/60000;for(const[v,m]of Object.entries(e.mo).slice(0,1))s+=`<circle cx="${X(t)}" cy="${Y(m.p)}" r="3.5" fill="var(--good)"><title>${esc(v)} p=${m.p} at ${e.e}</title></circle>`;s+=`<text x="${X(t)-8}" y="${H-12-(ENTRIES.indexOf(e.e)%2)*11}">${e.e}</text>`}
  const d=new Date(t0*60000).toISOString().slice(5,16).replace('T',' ');
  s+=`<text x="${L}" y="${H-1}">${d} UTC</text><text x="${W-R-70}" y="${H-1}">${new Date(t1*60000).toISOString().slice(5,16).replace('T',' ')}</text></svg>
  <div class=sub><span style="color:var(--acc)">━</span> yes bid · <span style="color:var(--bad)">━</span> yes ask · <span style="color:var(--good)">●</span> frozen model probability at entry · ${pts.length} distinct captured quotes${pts.length>=90?' (decimated for display)':''}</div>`;
  return s}
function contract(){
  const k=UI.ticker;if(!k){$('view').innerHTML='<div class=note>Select a contract from the Families or Opening night tab.</div>';return}
  const c=D.byK.get(k);if(!c){$('view').innerHTML='<div class=note>Unknown contract.</div>';return}
  const es=(D.entries[k]||[]).sort((a,b)=>ENTRIES.indexOf(a.e)-ENTRIES.indexOf(b.e));
  const fl=c.fl.map(f=>`<span class="flag ${flagCls(f)}">${f}</span>`).join('');
  let h=`<h2 style="margin-top:6px">${esc(c.t)}</h2><div class=sub>${esc(c.k)}</div><div style="margin:6px 0">${fl}</div>
   <div class=grid2><div class=card><dl><dt>Family / series</dt><dd>${c.f} · ${esc(c.s)}</dd><dt>Game</dt><dd>${esc(c.c)}${c.gs?' · tip '+esc(c.gs):''}</dd><dt>YES means</dt><dd>${esc(c.sem||c.rules||'–')}</dd>
   <dt>Mapping</dt><dd>${esc(c.mp)}</dd><dt>Support</dt><dd>${esc(c.sv)}</dd><dt>Model</dt><dd>${c.mo==='MODELED'?'modeled':esc(c.mg||'unmodeled')}</dd><dt>Close time</dt><dd>${esc(c.ct||'–')}</dd></dl></div>
   <div class=card><dl><dt>Settlement</dt><dd>${c.r?`<b>${c.r.toUpperCase()}</b> at ${esc(c.st||'–')}`:esc(c.ou)}</dd><dt>Official result check</dt><dd>${esc(c.oc)}</dd>
   <dt>Pretip quote</dt><dd>${c.gap?`<span class=pos>missing</span> · ${esc(c.gap)}`:'captured'}</dd><dt>Missing entry points</dt><dd>${c.miss.length?c.miss.join(', '):'none'}</dd><dt>Snapshots</dt><dd>${c.n}</dd></dl></div></div>`;
  if(c.rules)h+=`<div class=note>${esc(c.rules)}</div>`;
  h+='<h3>Quote timeline</h3>'+timeline(k,c,es);
  h+='<h3>Entry points: quotes, frozen model, fees and execution</h3>';
  if(!es.length)h+='<div class=note>No pretip entry point could be built for this contract (see the pretip cause above). Nothing was reconstructed.</div>';
  else{const vers=[...new Set(es.flatMap(e=>Object.keys(e.mo)))];
   h+=`<div class=wrap><table><tr><th>Entry</th><th>Captured (UTC)</th><th>Hrs before tip</th><th>Bid / Ask</th><th>Market p (mid)</th><th>Tier</th>${vers.map(v=>`<th>${esc(v)} p · EV yes/no · max entry yes/no</th>`).join('')}<th>YES: price · fee · cash · gross/net P&amp;L</th><th>NO: price · fee · cash · gross/net P&amp;L</th><th>Fee rule</th></tr>`+
    es.map(e=>{const fx=x=>x.fill!=='FILLED'?`<span class=low>${esc(x.fill)}</span>`:`${n4(x.price)} · ${n4(x.fee)} · ${n4(x.total_cost)}${x.net_pnl!=null?` · ${n4(x.gross_pnl)} / ${n4(x.net_pnl)}`:' · unsettled'}`;
     return`<tr><td>${e.e}</td><td>${esc((e.t||'').slice(5,16).replace('T',' '))}</td><td>${e.h==null?'–':e.h}</td><td>${e.b ?? '–'} / ${e.a ?? '–'}</td><td>${n4(e.m,3)}</td><td>${e.q}</td>${vers.map(v=>{const m=e.mo[v];return`<td>${m?`${n4(m.p,3)} · ${n4(m.ev_yes,3)}/${n4(m.ev_no,3)} · ${n4(m.max_entry_yes,2)}/${n4(m.max_entry_no,2)}`:'<span class=low>no prediction</span>'}</td>`}).join('')}<td>${fx(e.Y)}</td><td>${fx(e.N)}</td><td>${esc(e.fb)}</td></tr>`}).join('')+'</table></div>';
   const clv=es.filter(e=>e.Y.clv_gross!=null);
   if(clv.length)h+=`<div class=sub>CLV (YES, vs closing mid): ${clv.map(e=>`${e.e} gross ${n4(e.Y.clv_gross)} / fee-adjusted ${n4(e.Y.clv_net)}`).join(' · ')}</div>`}
  $('view').innerHTML=h}
load();
</script></body></html>
"""
