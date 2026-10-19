#!/usr/bin/env python3
"""Adds the Annual Review flow to eridant-demo.html. Purely additive: 3 insertions, verified by diff."""
import difflib

SRC='/mnt/user-data/uploads/eridant-demo.html'
DST='/mnt/user-data/outputs/eridant-demo.html'
src=open(SRC,encoding='utf8').read()

CSS=r'''
<style id="ar-style">
/* ============ ANNUAL REVIEW MODULE (additive) ============ */
#ar-fab{position:fixed;right:22px;bottom:54px;z-index:70;display:none;align-items:center;gap:12px;background:var(--ink);color:var(--paper);border:1px solid var(--brass);border-radius:999px;padding:11px 18px 11px 14px;cursor:pointer;box-shadow:0 14px 34px rgba(18,32,59,.35);font-family:var(--ff-b);text-align:left;transition:transform .12s,box-shadow .12s}
#ar-fab.show{display:inline-flex}#ar-fab:hover{transform:translateY(-1px);box-shadow:0 18px 40px rgba(18,32,59,.42)}
#ar-fab .k{display:block;font-family:var(--ff-m);font-size:9px;letter-spacing:.14em;color:var(--brass)}
#ar-fab .t{display:block;font-size:13px;font-weight:600;margin-top:2px}
#ar-fab .dot{width:9px;height:9px;border-radius:50%;background:var(--red2);box-shadow:0 0 0 3px rgba(179,64,42,.22)}
#scr-review{position:fixed;inset:0;z-index:80;display:none;overflow:auto;background:#EEF1F6;color:var(--ink);font-family:var(--ff-b);-webkit-overflow-scrolling:touch}
#scr-review.open{display:block}
.ar-top{position:sticky;top:0;z-index:5;display:flex;align-items:center;gap:12px;padding:10px 22px;background:var(--ink-deep);color:var(--paper)}
.ar-top .mark{font-family:var(--ff-m);font-weight:700;letter-spacing:.16em;font-size:14px}.ar-top .mark em{color:var(--brass);font-style:normal}
.ar-top .tag{font-family:var(--ff-m);font-size:9px;letter-spacing:.14em;color:rgba(246,241,231,.55)}
.ar-top .sp{flex:1}
.ar-pill{font-family:var(--ff-m);font-size:9.5px;letter-spacing:.12em;border:1px solid rgba(246,241,231,.3);border-radius:999px;padding:4px 10px;color:rgba(246,241,231,.85)}
.ar-pill.gold{border-color:var(--brass);color:var(--brass)}
.ar-btn{font-family:var(--ff-b);font-size:12.5px;font-weight:600;border-radius:8px;padding:8px 14px;cursor:pointer;border:1px solid var(--line);background:#fff;color:var(--ink)}
.ar-btn.gold{background:var(--brass);border-color:var(--brass);color:#fff}
.ar-btn.ghost{background:transparent;color:var(--paper);border-color:rgba(246,241,231,.35)}
.ar-wrap{max-width:1180px;margin:0 auto;padding:26px 22px 110px}
.ar-k{font-family:var(--ff-m);font-size:9.5px;letter-spacing:.14em;color:var(--grey);text-transform:uppercase}
.ar-hero{position:relative;overflow:hidden;border-radius:20px;padding:30px 34px;background:linear-gradient(130deg,#101A2F 0%,#1B2A47 64%,#24456A 100%);color:#F8FAFD;box-shadow:0 18px 45px rgba(16,26,47,.16);display:flex;gap:22px;flex-wrap:wrap;align-items:flex-end}
.ar-hero .ar-k{color:rgba(248,250,253,.6)}
.ar-hero h1{font-family:var(--ff-d);font-weight:700;font-size:34px;letter-spacing:-.01em;margin:6px 0 4px;color:#fff}
.ar-hero .sub{color:rgba(248,250,253,.8);font-size:13.5px;max-width:720px}
.ar-rating{margin-left:auto;background:rgba(255,255,255,.08);border:1px solid rgba(255,255,255,.18);border-radius:14px;padding:14px 18px;display:flex;gap:18px;align-items:center}
.ar-rating .r{font-family:var(--ff-m);font-weight:700;font-size:24px}.ar-rating .lab{font-family:var(--ff-m);font-size:9px;letter-spacing:.12em;color:rgba(248,250,253,.6)}
.ar-rating .arrow{font-size:22px;color:rgba(248,250,253,.5)}
.ar-chip{display:inline-block;font-family:var(--ff-m);font-size:9.5px;letter-spacing:.1em;font-weight:700;padding:3px 9px;border-radius:6px;white-space:nowrap}
.ar-chip.bad{background:var(--red);color:#fff}.ar-chip.ok{background:var(--ok);color:#fff}.ar-chip.mid{background:var(--brass);color:#fff}.ar-chip.wait{background:var(--grey);color:#fff}.ar-chip.soft{background:var(--paper2);color:var(--brass2)}
.ar-intro{padding:60px 20px;text-align:center}
.ar-intro .big{font-family:var(--ff-d);font-size:40px;font-weight:700;color:var(--ink);margin:6px 0 10px}
.ar-intro .stages{display:inline-block;text-align:left;margin:22px auto 0;min-width:340px}
.ar-intro .st{display:flex;gap:12px;align-items:flex-start;padding:9px 0;color:var(--grey);opacity:.35;transition:opacity .3s}
.ar-intro .st.on{opacity:1;color:var(--ink)}.ar-intro .st.done .dot{background:var(--ok);border-color:var(--ok)}
.ar-intro .dot{width:12px;height:12px;border-radius:50%;border:2px solid var(--brass);margin-top:3px;flex:none}
.ar-intro .st b{display:block;font-size:14px}.ar-intro .st span{font-size:12px;font-family:var(--ff-m);letter-spacing:.02em}
.ar-intro .skip{margin-top:22px;background:none;border:0;color:var(--grey);font-family:var(--ff-m);font-size:10px;letter-spacing:.12em;cursor:pointer;text-decoration:underline}
.ar-kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:18px 0}
.ar-kpi{background:#fff;border:1px solid #E3E7EE;border-radius:14px;padding:14px 16px;box-shadow:0 7px 24px rgba(24,39,67,.055)}
.ar-kpi .v{font-family:var(--ff-m);font-size:21px;font-weight:700;margin:6px 0 2px}.ar-kpi .d{font-size:12px;color:var(--grey)}
.ar-kpi.bad .v{color:var(--red)}.ar-kpi.ok .v{color:var(--ok)}
.ar-card{background:#fff;border:1px solid #E3E7EE;border-radius:16px;padding:20px 22px;margin-bottom:16px;box-shadow:0 7px 24px rgba(24,39,67,.055)}
.ar-card-h{display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin-bottom:12px}
.ar-card-h h2{font-family:var(--ff-d);font-weight:700;font-size:21px;margin:0}.ar-card-h .sp{flex:1}
.ar-card-h p{margin:0;font-size:13px;color:var(--grey);flex-basis:100%}
table.ar-t{width:100%;border-collapse:collapse;font-size:13px}
table.ar-t th{font-family:var(--ff-m);font-size:9.5px;letter-spacing:.1em;color:var(--grey);text-align:left;font-weight:600;padding:8px 10px;border-bottom:1px solid var(--line);text-transform:uppercase}
table.ar-t td{padding:11px 10px;border-bottom:1px solid #EAE4D6;vertical-align:middle}
table.ar-t td.n{font-family:var(--ff-m);text-align:right;white-space:nowrap}
table.ar-t tr.row{cursor:pointer}table.ar-t tr.row:hover td{background:#FBFAF6}
table.ar-t tr.row td:first-child::before{content:"▸";display:inline-block;width:14px;color:var(--brass);font-size:11px}
table.ar-t tr.row.open td:first-child::before{content:"▾"}
.ar-var{font-family:var(--ff-m);font-weight:700}.ar-var.bad{color:var(--red)}.ar-var.ok{color:var(--ok)}.ar-var.mid{color:var(--brass2)}
.ar-bar{position:relative;height:6px;background:#EEE9DC;border-radius:3px;overflow:hidden;margin-top:6px;min-width:110px}
.ar-bar b{position:absolute;left:50%;top:-2px;bottom:-2px;width:1px;background:var(--grey)}
.ar-bar i{position:absolute;top:0;bottom:0;background:var(--brass)}.ar-bar i.bad{background:var(--red)}.ar-bar i.ok{background:var(--ok)}
tr.ar-read td{background:#FBFAF6;padding:14px 18px 18px 40px!important}
.ar-two{display:grid;grid-template-columns:1fr 1fr;gap:12px}
.ar-box{border-radius:10px;padding:12px 14px;font-size:12.8px;line-height:1.5}
.ar-box .ar-k{margin-bottom:5px}
.ar-box.benign{background:#F1F5F1;border-left:3px solid var(--ok)}.ar-box.concern{background:#F8ECE8;border-left:3px solid var(--red)}
.ar-ask{margin-top:12px;border:1px solid var(--line);border-radius:10px;padding:12px 14px;background:#fff;font-size:13px;line-height:1.5}
.ar-ask b{font-family:var(--ff-d);font-size:14px}
.ar-ask .doc{margin-top:6px;font-size:12px;color:var(--grey)}.ar-ask .doc em{font-style:normal;color:var(--brass2);font-weight:600}
.ar-cov{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}
.ar-cv{border:1px solid #E3E7EE;border-radius:14px;padding:14px 16px;background:#FBFAF6;display:flex;flex-direction:column;gap:8px}
.ar-cv.bad{border-color:#E0BDB3;background:#FDF5F2}.ar-cv.ok{background:#F5F9F5;border-color:#CADBCC}
.ar-cv .nm{font-family:var(--ff-d);font-weight:700;font-size:16px}.ar-cv .test{font-size:12px;color:var(--grey)}
.ar-cv .val{font-family:var(--ff-m);font-size:22px;font-weight:700}
.ar-cv .hist{display:flex;gap:6px;font-family:var(--ff-m);font-size:10.5px}
.ar-cv .hist span{flex:1;background:#fff;border:1px solid #E3E7EE;border-radius:6px;padding:5px 7px;text-align:center}
.ar-cv .hist span em{display:block;font-style:normal;font-size:8.5px;letter-spacing:.1em;color:var(--grey)}
.ar-cv .hist span.cur{border-color:var(--ink);font-weight:700}
.ar-head{height:6px;background:#E8E3D6;border-radius:3px;overflow:hidden}.ar-head i{display:block;height:100%;background:var(--ok)}.ar-cv.bad .ar-head i{background:var(--red)}
.ar-cv .note{font-size:12.3px;color:var(--ink2);line-height:1.45}
.ar-chk{width:100%;border-collapse:collapse;font-size:13px}.ar-chk td{padding:9px 6px;border-bottom:1px solid #EAE4D6;vertical-align:top}.ar-chk td:first-child{width:128px}
.ar-s{font-family:var(--ff-m);font-size:9.5px;letter-spacing:.08em;font-weight:700;padding:3px 8px;border-radius:5px;display:inline-block;white-space:nowrap}
.ar-s.ok{background:#E8F0E9;color:var(--ok)}.ar-s.bad{background:#F8E7E2;color:var(--red)}.ar-s.mid{background:#F4EAD3;color:var(--brass2)}
.ar-issues{margin:0;padding:0;list-style:none}.ar-issues li{display:flex;gap:12px;padding:10px 0;border-bottom:1px solid #EAE4D6;font-size:13px;line-height:1.5}
.ar-issues li .ar-chip{margin-top:2px}
.ar-drv{margin:0;padding-left:18px}.ar-drv li{margin:6px 0;font-size:13px;color:var(--ink2);line-height:1.5}
table.ar-t.agenda td{vertical-align:top}table.ar-t.agenda td.q{font-weight:600}table.ar-t.agenda td.why{color:var(--grey);font-size:12.5px}
.ar-foot{text-align:center;font-family:var(--ff-m);font-size:9px;letter-spacing:.08em;color:var(--grey);margin-top:26px}
@media(max-width:900px){.ar-kpis{grid-template-columns:1fr 1fr}.ar-cov{grid-template-columns:1fr}.ar-two{grid-template-columns:1fr}.ar-hero h1{font-size:26px}.ar-rating{margin-left:0;width:100%}.ar-top{flex-wrap:wrap;gap:8px}#ar-fab .t{display:none}#ar-fab{padding:12px 14px;bottom:60px}}
@media print{body.ar-open>*:not(#scr-review){display:none!important}#scr-review{position:static;overflow:visible}.ar-top,#ar-fab,.ar-noprint{display:none!important}.ar-card,.ar-kpi,.ar-cv{break-inside:avoid;box-shadow:none}#scr-review{background:#fff}tr.ar-read{display:table-row!important}}
</style>'''

SCREEN=r'''
<!-- ANNUAL REVIEW MODULE (additive) -->
<button type="button" id="ar-fab" aria-label="Open the annual review"><span class="dot"></span><span><span class="k">12 MONTHS LATER</span><span class="t">Annual review · FY2026 →</span></span></button>
<div id="scr-review" role="dialog" aria-label="Annual review">
  <div class="ar-top">
    <div><span class="mark">ERIDANT<em>◆</em></span> <span class="tag">EVIDENCE INTELLIGENCE</span></div>
    <span class="ar-pill gold">ANNUAL REVIEW · FY2026</span>
    <span class="ar-pill">REVIEW DATE · APR 15, 2027</span>
    <span class="sp"></span>
    <button type="button" class="ar-btn ghost ar-noprint" id="ar-print">Export ↗</button>
    <button type="button" class="ar-btn gold ar-noprint" id="ar-back">‹ Back to origination</button>
  </div>
  <div class="ar-wrap">
    <div id="ar-intro" class="ar-intro">
      <div class="ar-k">Credit approved · Aug 2026 · RLOC increased to $3.0M · equipment notes renewed</div>
      <div class="big">Twelve months later.</div>
      <div style="color:var(--grey);font-size:14px">FY2026 statements received April 9, 2027. Running the annual review against the terms set at approval.</div>
      <div class="stages" id="ar-stages">
        <div class="st"><span class="dot"></span><div><b>Retrieving approval terms</b><span>forecast underwritten Aug 2026 · 6 covenants · reporting conditions</span></div></div>
        <div class="st"><span class="dot"></span><div><b>Reading the FY2026 packet</b><span>comparative statements · A/R aging by customer · WIP summary · surety letter</span></div></div>
        <div class="st"><span class="dot"></span><div><b>Comparing forecast to actuals</b><span>10 metrics · variance read two ways · question for the borrower on each</span></div></div>
        <div class="st"><span class="dot"></span><div><b>Testing covenants &amp; conditions</b><span>financial · reporting · legal standing · other issues surfaced</span></div></div>
      </div>
      <div><button type="button" class="skip" id="ar-skip">SKIP</button></div>
    </div>
    <div id="ar-body" style="display:none"></div>
  </div>
</div>'''

JS=r'''
<script id="ar-js">
/* ============ ANNUAL REVIEW MODULE (additive) — deterministic, offline ============ */
(function(){
const q=s=>document.querySelector(s);
const M=v=>(v<0?"−":"")+"$"+Math.abs(v).toFixed(2)+"M";
const P=(a,f)=>(a-f)/Math.abs(f)*100;
const S=v=>(v>=0?"+":"−")+Math.abs(v).toFixed(1)+"%";

/* ---- Approval baseline (FY2025, from the origination packet) ---- */
const B={rev:38.60,gp:5.35,gm:13.9,ebitda:4.40,ni:3.23,cfo:-0.86,cash:0.83,ar:6.42,top:2.95,topPct:46,underbill:2.31,inv:1.94,debt:4.37,rloc:1.85,rlocLimit:2.00,interest:0.34,cpltd:0.40,dist:0.42,head:58,backlog:21.38};
/* ---- Forecast underwritten at approval (management projections adopted as the underwriting case, Aug 2026) ---- */
const F={rev:42.50,gm:13.5,gp:5.74,ebitda:4.85,ni:3.45,cfo:1.90,cash:1.60,ar:6.80,topPct:35,debt:3.90,dist:0.90,head:66,backlog:24.00};
/* ---- FY2026 actuals (annual review packet) ---- */
const A={rev:40.90,gp:4.05,gm:9.9,ebitda:2.36,ni:1.02,cfo:-0.47,cash:0.58,ar:8.75,top:4.64,topPct:53,top90:2.05,underbill:3.10,disputed:1.40,inv:2.20,debt:5.15,rloc:2.85,rlocLimit:3.00,notes:2.30,interest:0.44,cpltd:0.43,dist:0.66,head:52,backlog:16.90,rlocLow:2.10};

/* ---- Forecast vs actuals: variance read two ways + the question ---- */
const ROWS=[
 {m:"Revenue",f:F.rev,a:A.rev,fmt:M,bad:v=>v<0,
  benign:"Halcyon Waterfront Ph II milestones slipped into 2027; revenue is timing, not loss of work.",
  concern:"Backlog fell 21% and headcount fell to 52 while the forecast assumed 66. A shortfall against a shrinking backlog is capacity and pipeline, not timing.",
  ask:"Bridge FY2026 forecast to actual job by job — which contracts slipped, which were lost, and what replaced them?",doc:"WIP schedule (job-level) and backlog report by contract with expected start dates"},
 {m:"Gross margin",f:F.gm,a:A.gm,pts:true,bad:v=>v<0,
  benign:"A single cost overrun on one job, fully absorbed in FY2026, with the remaining book at plan margin.",
  concern:"FY2025 margin of 13.9% carried $1.10M of unapproved change orders in underbillings. A 4-pt fade with $1.40M of Halcyon change orders now disputed says the earlier margin was optimistic estimates being unwound.",
  ask:"Show original vs current estimated margin for every job over $2M — which jobs faded, when did the estimate change, and who approved the change-order billings?",doc:"WIP schedule with original vs current margin; Halcyon change-order log (submitted / approved / rejected)"},
 {m:"EBITDA",f:F.ebitda,a:A.ebitda,fmt:M,bad:v=>v<0,
  benign:"Non-recurring: the disputed change orders are a one-time write-down and FY2027 returns to plan.",
  concern:"EBITDA halved against forecast and fell 46% year over year. On the tax basis the FY2025 figure was already $3.10M, so FY2026 confirms the lower run-rate rather than interrupting a higher one.",
  ask:"Reconcile the $2.49M EBITDA shortfall by driver — volume, margin, overhead — and state how much is Halcyon.",doc:"EBITDA bridge FY2026 forecast → actual, by job and by cost category"},
 {m:"Net income",f:F.ni,a:A.ni,fmt:M,bad:v=>v<0,
  benign:"Follows EBITDA; no new fixed charges beyond the renewed notes.",
  concern:"Interest rose to $0.44M as the line stayed 95% drawn. Net margin 2.5% vs 8.4% in FY2025 — the FY2025 result now looks like the outlier.",
  ask:"Is any of the FY2026 shortfall reserved for claims or litigation with Halcyon — and if not, why not?",doc:"Notes to financial statements: contingencies; legal correspondence"},
 {m:"Operating cash flow",f:F.cfo,a:A.cfo,fmt:M,bad:v=>v<0,
  benign:"Working-capital build for 2027 billings; underbillings will convert once milestones are certified.",
  concern:"Second consecutive negative year while reporting positive earnings. Underbillings grew to $3.10M including $1.40M the customer disputes — earnings are being booked that may never convert to cash.",
  ask:"For every underbilled job: expected billing date, amount, and whether the owner has certified the work.",doc:"Underbilling schedule by job with certification status; 12-month monthly cash-flow forecast"},
 {m:"Unrestricted cash",f:F.cash,a:A.cash,fmt:M,bad:v=>v<0,
  benign:"Year-end trough; cash recovers in Q1 on retention releases.",
  concern:"Below the $0.75M covenant floor with the line 95% drawn — there is no liquidity cushion left if Halcyon does not pay.",
  ask:"Provide monthly cash and line balances for FY2026 and a 13-week cash forecast — where is the trough, and what funds it?",doc:"13-week cash forecast; monthly bank and line statements"},
 {m:"Top-customer concentration",f:F.topPct,a:A.topPct,pts:true,pctLabel:true,bad:v=>v>0,
  benign:"Halcyon is a large, creditworthy developer and the exposure is retention that releases at close-out.",
  concern:"$4.64M of $8.75M receivables with one counterparty, $2.05M past 90 days and tied to disputed change orders. The concentration the approval asked to reduce to 35% widened to 53%.",
  ask:"What is the status of the Halcyon dispute — amounts invoiced, amounts acknowledged, and have preliminary-notice and mechanics-lien rights been preserved on each project?",doc:"Halcyon aging by invoice; dispute correspondence; California preliminary notices and lien filings"},
 {m:"Interest-bearing debt",f:F.debt,a:A.debt,fmt:M,bad:v=>v>0,
  benign:"The increased line was used as intended — to carry receivables — and pays down as they collect.",
  concern:"Debt rose 32% against a forecast decline; the line never rested below $2.10M and equipment notes were renewed, not amortized. The business is borrowing to fund earnings it has not collected.",
  ask:"What did the additional $1.25M of borrowing fund — receivables, materials, or distributions — and what is the plan to term out or pay down?",doc:"Debt schedule; monthly line-usage report"},
 {m:"Shareholder distributions",f:F.dist,a:A.dist,fmt:M,bad:v=>v>0,ratio:true,
  benign:"Below the $0.90M forecast; sized to pass-through tax obligations.",
  concern:"65% of a net income that is itself 70% below forecast, taken in a year of negative operating cash flow — the distribution covenant (≤50%) is breached and cash left the business while the line funded operations.",
  ask:"Split FY2026 distributions between estimated tax and discretionary draws; what is the guarantor's current liquidity?",doc:"Guarantor PFS and 2026 Form 1040 (both outstanding)"},
 {m:"Headcount (year-end)",f:F.head,a:A.head,int:true,bad:v=>v<0,
  benign:"Deliberate shift to subcontracted labor on fixed-price work.",
  concern:"Third consecutive decline (74 → 58 → 52) while the plan needed 66 to deliver the forecast. Capacity is falling faster than revenue.",
  ask:"Which trades were lost, what is the sub-to-self-perform ratio now, and can the current crew deliver the $16.9M backlog on schedule?",doc:"Workers' comp payroll audit; backlog delivery schedule"}
];
function bar(v,badFn){const w=Math.min(Math.abs(v),100)/100*50, isBad=badFn(v);return `<div class="ar-bar"><b></b><i class="${isBad?'bad':'ok'}" style="${v>=0?'left:50%':'right:50%'};width:${w}%"></i></div>`;}
function renderFVA(){
  let h=`<table class="ar-t" id="ar-fva"><thead><tr><th>Metric</th><th style="text-align:right">Forecast (Aug 2026)</th><th style="text-align:right">Actual FY2026</th><th style="text-align:right">Variance</th><th style="text-align:right">FY2025 (at approval)</th></tr></thead><tbody>`;
  const b25={"Revenue":M(B.rev),"Gross margin":B.gm.toFixed(1)+"%","EBITDA":M(B.ebitda),"Net income":M(B.ni),"Operating cash flow":M(B.cfo),"Unrestricted cash":M(B.cash),"Top-customer concentration":B.topPct+"%","Interest-bearing debt":M(B.debt),"Shareholder distributions":M(B.dist),"Headcount (year-end)":String(B.head)};
  ROWS.forEach((r,i)=>{
    let fc,ac,v,vt;
    if(r.pts){fc=(r.pctLabel?"≤ ":"")+r.f.toFixed(r.pctLabel?0:1)+"%";ac=r.a.toFixed(r.pctLabel?0:1)+"%";v=r.a-r.f;vt=(v>=0?"+":"−")+Math.abs(v).toFixed(1)+" pts";}
    else if(r.int){fc=String(r.f);ac=String(r.a);v=P(r.a,r.f);vt=S(v);}
    else{fc=M(r.f);ac=M(r.a);v=(r.f===0)?(r.a>=0?100:-100):P(r.a,r.f);vt=S(v);}
    const isBad=r.bad(v);
    h+=`<tr class="row" data-i="${i}"><td><b>${r.m}</b></td><td class="n">${fc}</td><td class="n"><b>${ac}</b></td><td class="n"><span class="ar-var ${isBad?'bad':'ok'}">${vt}</span>${bar(r.pts?v*4:v,r.bad)}</td><td class="n" style="color:var(--grey)">${b25[r.m]}</td></tr>`;
    h+=`<tr class="ar-read" data-r="${i}" style="display:none"><td colspan="5">
      <div class="ar-two"><div class="ar-box benign"><div class="ar-k">Benign if…</div>${r.benign}</div><div class="ar-box concern"><div class="ar-k">Concerning because…</div>${r.concern}</div></div>
      <div class="ar-ask"><div class="ar-k">Put to the borrower</div><b>“${r.ask}”</b><div class="doc">Settles it: <em>${r.doc}</em></div></div></td></tr>`;
  });
  return h+`</tbody></table>`;
}

/* ---- Covenants set at approval (Aug 2026) ---- */
const dscr=(e,d,i,c)=>(e-d)/(i+c);
const COV=[
 {nm:"Leverage",test:"Total interest-bearing debt ÷ EBITDA",thr:"≤ 3.00×",v25:B.debt/B.ebitda,v26:A.debt/A.ebitda,fmt:x=>x.toFixed(2)+"×",pass:x=>x<=3,head:x=>1-x/3,
  note:"Passes — but moved from 0.99× to 2.18× in one year as debt rose and EBITDA halved. One more year on this trajectory breaches."},
 {nm:"Debt service coverage",test:"(EBITDA − distributions) ÷ (interest + scheduled principal)",thr:"≥ 1.25×",v25:dscr(B.ebitda,B.dist,B.interest,B.cpltd),v26:dscr(A.ebitda,A.dist,A.interest,A.cpltd),fmt:x=>x.toFixed(2)+"×",pass:x=>x>=1.25,head:x=>1-1.25/x,
  note:"Passes at 1.95× (from 5.38×). Distributions of $0.66M consumed the cushion; without them coverage would be 2.71×."},
 {nm:"Minimum liquidity",test:"Unrestricted cash at fiscal year-end",thr:"≥ $0.75M",v25:B.cash,v26:A.cash,fmt:M,pass:x=>x>=0.75,head:x=>x/0.75,
  note:"Breach — shortfall $0.17M with the line 95% drawn. The floor was set $0.08M below FY2025 cash; it has now been broken by 23%."},
 {nm:"Customer concentration",test:"Largest customer ÷ total receivables · step-down",thr:"≤ 35% at FYE26 → ≤ 25% at FYE27",v25:B.topPct,v26:A.topPct,fmt:x=>x.toFixed(0)+"%",pass:x=>x<=35,head:x=>35/x,
  note:"Breach — widened from 46% to 53% against an agreed step-down to 35%. $2.05M of the Halcyon balance is past 90 days and disputed."},
 {nm:"Operating cash flow",test:"Cash flow from operations, trailing twelve months",thr:"≥ $0 (tested from FY2026)",v25:B.cfo,v26:A.cfo,fmt:M,pass:x=>x>=0,head:x=>0,
  note:"Breach — FY2025’s negative CFO was accepted at approval as a one-time growth investment. FY2026 repeats it: earnings are not converting to cash.",pre:"waived"},
 {nm:"Distributions",test:"Shareholder distributions ÷ net income",thr:"≤ 50%",v25:B.dist/B.ni*100,v26:A.dist/A.ni*100,fmt:x=>x.toFixed(0)+"%",pass:x=>x<=50,head:x=>50/x,
  note:"Breach — 65% of net income distributed in a negative-cash-flow year. Cash left the business while the Bank’s line funded operations."}
];
function renderCov(){
  let h=`<div class="ar-cov">`;
  COV.forEach(c=>{
    const ok=c.pass(c.v26), st=ok?"ok":"bad";
    const pre25=c.pre==="waived"?`<span title="Waived at approval">${c.fmt(c.v25)} <small style="color:var(--grey)">waived</small></span>`:c.fmt(c.v25);
    h+=`<div class="ar-cv ${st}"><div style="display:flex;justify-content:space-between;align-items:center;gap:8px"><div class="nm">${c.nm}</div><span class="ar-chip ${ok?'ok':'bad'}">${ok?'IN COMPLIANCE':'BREACH'}</span></div>
      <div class="test">${c.test} · <b>${c.thr}</b></div><div class="val">${c.fmt(c.v26)}</div>
      <div class="hist"><span><em>FY25 · APPROVAL</em>${pre25}</span><span class="cur"><em>FY26 · REVIEW</em>${c.fmt(c.v26)}</span></div>
      <div class="ar-head" title="headroom"><i style="width:${Math.max(0,Math.min(1,c.head(c.v26)))*100}%"></i></div><div class="note">${c.note}</div></div>`;
  });
  return h+`</div>`;
}
const REP=[
 {s:"ok",t:"RECEIVED · DAY 99",n:"Annual financial statements within 120 days",d:"FY2026 statements dated Apr 9, 2027 — still company-prepared; CPA review was conditioned at approval and has not been delivered."},
 {s:"bad",t:"OUTSTANDING",n:"Guarantor PFS and Form 1040, annually",d:"Not received for 2026. Guarantor liquidity is untested while $0.66M was distributed."},
 {s:"mid",t:"Q4 LATE",n:"Customer-level receivables schedule, quarterly",d:"Q1–Q3 received on time; Q4 arrived with the statements, 40 days late — the quarter in which Halcyon aged past 90 days."},
 {s:"bad",t:"NOT ACHIEVED",n:"30-day annual line rest",d:"Line low point $2.10M (Feb 2027). The revolver is functioning as term debt."},
 {s:"ok",t:"CURRENT",n:"Certificates of insurance naming the Bank",d:"GL / auto / umbrella / workers’ comp current to Aug 2027."},
 {s:"ok",t:"RENEWED",n:"CSLB license, bond and workers’ comp",d:"License renewed to Mar 2028; no disciplinary actions."},
 {s:"ok",t:"FILED",n:"California Statement of Information",d:"Filed May 2026; next due May 2027 — confirm at the June interim."},
 {s:"mid",t:"CAPACITY CUT",n:"Surety letter",d:"Jan 2027 letter keeps aggregate capacity but reduces the single-job limit from $12M to $8M — the surety re-underwrote and tightened."}
];
function renderRep(){return `<table class="ar-chk"><tbody>${REP.map(r=>`<tr><td><span class="ar-s ${r.s}">${r.t}</span></td><td><b>${r.n}</b><div style="color:var(--grey);font-size:12px;margin-top:2px">${r.d}</div></td></tr>`).join("")}</tbody></table>`;}
const ISSUES=[
 {sev:"bad",t:"Lien-rights clock on the Halcyon dispute",d:"California mechanics-lien rights on a completed project expire 90 days after completion (30 days after a notice of completion). If Ph II reached completion in Q4 2026 the window may already be closing — the $2.05M disputed balance could become unsecured."},
 {sev:"bad",t:"Underbillings contain disputed change orders",d:"$1.40M of the $3.10M underbilled is Halcyon change orders the owner has rejected. It sits in current assets and in revenue; the Bank’s borrowing base, if formula-based, may be over-advanced."},
 {sev:"mid",t:"Surety single-job limit reduced",d:"A surety tightening while the bank widened is the free second underwrite pointing the other way. It also caps the size of replacement backlog."},
 {sev:"mid",t:"Books-to-tax gap not yet reconciled",d:"The 42% FY2025 EBITDA gap flagged at origination was never reconciled; FY2026 results land near the tax-basis run-rate, which makes the FY2025 books the anomaly."},
 {sev:"mid",t:"Revolver functioning as term debt",d:"No 30-day rest, 95% drawn at year-end, notes renewed rather than amortized — the structure no longer matches the use."}
];
function renderIssues(){return `<ul class="ar-issues">${ISSUES.map(i=>`<li><span class="ar-chip ${i.sev}">${i.sev==='bad'?'MATERIAL':'WATCH'}</span><div><b>${i.t}</b><div style="color:var(--ink2);font-size:12.6px;margin-top:2px">${i.d}</div></div></li>`).join("")}</ul>`;}
const AGENDA=[
 ["Status of the Halcyon change-order dispute: amounts invoiced, acknowledged, rejected; lien rights preserved on each project?","Concentration 53% · $2.05M past 90 days · CFO negative","Aging by invoice · dispute correspondence · preliminary notices & lien filings","CREDIT · BEFORE MEETING"],
 ["Job-level original vs current margin for every contract over $2M; who approved change-order billings?","Gross margin 13.5% → 9.9% · EBITDA −51% vs forecast","WIP schedule with margin history · change-order log","BORROWER · 10 DAYS"],
 ["For every underbilled job: expected billing date and owner certification status.","Underbillings $3.10M incl. $1.40M disputed · second negative CFO year","Underbilling schedule · 12-month cash-flow forecast","BORROWER · 10 DAYS"],
 ["Monthly cash and line balances FY2026; 13-week forecast — where is the trough and what funds it?","Cash $0.58M below the $0.75M floor · line 95% drawn · no 30-day rest","13-week cash forecast · bank and line statements","BORROWER · 10 DAYS"],
 ["What did the additional $1.25M of borrowing fund, and what is the plan to term out or pay down?","Debt +32% vs forecast decline · notes renewed not amortized","Debt schedule · line-usage report","BORROWER · 10 DAYS"],
 ["Split of distributions between pass-through tax and discretionary draws; guarantor liquidity today.","Distributions 65% of NI in a negative-cash year · PFS outstanding","Guarantor PFS · 2026 Form 1040","GUARANTOR · 30 DAYS"],
 ["Can the 52-person crew deliver the $16.9M backlog on schedule; which trades were lost?","Headcount 74 → 58 → 52 vs plan of 66 · backlog −21%","Workers’ comp payroll audit · backlog delivery schedule","BORROWER · 30 DAYS"],
 ["Why did the surety reduce the single-job limit, and does it constrain the 2027 pipeline?","Surety letter Jan 2027 · early-warning signal","Surety correspondence · updated capacity letter","RM · 30 DAYS"],
 ["Deliver the CPA-reviewed FY2026 statements and the book-to-tax reconciliation conditioned at approval.","Condition of approval not met · FY2025 gap unreconciled","CPA-reviewed statements · book-to-tax reconciliation","BORROWER · 60 DAYS"]
];
function renderAgenda(){return `<table class="ar-t agenda"><thead><tr><th>#</th><th>Question to the borrower</th><th>Why we are asking</th><th>What settles it</th><th>Owner · due</th></tr></thead><tbody>${AGENDA.map((a,i)=>`<tr><td class="n">${i+1}</td><td class="q">${a[0]}</td><td class="why">${a[1]}</td><td style="font-size:12.5px">${a[2]}</td><td class="n" style="font-size:10px;letter-spacing:.06em;color:var(--grey)">${a[3]}</td></tr>`).join("")}</tbody></table>`;}

function renderBody(){
  const nBad=COV.filter(c=>!c.pass(c.v26)).length, nOk=COV.length-nBad;
  const hit=ROWS.filter(r=>{const v=r.pts?(r.a-r.f):(r.int?P(r.a,r.f):P(r.a,r.f));return !r.bad(v);}).length;
  q("#ar-body").innerHTML=`
  <div class="ar-hero">
    <div><div class="ar-k">Annual review · approved Aug 2026 · S corporation · California · C3487215 · RLOC $3.0M + equipment notes $2.52M</div>
      <h1>Redwood Summit Construction, Inc.</h1>
      <div class="sub">FY2026 actuals against the forecast underwritten at approval, six financial covenants and eight conditions tested, and the other issues the year surfaced. Every variance is read two ways and ends in the question that would settle it.</div></div>
    <div class="ar-rating"><div><div class="lab">RATING AT APPROVAL</div><div class="r">4</div><div class="lab">SATISFACTORY</div></div><div class="arrow">→</div><div><div class="lab">RECOMMENDED</div><div class="r" style="color:#F2B8A8">6</div><div class="lab">SPECIAL MENTION</div></div><div style="margin-left:6px"><span class="ar-chip bad">DOWNGRADE</span></div></div>
  </div>
  <div class="ar-kpis">
    <div class="ar-kpi bad"><div class="ar-k">Covenant compliance</div><div class="v">${nOk} / ${COV.length}</div><div class="d">${nBad} in breach at FYE 2026 · none at approval</div></div>
    <div class="ar-kpi bad"><div class="ar-k">Forecast delivered</div><div class="v">${hit} / ${ROWS.length}</div><div class="d">metrics at or better than the approval forecast</div></div>
    <div class="ar-kpi bad"><div class="ar-k">Unrestricted cash</div><div class="v">${M(A.cash)}</div><div class="d">▼ 30% YoY · below the $0.75M floor · line 95% drawn</div></div>
    <div class="ar-kpi bad"><div class="ar-k">Top-customer exposure</div><div class="v">${A.topPct}%</div><div class="d">${M(A.top)} of ${M(A.ar)} · ${M(A.top90)} past 90 days, disputed</div></div>
  </div>
  <div class="ar-card"><div class="ar-card-h"><h2>Forecast vs actuals — FY2026</h2><span class="ar-k">Forecast = management projections adopted as the underwriting case, Aug 2026</span><span class="sp"></span><button type="button" class="ar-btn ar-noprint" id="ar-expand">Expand all readings</button><p>Click any metric for the two readings and the question to put to the borrower.</p></div>${renderFVA()}</div>
  <div class="ar-card"><div class="ar-card-h"><h2>Covenant tracking</h2><span class="ar-k">Set at approval · tested on FY2026 year-end statements</span><span class="sp"></span><span class="ar-chip soft">${nOk} IN COMPLIANCE · ${nBad} BREACHED</span></div>${renderCov()}</div>
  <div class="ar-two">
    <div class="ar-card"><div class="ar-card-h"><h2>Reporting &amp; legal conditions</h2><span class="sp"></span><span class="ar-chip mid">4 OPEN</span></div>${renderRep()}</div>
    <div class="ar-card"><div class="ar-card-h"><h2>Other issues surfaced</h2><span class="sp"></span><span class="ar-chip bad">2 MATERIAL</span></div>${renderIssues()}</div>
  </div>
  <div class="ar-card"><div class="ar-card-h"><h2>Rating recommendation</h2><span class="sp"></span><span class="ar-chip bad">4 → 6 · SPECIAL MENTION</span></div>
    <ul class="ar-drv">
      <li><b>Four of six financial covenants breached</b> — liquidity, concentration, operating cash flow and distributions — in the first year after approval.</li>
      <li><b>The concentration the approval asked to reduce was realized instead:</b> 53% of receivables with one customer, $2.05M past 90 days and disputed, with lien rights at risk.</li>
      <li><b>Second consecutive year of negative operating cash flow</b> with positive reported earnings — earnings quality, not volume, is the weakness.</li>
      <li><b>Leverage and coverage still pass</b>, which is why this is Special Mention rather than Substandard: repayment is not yet jeopardized, but the trend is one year from it.</li>
      <li><b>Path back to 5 — Watch:</b> Halcyon disputed balance collected or settled and cash restored above $0.75M by the June 2027 interim, with the CPA-reviewed statements delivered.</li>
    </ul>
  </div>
  <div class="ar-card"><div class="ar-card-h"><h2>Annual review meeting — questions &amp; requests</h2><span class="ar-k">Consolidated from every variance and breach above</span></div>${renderAgenda()}</div>
  <div class="ar-foot">DETERMINISTIC REVIEW · COMPUTED FROM THE APPROVAL TERMS AND THE FY2026 REVIEW PACKET · FOR ANALYST REVIEW ONLY · ALL ENTITIES AND FIGURES FICTIONAL — SPECIMEN</div>`;
  document.querySelectorAll("#ar-fva tr.row").forEach(tr=>tr.onclick=()=>{const rd=q(`#ar-fva tr.ar-read[data-r="${tr.dataset.i}"]`);const open=rd.style.display!=="none";rd.style.display=open?"none":"table-row";tr.classList.toggle("open",!open);});
  q("#ar-expand").onclick=()=>{const rows=[...document.querySelectorAll("#ar-fva tr.ar-read")];const anyClosed=rows.some(r=>r.style.display==="none");rows.forEach(r=>r.style.display=anyClosed?"table-row":"none");document.querySelectorAll("#ar-fva tr.row").forEach(t=>t.classList.toggle("open",anyClosed));q("#ar-expand").textContent=anyClosed?"Collapse all readings":"Expand all readings";};
}

/* ---- flow: FAB → time-jump → review ---- */
let timers=[], rendered=false;
function finishIntro(){timers.forEach(clearTimeout);timers=[];q("#ar-intro").style.display="none";if(!rendered){renderBody();rendered=true;}q("#ar-body").style.display="block";q("#scr-review").scrollTop=0;}
function openReview(){
  q("#scr-review").classList.add("open");document.body.classList.add("ar-open");document.body.style.overflow="hidden";q("#ar-fab").classList.remove("show");
  if(rendered){finishIntro();return;}
  q("#ar-intro").style.display="block";q("#ar-body").style.display="none";
  const st=[...document.querySelectorAll("#ar-stages .st")];st.forEach(s=>s.classList.remove("on","done"));
  st.forEach((s,i)=>{timers.push(setTimeout(()=>{s.classList.add("on");if(st[i-1])st[i-1].classList.add("done");},400+i*1100));});
  timers.push(setTimeout(()=>{st.forEach(s=>s.classList.add("done"));finishIntro();},400+st.length*1100+500));
}
function closeReview(){timers.forEach(clearTimeout);timers=[];q("#scr-review").classList.remove("open");document.body.classList.remove("ar-open");document.body.style.overflow="";syncFab();}
function syncFab(){const w=q("#scr-work"),f=q("#ar-fab");if(!w||!f)return;const vis=w.style.display&&w.style.display!=="none";f.classList.toggle("show",!!vis&&!q("#scr-review").classList.contains("open"));}
function init(){
  const w=q("#scr-work");if(!w)return;
  q("#ar-fab").onclick=openReview;q("#ar-back").onclick=closeReview;q("#ar-skip").onclick=finishIntro;q("#ar-print").onclick=()=>window.print();
  document.addEventListener("keydown",e=>{if(e.key==="Escape"&&q("#scr-review").classList.contains("open"))closeReview();});
  new MutationObserver(syncFab).observe(w,{attributes:true,attributeFilter:["style","class"]});syncFab();
  window.__annualReview={open:openReview,close:closeReview,skip:finishIntro};
}
if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",init);else init();
})();
</script>'''

def insert_once(s, anchor, addition, before=True, tag=""):
    assert s.count(anchor)==1, f"anchor {tag!r} count={s.count(anchor)}"
    return s.replace(anchor, (addition+anchor) if before else (anchor+addition))

out=src
out=insert_once(out,'</style></head>','',True,'style')  # sanity: anchor exists
out=out.replace('</style></head>','</style>'+CSS+'</head>',1)
out=insert_once(out,'<!-- EXPLAIN DRAWER -->',SCREEN+'\n\n',True,'drawer')
out=insert_once(out,'</body></html>',JS+'\n',True,'end')
open(DST,'w',encoding='utf8').write(out)

# ---- prove additivity: every original line survives, in order; only insertions ----
a=src.splitlines(); b=out.splitlines()
ops=difflib.SequenceMatcher(None,a,b,autojunk=False).get_opcodes()
kinds={o[0] for o in ops}
print('diff opcodes:',sorted(kinds),'| inserted lines:',sum(o[4]-o[3] for o in ops if o[0]=='insert'))
assert kinds<= {'equal','insert'}, "NON-ADDITIVE CHANGE DETECTED"
print('original lines preserved:',len(a),'→ output lines:',len(b))
