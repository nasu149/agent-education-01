const nodes = [
  "investigate",
  "tools",
  "judge",
  "approval",
  "remediate",
  "verify",
  "report",
  "done",
];
const labels = {
  investigate: "investigate\nLLMが次の調査を判断",
  tools: "tools\nToolNodeで観測",
  judge: "judge\n原因と対処を構造化",
  approval: "approval\n人間承認",
  remediate: "remediate\n状態変更",
  verify: "verify\n再観測",
  report: "report\n結果整理",
  done: "END",
};

function esc(value) {
  return String(value ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
}
function renderFlow(s) {
  const visited = new Set((s.node_history || []).map((x) => x.node));
  const current = s.current_node;
  document.getElementById("flow").innerHTML = nodes
    .map((n, i) => {
      const classes = ["node"];
      if (visited.has(n)) classes.push("visited");
      if (current === n) classes.push("active");
      if (n === "done" && current === "done") classes.push("done");
      const box = `<div class="${classes.join(" ")}">${esc(labels[n]).replace(/\n/g, "<br>")}</div>`;
      return box + (i < nodes.length - 1 ? '<span class="arrow">→</span>' : "");
    })
    .join("");
  const hist = (s.node_history || [])
    .map((x) => `${x.time} ${x.node}`)
    .join(" → ");
  document.getElementById("history").textContent = hist
    ? `Node history: ${hist}`
    : "Node history: -";
}
function renderState(st) {
  if (!st) {
    document.getElementById("state").textContent =
      "まだIncidentStateはありません。";
    document.getElementById("stateRaw").textContent = "{}";
    return;
  }
  const diagnosis = st.diagnosis;
  const verification = st.verification;
  const messages = st.messages || [];
  let html = `<div class="state-grid">
   <div class="kv"><div class="k">approval</div><div class="v">${esc(st.approval)}</div></div>
   <div class="kv"><div class="k">messages_count</div><div class="v">${esc(st.messages_count)}</div></div>
   <div class="kv"><div class="k">investigation_tool_results</div><div class="v">${esc(st.investigation_tool_results)}</div></div>
   <div class="kv"><div class="k">verify_attempts</div><div class="v">${esc(st.verify_attempts)}</div></div>
 </div>`;
  html += `<div class="section-title">incident</div><div class="diagnosis">${esc(st.incident || "-")}</div>`;
  if (diagnosis) {
    html += `<div class="section-title">diagnosis</div><div class="diagnosis">
     <b>root_cause:</b> ${esc(diagnosis.root_cause)}<br>
     <b>recommended_action:</b> ${esc(diagnosis.recommended_action)} → ${esc(diagnosis.target_service)}${diagnosis.target_application && diagnosis.target_application !== "none" ? ` / ${esc(diagnosis.target_application)}` : ""}<br>
     <b>confidence:</b> ${esc(diagnosis.confidence)}<br>
     <b>evidence:</b><ul>${(diagnosis.evidence || []).map((x) => `<li>${esc(x)}</li>`).join("")}</ul>
   </div>`;
  }
  if (verification) {
    html += `<div class="section-title">verification</div><div class="diagnosis"><b>success:</b> ${esc(verification.success)}</div>`;
  }
  html += `<div class="section-title">messages（直近${messages.length}件）</div>`;
  html += messages.length
    ? messages
        .map(
          (m) =>
            `<div class="message"><div class="mtype">${esc(m.type)}${m.name ? ` / ${esc(m.name)}` : ""}${m.tool_calls ? ` → tool_calls: ${esc(m.tool_calls.join(", "))}` : ""}</div><div class="mcontent">${esc(m.content)}</div></div>`,
        )
        .join("")
    : '<div class="small">まだmessagesはありません。</div>';
  if (st.report) {
    html += `<div class="section-title">report</div><div class="diagnosis">${esc(st.report).replace(/\n/g, "<br>")}</div>`;
  }
  document.getElementById("state").innerHTML = html;
  document.getElementById("stateRaw").textContent = JSON.stringify(st, null, 2);
}
async function refresh() {
  const r = await fetch("/api/status");
  const s = await r.json();
  const klass = s.healthy ? "ok" : "ng";
  const label = s.healthy ? "HEALTHY" : "UNHEALTHY";
  document.getElementById("health").innerHTML =
    `<span class="badge ${klass}">${label}</span> HTTP ${s.last_http_status ?? "-"}`;
  document.getElementById("incident").textContent = s.active_incident_id
    ? `Incident: ${s.active_incident_id} / current node: ${s.current_node}`
    : `Active incident: none / last node: ${s.current_node}`;
  renderFlow(s);
  renderState(s.current_state);
  document.getElementById("events").textContent =
    s.events
      .map((e) => `${e.time}  ${e.level.padEnd(7)} ${e.message}`)
      .join("\n") || "No events";
  document.getElementById("report").textContent =
    s.last_report || "まだレポートはありません。";
  const a = s.pending_approval;
  if (a) {
    document.getElementById("approval").innerHTML =
      `<span class="badge wait">APPROVAL REQUIRED</span>
   <p><b>${esc(a.action)}</b> → ${esc(a.target_service)}${a.target_application && a.target_application !== "none" ? ` / ${esc(a.target_application)}` : ""}</p><p>${esc(a.root_cause)}</p>
   <ul class="evidence">${a.evidence.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>
   <button class="approve" onclick="approve(true)">承認</button><button class="reject" onclick="approve(false)">却下</button>`;
  } else
    document.getElementById("approval").textContent = "承認待ちはありません。";
}
async function approve(value) {
  await fetch("/api/approval", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ approved: value }),
  });
  await refresh();
}
setInterval(refresh, 1500);
refresh();
