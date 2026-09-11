"""Small dependency-free training dashboard served by FastAPI."""

PAGE = r"""<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>一次障害対応Agent</title>
<style>
body{font-family:system-ui,-apple-system,sans-serif;margin:0;background:#f4f6f8;color:#18212a}
main{max-width:1100px;margin:28px auto;padding:0 18px}
h1{margin-bottom:4px}.sub{color:#5d6b78;margin-top:0}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:16px}
.card{background:#fff;border:1px solid #dfe5ea;border-radius:12px;padding:18px;box-shadow:0 1px 3px #0000000d}
.full{grid-column:1/-1}.badge{display:inline-block;padding:4px 9px;border-radius:999px;font-weight:700}
.ok{background:#dff5e7;color:#116b35}.ng{background:#fde4e1;color:#9b231a}.wait{background:#fff0c2;color:#7a5500}
pre{white-space:pre-wrap;background:#111820;color:#e8edf2;padding:14px;border-radius:8px;max-height:420px;overflow:auto}
button{border:0;border-radius:8px;padding:10px 16px;font-weight:700;cursor:pointer;margin-right:8px}
.approve{background:#16794a;color:white}.reject{background:#c73a31;color:white}
.small{font-size:.9rem;color:#61707d}.evidence li{margin:6px 0}
@media(max-width:800px){.grid{grid-template-columns:1fr}.full{grid-column:auto}}
</style>
</head>
<body><main>
<h1>一次障害対応Agent</h1>
<p class="sub">Observe → Decide → Act → Re-observe を可視化する研修用ダッシュボード</p>
<div class="grid">
<section class="card"><h2>System</h2><div id="health"></div><p class="small" id="incident"></p></section>
<section class="card"><h2>Human-in-the-loop</h2><div id="approval">承認待ちはありません。</div></section>
<section class="card full"><h2>Agent activity</h2><pre id="events">loading...</pre></section>
<section class="card full"><h2>Last report</h2><pre id="report">まだレポートはありません。</pre></section>
</div>
</main>
<script>
async function refresh(){
 const r=await fetch('/api/status'); const s=await r.json();
 const klass=s.healthy?'ok':'ng'; const label=s.healthy?'HEALTHY':'UNHEALTHY';
 document.getElementById('health').innerHTML=`<span class="badge ${klass}">${label}</span> HTTP ${s.last_http_status ?? '-'}`;
 document.getElementById('incident').textContent=s.active_incident_id?`Incident: ${s.active_incident_id}`:'Active incident: none';
 document.getElementById('events').textContent=s.events.map(e=>`${e.time}  ${e.level.padEnd(7)} ${e.message}`).join('\n') || 'No events';
 document.getElementById('report').textContent=s.last_report || 'まだレポートはありません。';
 const a=s.pending_approval;
 if(a){
   document.getElementById('approval').innerHTML=`<span class="badge wait">APPROVAL REQUIRED</span>
   <p><b>${a.action}</b> → ${a.target_service}</p><p>${a.root_cause}</p>
   <ul class="evidence">${a.evidence.map(x=>`<li>${x}</li>`).join('')}</ul>
   <button class="approve" onclick="approve(true)">承認</button><button class="reject" onclick="approve(false)">却下</button>`;
 } else document.getElementById('approval').textContent='承認待ちはありません。';
}
async function approve(value){
 await fetch('/api/approval',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({approved:value})});
 await refresh();
}
setInterval(refresh,2000); refresh();
</script>
</body></html>"""
