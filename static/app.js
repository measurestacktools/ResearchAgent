const $ = (id) => document.getElementById(id);
let sessionId = sessionStorage.getItem("ra_session") || ("s-" + Math.random().toString(36).slice(2));
sessionStorage.setItem("ra_session", sessionId);
let chatHistory = [];

function headers(extra = {}) {
  const h = { "Content-Type": "application/json", "X-Session-Id": sessionId, ...extra };
  const k = sessionStorage.getItem("ra_key");
  if (k) h["X-Groq-Key"] = k;
  return h;
}
function showErr(m) { const e = $("err"); e.hidden = false; e.textContent = m; }
function clearErr() { $("err").hidden = true; }
async function parseErr(r) {
  try { const j = await r.json(); return j.detail || JSON.stringify(j); }
  catch { return "Request failed (" + r.status + ")"; }
}

async function refreshStatus() {
  const pill = $("statusPill");
  try {
    const r = await fetch("/api/status", { headers: headers() });
    const j = await r.json();
    if (j.has_key) { pill.className = "pill ok"; pill.textContent = "● key OK · " + j.model; }
    else { pill.className = "pill bad"; pill.textContent = "○ no key — open Settings"; }
  } catch { pill.className = "pill bad"; pill.textContent = "○ status error"; }
}

async function refreshSources() {
  const r = await fetch("/api/sources", { headers: headers() });
  const j = await r.json();
  if (j.session_id) { sessionId = j.session_id; sessionStorage.setItem("ra_session", sessionId); }
  $("srcCount").textContent = j.count + " / " + j.max;
  const list = $("srcList"); list.innerHTML = "";
  const sel = $("srcSelect"); sel.innerHTML = "";
  (j.sources || []).forEach((s, i) => {
    const d = document.createElement("div");
    d.className = "src-item";
    d.innerHTML = "";
    const b = document.createElement("b"); b.textContent = (i + 1) + ". " + s.title + " (" + s.chars + " chars)";
    const p = document.createElement("div"); p.className = "prev"; p.textContent = s.preview + (s.chars > 300 ? "…" : "");
    const del = document.createElement("button"); del.className = "btn danger-ghost"; del.textContent = "Remove";
    del.onclick = async () => {
      await fetch("/api/sources/" + i, { method: "DELETE", headers: headers() });
      refreshSources();
    };
    d.appendChild(b); d.appendChild(p); d.appendChild(del);
    list.appendChild(d);
    const o = document.createElement("option"); o.value = i; o.textContent = (i + 1) + ". " + s.title;
    sel.appendChild(o);
  });
  if (!j.sources || !j.sources.length) list.innerHTML = '<span class="muted">No sources yet. Paste up to 6.</span>';
}

$("srcText").addEventListener("input", () => { $("charCount").textContent = $("srcText").value.length + " / 8000"; });

$("addSrcBtn").onclick = async () => {
  clearErr();
  const title = $("srcTitle").value.trim(), text = $("srcText").value.trim();
  if (!title) return showErr("Source title is required.");
  if (!text) return showErr("Source text is required (paste content).");
  if (text.length > 8000) return showErr("Source too large (max 8000 chars).");
  const r = await fetch("/api/sources", { method: "POST", headers: headers(), body: JSON.stringify({ title, text }) });
  if (!r.ok) return showErr(await parseErr(r));
  $("srcTitle").value = ""; $("srcText").value = ""; $("charCount").textContent = "0 / 8000";
  refreshSources();
};
$("clearSrcBtn").onclick = async () => { await fetch("/api/sources", { method: "DELETE", headers: headers() }); refreshSources(); };

async function runAnalyze(job, extra = {}) {
  clearErr();
  const body = { job, question: $("question").value.trim(), ...extra };
  const key = sessionStorage.getItem("ra_key"); if (key) body.key = key;
  const r = await fetch("/api/analyze", { method: "POST", headers: headers(), body: JSON.stringify(body) });
  if (!r.ok) throw new Error(await parseErr(r));
  return (await r.json()).result;
}

$("planBtn").onclick = async () => {
  clearErr();
  const q = $("question").value.trim();
  if (!q) return showErr("Research question is required.");
  $("planOut").textContent = "Generating plan…";
  try {
    const key = sessionStorage.getItem("ra_key");
    const r = await fetch("/api/plan", { method: "POST", headers: headers(), body: JSON.stringify({ question: q, key }) });
    if (!r.ok) throw new Error(await parseErr(r));
    $("planOut").textContent = (await r.json()).plan;
  } catch (e) { $("planOut").textContent = "Failed."; showErr(e.message); }
};

$("followupsBtn").onclick = async () => {
  try { $("planOut").textContent = await runAnalyze("followups"); }
  catch (e) { showErr(e.message); }
};

document.querySelectorAll("[data-job]").forEach((b) => {
  b.onclick = async () => {
    const job = b.dataset.job;
    $("analysisOut").textContent = "Running " + job + "…";
    try {
      const extra = {};
      if (job === "summarize" || job === "claims") {
        const v = $("srcSelect").value;
        if (v === "" || v == null) throw new Error("Add at least 1 source first, then pick it in the dropdown.");
        extra.source_index = parseInt(v, 10);
      }
      $("analysisOut").textContent = await runAnalyze(job, extra);
    } catch (e) { $("analysisOut").textContent = "Failed."; showErr(e.message); }
  };
});

$("askBtn").onclick = async () => {
  const q = $("askInput").value.trim();
  if (!q) return showErr("Type a question for free ask.");
  $("analysisOut").textContent = "Asking…";
  try {
    const res = await runAnalyze("ask", { query: q, history: chatHistory });
    chatHistory.push({ role: "user", content: q }, { role: "assistant", content: res });
    $("analysisOut").textContent = res;
    $("askInput").value = "";
  } catch (e) { $("analysisOut").textContent = "Failed."; showErr(e.message); }
};

$("reportBtn").onclick = async () => {
  try { $("reportOut").textContent = await runAnalyze("report"); }
  catch (e) { showErr(e.message); }
};
$("copyBtn").onclick = async () => {
  try { await navigator.clipboard.writeText($("reportOut").textContent); $("copyBtn").textContent = "✓ Copied"; setTimeout(() => $("copyBtn").textContent = "⧉ Copy", 1500); }
  catch { showErr("Copy failed — select the report text manually."); }
};
$("dlBtn").onclick = () => {
  const blob = new Blob([$("reportOut").textContent], { type: "text/markdown" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob); a.download = "research-report.md"; a.click();
  URL.revokeObjectURL(a.href);
};
$("resetBtn").onclick = async () => {
  await fetch("/api/sources", { method: "DELETE", headers: headers() });
  $("question").value = ""; $("planOut").textContent = "Your research plan will appear here.";
  $("analysisOut").textContent = "Analysis results appear here.";
  $("reportOut").textContent = "No report yet.";
  chatHistory = []; clearErr(); refreshSources();
};

// Settings modal
$("settingsBtn").onclick = () => { $("settingsModal").hidden = false; };
$("closeSettings").onclick = () => { $("settingsModal").hidden = true; };
$("verifyBtn").onclick = async () => {
  const k = $("keyInput").value.trim();
  if (!k) { $("keyMsg").textContent = "Paste a key first."; return; }
  $("keyMsg").textContent = "Verifying…";
  const r = await fetch("/api/settings/verify", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ key: k }) });
  if (r.ok) { sessionStorage.setItem("ra_key", k); $("keyMsg").textContent = "✓ Key verified (session only)."; refreshStatus(); }
  else { $("keyMsg").textContent = "✗ " + await parseErr(r); }
};
$("removeKeyBtn").onclick = () => { sessionStorage.removeItem("ra_key"); $("keyInput").value = ""; $("keyMsg").textContent = "Key removed from session."; refreshStatus(); };

refreshStatus(); refreshSources();
