"""Agent の監視・調査・承認・報告を可視化する、研修用ダッシュボード。

PAGE に HTML・CSS・JavaScript をまとめ、api.py から配信する。
別のフロントエンド用フレームワークは使わず、ブラウザーから状態取得 API を呼び出して
画面を更新する。承認・却下のボタンは人間の判断を API に送り、Graph の再開につなぐ。
"""

PAGE = r"""<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>一次障害対応Agent</title>
<style>
body{font-family:system-ui,-apple-system,sans-serif;margin:0;background:#f4f6f8;color:#18212a}
main{max-width:1250px;margin:28px auto;padding:0 18px}
h1{margin-bottom:4px}.sub{color:#5d6b78;margin-top:0}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:16px}
.card{background:#fff;border:1px solid #dfe5ea;border-radius:12px;padding:18px;box-shadow:0 1px 3px #0000000d}
.full{grid-column:1/-1}.badge{display:inline-block;padding:4px 9px;border-radius:999px;font-weight:700}
.ok{background:#dff5e7;color:#116b35}.ng{background:#fde4e1;color:#9b231a}.wait{background:#fff0c2;color:#7a5500}.info{background:#e7eefc;color:#284b8f}
pre{white-space:pre-wrap;background:#111820;color:#e8edf2;padding:14px;border-radius:8px;max-height:420px;overflow:auto}
button{border:0;border-radius:8px;padding:10px 16px;font-weight:700;cursor:pointer;margin-right:8px}
.approve{background:#16794a;color:white}.reject{background:#c73a31;color:white}
.small{font-size:.9rem;color:#61707d}.evidence li{margin:6px 0}
.flow{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin:10px 0 4px}
.node{padding:8px 11px;border-radius:9px;border:1px solid #cfd8df;background:#f7f9fb;font-size:.9rem;font-weight:700;color:#52616d}
.node.visited{background:#edf4ff;border-color:#9bb9e8;color:#28538c}
.node.active{background:#fff0c2;border:2px solid #d6a20b;color:#6c5000;box-shadow:0 0 0 3px #fff8dc}
.node.done{background:#dff5e7;border-color:#75ba90;color:#116b35}
.arrow{color:#98a5af;font-weight:700}
.state-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin:12px 0}
.kv{background:#f7f9fb;border:1px solid #e1e7ec;border-radius:9px;padding:10px}
.kv .k{font-size:.78rem;color:#697985;text-transform:uppercase;letter-spacing:.04em}.kv .v{font-weight:700;margin-top:4px;word-break:break-word}
.section-title{font-weight:800;margin:18px 0 7px}.diagnosis{background:#f7f9fb;border-left:4px solid #597fb5;padding:12px 14px;border-radius:6px}
.message{border:1px solid #e1e7ec;border-radius:8px;padding:10px;margin:7px 0;background:#fafbfc}.message .mtype{font-weight:800;color:#355a86}.message .mcontent{font-family:ui-monospace,SFMono-Regular,Consolas,monospace;font-size:.84rem;white-space:pre-wrap;margin-top:5px;max-height:150px;overflow:auto}
.history{font-family:ui-monospace,SFMono-Regular,Consolas,monospace;font-size:.86rem;color:#4f5f6b}
details{margin-top:14px}summary{cursor:pointer;font-weight:700;color:#40566b}
@media(max-width:900px){.grid{grid-template-columns:1fr}.full{grid-column:auto}.state-grid{grid-template-columns:1fr 1fr}}
</style>
</head>
<body><main>
<h1>一次障害対応Agent</h1>
<p class="sub">Observe → Decide → Act → Re-observe と LangGraph State の変化を可視化する研修用ダッシュボード</p>
<div class="grid">
<section class="card"><h2>System</h2><div id="health"></div><p class="small" id="incident"></p></section>
<section class="card"><h2>Human-in-the-loop</h2><div id="approval">承認待ちはありません。</div></section>

<section class="card full">
  <h2>LangGraph workflow</h2>
  <p class="small">黄色が現在のNode、青が通過済みです。investigate ↔ tools は必要な情報が集まるまでループします。</p>
  <div class="flow" id="flow"></div>
  <div class="history" id="history"></div>
</section>

<section class="card full">
  <h2>IncidentState</h2>
  <p class="small">Node間で引き継がれる共有Stateです。messagesはブラウザ表示用に直近8件・短縮表示しています。</p>
  <div id="state">まだIncidentStateはありません。</div>
  <details><summary>State snapshot をJSONで見る</summary><pre id="stateRaw">{}</pre></details>
</section>

<section class="card full"><h2>Agent activity</h2><pre id="events">loading...</pre></section>
<section class="card full"><h2>Last report</h2><pre id="report">まだレポートはありません。</pre></section>
</div>
</main>
<script>
const nodes=['investigate','tools','judge','approval','remediate','verify','report','done'];
const labels={investigate:'investigate\nLLMが次の調査を判断',tools:'tools\nToolNodeで観測',judge:'judge\n原因と対処を構造化',approval:'approval\n人間承認',remediate:'remediate\n状態変更',verify:'verify\n再観測',report:'report\n結果整理',done:'END'};

function esc(value){
 return String(value ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}
function renderFlow(s){
 const visited=new Set((s.node_history||[]).map(x=>x.node));
 const current=s.current_node;
 document.getElementById('flow').innerHTML=nodes.map((n,i)=>{
   const classes=['node'];
   if(visited.has(n)) classes.push('visited');
   if(current===n) classes.push('active');
   if(n==='done' && current==='done') classes.push('done');
   const box=`<div class="${classes.join(' ')}">${esc(labels[n]).replace(/\n/g,'<br>')}</div>`;
   return box+(i<nodes.length-1?'<span class="arrow">→</span>':'');
 }).join('');
 const hist=(s.node_history||[]).map(x=>`${x.time} ${x.node}`).join(' → ');
 document.getElementById('history').textContent=hist?`Node history: ${hist}`:'Node history: -';
}
function renderState(st){
 if(!st){
   document.getElementById('state').textContent='まだIncidentStateはありません。';
   document.getElementById('stateRaw').textContent='{}';
   return;
 }
 const diagnosis=st.diagnosis;
 const verification=st.verification;
 const messages=st.messages||[];
 let html=`<div class="state-grid">
   <div class="kv"><div class="k">approval</div><div class="v">${esc(st.approval)}</div></div>
   <div class="kv"><div class="k">messages_count</div><div class="v">${esc(st.messages_count)}</div></div>
   <div class="kv"><div class="k">investigation_tool_results</div><div class="v">${esc(st.investigation_tool_results)}</div></div>
   <div class="kv"><div class="k">verify_attempts</div><div class="v">${esc(st.verify_attempts)}</div></div>
 </div>`;
 html+=`<div class="section-title">incident</div><div class="diagnosis">${esc(st.incident||'-')}</div>`;
 if(diagnosis){
   html+=`<div class="section-title">diagnosis</div><div class="diagnosis">
     <b>root_cause:</b> ${esc(diagnosis.root_cause)}<br>
     <b>recommended_action:</b> ${esc(diagnosis.recommended_action)} → ${esc(diagnosis.target_service)}${diagnosis.target_application && diagnosis.target_application!=='none'?` / ${esc(diagnosis.target_application)}`:''}<br>
     <b>confidence:</b> ${esc(diagnosis.confidence)}<br>
     <b>evidence:</b><ul>${(diagnosis.evidence||[]).map(x=>`<li>${esc(x)}</li>`).join('')}</ul>
   </div>`;
 }
 if(verification){
   html+=`<div class="section-title">verification</div><div class="diagnosis"><b>success:</b> ${esc(verification.success)}</div>`;
 }
 html+=`<div class="section-title">messages（直近${messages.length}件）</div>`;
 html+=messages.length?messages.map(m=>`<div class="message"><div class="mtype">${esc(m.type)}${m.name?` / ${esc(m.name)}`:''}${m.tool_calls?` → tool_calls: ${esc(m.tool_calls.join(', '))}`:''}</div><div class="mcontent">${esc(m.content)}</div></div>`).join(''):'<div class="small">まだmessagesはありません。</div>';
 if(st.report){html+=`<div class="section-title">report</div><div class="diagnosis">${esc(st.report).replace(/\n/g,'<br>')}</div>`;}
 document.getElementById('state').innerHTML=html;
 document.getElementById('stateRaw').textContent=JSON.stringify(st,null,2);
}
async function refresh(){
 const r=await fetch('/api/status'); const s=await r.json();
 const klass=s.healthy?'ok':'ng'; const label=s.healthy?'HEALTHY':'UNHEALTHY';
 document.getElementById('health').innerHTML=`<span class="badge ${klass}">${label}</span> HTTP ${s.last_http_status ?? '-'}`;
 document.getElementById('incident').textContent=s.active_incident_id?`Incident: ${s.active_incident_id} / current node: ${s.current_node}`:`Active incident: none / last node: ${s.current_node}`;
 renderFlow(s); renderState(s.current_state);
 document.getElementById('events').textContent=s.events.map(e=>`${e.time}  ${e.level.padEnd(7)} ${e.message}`).join('\n') || 'No events';
 document.getElementById('report').textContent=s.last_report || 'まだレポートはありません。';
 const a=s.pending_approval;
 if(a){
   document.getElementById('approval').innerHTML=`<span class="badge wait">APPROVAL REQUIRED</span>
   <p><b>${esc(a.action)}</b> → ${esc(a.target_service)}${a.target_application && a.target_application!=='none'?` / ${esc(a.target_application)}`:''}</p><p>${esc(a.root_cause)}</p>
   <ul class="evidence">${a.evidence.map(x=>`<li>${esc(x)}</li>`).join('')}</ul>
   <button class="approve" onclick="approve(true)">承認</button><button class="reject" onclick="approve(false)">却下</button>`;
 } else document.getElementById('approval').textContent='承認待ちはありません。';
}
async function approve(value){
 await fetch('/api/approval',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({approved:value})});
 await refresh();
}
setInterval(refresh,1500); refresh();
</script>
</body></html>"""
