/* JARVIS · Decision Pipeline
 * Modlar: LIVE (/ws/decisions) · REPLAY (/api/decisions, 0.5x-4x) · DEMO (sahte ama gercekci).
 * URL: ?mode=live|replay|demo&speed=0.5|1|2|4   Klavye: 1/2/3 mod, +/- hiz, bosluk duraklat.
 * Bagimlilik yok; file:// ile acilirsa DEMO calisir.
 */
(() => {
  "use strict";

  // ------------------------------------------------------------------ sabitler
  const W0 = 1920, H0 = 1080;
  const TASKS = ["sohbet", "kod", "arastirma", "yazi", "planlama", "gorsel", "sistem_komutu", "okul", "iletisim", "qa"];
  const TASK_TITLE = {
    sohbet: "CHAT", kod: "CODE REQUEST", arastirma: "RESEARCH QUERY", yazi: "WRITING TASK",
    planlama: "PLANNING", gorsel: "VISION INPUT", sistem_komutu: "SYSTEM COMMAND", okul: "SCHOOL TASK",
    iletisim: "EMAIL TRIAGE", qa: "QA REVIEW",
  };
  const TASK_SHORT = {
    sohbet: "CHAT", kod: "CODE", arastirma: "RESEARCH", yazi: "WRITING", planlama: "PLANNING",
    gorsel: "VISION", sistem_komutu: "SYSTEM", okul: "SCHOOL", iletisim: "EMAIL / COMMS", qa: "QA",
  };
  const TASK_COLOR = {
    sohbet: "#8b7bff", kod: "#00e5ff", arastirma: "#3dff9a", yazi: "#ffd166", planlama: "#ff9f43",
    gorsel: "#ff2fd1", sistem_komutu: "#4db8ff", okul: "#7cffcb", iletisim: "#ff6b9a", qa: "#ffffff",
  };
  const RULES = [
    { id: "qa", label: "QA · STRONGEST" }, { id: "explicit_model", label: "EXPLICIT MODEL" },
    { id: "image_attachment", label: "IMAGE ATTACHED" }, { id: "long_context", label: "LONG CONTEXT" },
    { id: "none", label: "NO MATCH" },
  ];
  const GATES = [
    { id: "pass", label: "PASS ≥ THRESHOLD" }, { id: "llm", label: "LLM · DIFFICULTY" },
    { id: "conductor", label: "CONDUCTOR · AGENT" }, { id: "rule", label: "RULE BYPASS" },
  ];
  const DEFAULT_MODELS = [
    { id: "gemini-flash-lite-latest", provider: "gemini", cost: "free", active: true },
    { id: "gemini-3.5-flash-lite", provider: "gemini", cost: "free", active: true },
    { id: "gemini-3.5-flash", provider: "gemini", cost: "free", active: true },
    { id: "gemini-3.6-flash", provider: "gemini", cost: "free", active: true },
    { id: "nvidia/nemotron-3.5-super-vl:free", provider: "openrouter", cost: "free", active: true },
    { id: "poolside/laguna-s-2.1:free", provider: "openrouter", cost: "free", active: true },
    { id: "nvidia/nemotron-3-ultra-550b-a55b:free", provider: "openrouter", cost: "free", active: true },
    { id: "cohere/north-mini-code:free", provider: "openrouter", cost: "free", active: true },
    { id: "claude-opus-5-5", provider: "claude", cost: "paid", active: true, price: { input: 4, output: 20 } },
  ];

  // ------------------------------------------------------------------ durum
  const $ = (s) => document.querySelector(s);
  const params = new URLSearchParams(location.search);
  const HTTP = location.protocol.startsWith("http");
  const S = {
    mode: null, speed: 1, paused: false,
    info: { version: "router", thresholds: { task: 0.75, difficulty: 0.6, agent: 0.75 }, models: DEFAULT_MODELS },
    sim: 0,                       // hiz ve duraklatmaya bagli sahne saati (ms)
    cases: 0, totalCases: 0, counts: { local: 0, llm: 0, rule: 0 },
    lat: [], cost: 0, paid: 0, free: 0,
    taskMix: {}, modelMix: {}, fallbacks: 0,
    byId: {},                     // request_id -> karar
    paths: [], sparks: [], marks: [],
    ws: null, wsTry: 0, timer: null, gen: 0,
  };

  // ------------------------------------------------------------------ olcekleme
  const stage = $("#stage");
  let scale = 1;
  function fit() {
    scale = Math.min(innerWidth / W0, innerHeight / H0);
    const x = (innerWidth - W0 * scale) / 2, y = (innerHeight - H0 * scale) / 2;
    stage.style.transform = `translate(${x}px, ${y}px) scale(${scale})`;
    sizeCanvas();
  }

  const canvas = $("#scene"), ctx = canvas.getContext("2d");
  let CW = 1876, CH = 476, ratio = 1;
  function sizeCanvas() {
    const box = canvas.parentElement;
    CW = box.clientWidth; CH = box.clientHeight;
    ratio = Math.max(0.75, Math.min(2, (devicePixelRatio || 1) * scale));
    canvas.width = Math.round(CW * ratio); canvas.height = Math.round(CH * ratio);
    layout();
  }

  // ------------------------------------------------------------------ sahne yerlesimi
  const COLS = [
    { key: "request", title: "REQUEST", fx: 0.148 },
    { key: "rules", title: "RULES", fx: 0.31 },
    { key: "classifier", title: "CLASSIFIER", fx: 0.49 },
    { key: "gate", title: "GATE", fx: 0.665 },
    { key: "model", title: "MODEL", fx: 0.815 },
  ];
  let nodes = {};   // "col:id" -> {x,y,label,col,heat,color,count}
  function columnItems(key) {
    if (key === "rules") return RULES;
    if (key === "classifier") return TASKS.map((t) => ({ id: t, label: TASK_SHORT[t] }));
    if (key === "gate") return GATES;
    if (key === "model") return modelList().map((m) => ({ id: m.id, label: shortModel(m.id), model: m }));
    return [{ id: "in", label: "" }];
  }
  function layout() {
    const old = nodes; nodes = {};
    const top = 64, bottom = CH - 22;
    for (const col of COLS) {
      const items = columnItems(col.key), x = Math.round(CW * col.fx);
      items.forEach((it, i) => {
        const y = col.key === "request" ? CH / 2
          : items.length === 1 ? (top + bottom) / 2
          : top + (bottom - top) * (i / (items.length - 1));
        const k = `${col.key}:${it.id}`, prev = old[k] || {};
        nodes[k] = { x, y, label: it.label, col: col.key, id: it.id, model: it.model,
          heat: prev.heat || 0, color: prev.color || "#00e5ff", count: prev.count || 0, ok: prev.ok };
      });
    }
    S.paths.forEach(buildPath);
  }
  function modelList() {
    return (S.info.models || DEFAULT_MODELS).filter((m) => m.routable !== false);
  }
  function shortModel(id) {
    return String(id).replace(/^.*\//, "").replace(/:free$/, "").replace(/-a55b|-a12b/, "");
  }

  // ------------------------------------------------------------------ yollar
  function ensureModelNode(id) {
    if (!id || nodes[`model:${id}`]) return;
    S.info.models = [...modelList(), { id, provider: "?", cost: "free", active: true }];
    layout();
  }
  function bezier(a, b, steps, out) {
    const dx = (b.x - a.x) * 0.5;
    for (let i = 1; i <= steps; i++) {
      const t = i / steps, u = 1 - t;
      out.push({
        x: u * u * u * a.x + 3 * u * u * t * (a.x + dx) + 3 * u * t * t * (b.x - dx) + t * t * t * b.x,
        y: u * u * u * a.y + 3 * u * u * t * a.y + 3 * u * t * t * b.y + t * t * t * b.y,
      });
    }
  }
  function buildPath(p) {
    const keys = p.keys.filter((k) => nodes[k]);
    if (keys.length < 2) { p.pts = []; return; }
    const pts = [{ x: nodes[keys[0]].x, y: nodes[keys[0]].y }], marks = [0];
    for (let i = 1; i < keys.length; i++) {
      const a = nodes[keys[i - 1]], b = nodes[keys[i]];
      if (p.arc) {   // yedek gecisi: sag tarafa bombeli yay
        const steps = 40, bulge = 90;
        for (let s = 1; s <= steps; s++) {
          const t = s / steps;
          pts.push({ x: a.x + (b.x - a.x) * t + Math.sin(Math.PI * t) * bulge, y: a.y + (b.y - a.y) * t });
        }
      } else bezier(a, b, 46, pts);
      marks.push(pts.length - 1);
    }
    let len = 0; const acc = [0];
    for (let i = 1; i < pts.length; i++) { len += Math.hypot(pts[i].x - pts[i - 1].x, pts[i].y - pts[i - 1].y); acc.push(len); }
    p.pts = pts; p.acc = acc; p.len = len; p.marks = marks.map((m) => acc[m] / (len || 1));
  }
  function addPath(keys, color, opts = {}) {
    const p = { keys, color, born: S.sim, dur: opts.dur || 1700, arc: !!opts.arc, dashed: !!opts.dashed,
      label: opts.label || "", hit: 0, onHit: opts.onHit || null, width: opts.width || 2.4 };
    buildPath(p);
    S.paths.push(p);
    if (S.paths.length > 36) S.paths.splice(0, S.paths.length - 36);
    return p;
  }
  function spark(x, y, color, n = 14) {
    for (let i = 0; i < n; i++) {
      const a = Math.random() * Math.PI * 2, v = 0.04 + Math.random() * 0.16;
      S.sparks.push({ x, y, vx: Math.cos(a) * v, vy: Math.sin(a) * v, life: 1, color });
    }
  }

  // ------------------------------------------------------------------ cizim
  function rgba(hex, a) {
    const h = hex.replace("#", ""), n = parseInt(h.length === 3 ? h.split("").map((c) => c + c).join("") : h, 16);
    return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`;
  }
  function draw() {
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    ctx.clearRect(0, 0, CW, CH);

    // sutun basliklari + kilavuz cizgiler
    ctx.font = "600 12px " + getComputedStyle(document.body).fontFamily;
    ctx.textBaseline = "middle";
    COLS.forEach((c, i) => {
      const x = Math.round(CW * c.fx);
      if (i > 0) {
        const g = ctx.createLinearGradient(0, 40, 0, CH);
        g.addColorStop(0, "rgba(0,229,255,0.18)"); g.addColorStop(1, "rgba(0,229,255,0)");
        ctx.strokeStyle = g; ctx.lineWidth = 1; ctx.beginPath(); ctx.moveTo(x, 44); ctx.lineTo(x, CH - 10); ctx.stroke();
      }
      ctx.fillStyle = "rgba(95,120,148,0.95)"; ctx.textAlign = "center";
      ctx.fillText(`${String(i + 1).padStart(2, "0")} · ${c.title}`, i === 0 ? 150 : x, 24);
    });

    // eski yollar (sonen izler) once, aktif yollar ustte
    ctx.globalCompositeOperation = "lighter";
    for (const p of S.paths) drawPath(p);
    ctx.globalCompositeOperation = "source-over";

    // dugumler
    for (const k in nodes) drawNode(nodes[k]);

    // isaretler (BLOCKED, FALLBACK...)
    S.marks = S.marks.filter((m) => S.sim - m.born < 6000);
    for (const m of S.marks) {
      const n = nodes[m.key]; if (!n) continue;
      const a = Math.max(0, 1 - (S.sim - m.born) / 6000);
      ctx.fillStyle = rgba(m.color, a); ctx.font = "700 11px " + getComputedStyle(document.body).fontFamily;
      ctx.textAlign = "right"; ctx.fillText(m.text, n.x - 14, n.y - 13);
    }

    // kivilcimlar
    ctx.globalCompositeOperation = "lighter";
    S.sparks = S.sparks.filter((s) => s.life > 0);
    for (const s of S.sparks) {
      ctx.fillStyle = rgba(s.color, s.life * 0.9);
      ctx.beginPath(); ctx.arc(s.x, s.y, 1.6 + s.life * 1.4, 0, Math.PI * 2); ctx.fill();
    }
    ctx.globalCompositeOperation = "source-over";
  }

  function drawPath(p) {
    if (!p.pts || p.pts.length < 2) return;
    const age = S.sim - p.born, prog = Math.min(1, age / p.dur);
    const fade = prog < 1 ? 1 : Math.exp(-(age - p.dur) / 14000);
    if (fade < 0.02) return;
    const headD = prog * p.len;
    let n = 1; while (n < p.pts.length && p.acc[n] <= headD) n++;
    const pts = p.pts.slice(0, n);
    if (prog < 1 && n < p.pts.length) {   // kafa iki ornek arasinda
      const a = p.pts[n - 1], b = p.pts[n], seg = p.acc[n] - p.acc[n - 1] || 1, t = (headD - p.acc[n - 1]) / seg;
      pts.push({ x: a.x + (b.x - a.x) * t, y: a.y + (b.y - a.y) * t });
    }
    if (pts.length < 2) return;
    ctx.setLineDash(p.dashed ? [7, 6] : []);
    ctx.lineCap = "round"; ctx.lineJoin = "round";
    const live = prog < 1 ? 1 : 0.28 + 0.72 * Math.exp(-(age - p.dur) / 1600);
    for (const [w, a] of [[p.width * 5, 0.07], [p.width * 2.2, 0.2], [p.width, 0.95]]) {
      ctx.strokeStyle = rgba(p.color, a * fade * live);
      ctx.lineWidth = w; ctx.beginPath(); ctx.moveTo(pts[0].x, pts[0].y);
      for (let i = 1; i < pts.length; i++) ctx.lineTo(pts[i].x, pts[i].y);
      ctx.stroke();
    }
    ctx.setLineDash([]);
    if (prog < 1) {   // parlayan kafa
      const h = pts[pts.length - 1], g = ctx.createRadialGradient(h.x, h.y, 0, h.x, h.y, 26);
      g.addColorStop(0, rgba("#ffffff", 0.95)); g.addColorStop(0.25, rgba(p.color, 0.8)); g.addColorStop(1, rgba(p.color, 0));
      ctx.fillStyle = g; ctx.beginPath(); ctx.arc(h.x, h.y, 26, 0, Math.PI * 2); ctx.fill();
      if (Math.random() < 0.5) S.sparks.push({ x: h.x, y: h.y, vx: (Math.random() - 0.5) * 0.05, vy: (Math.random() - 0.5) * 0.05, life: 0.7, color: p.color });
    }
    // dugume varis olaylari
    while (p.hit < p.marks.length && prog >= p.marks[p.hit] - 1e-6) {
      const key = p.keys[p.hit], node = nodes[key];
      if (node && !p.arc) { node.heat = 1; node.color = p.color; spark(node.x, node.y, p.color, p.hit === p.marks.length - 1 ? 26 : 10); }
      if (p.onHit) p.onHit(p.hit, key);
      p.hit++;
    }
    if (p.label && prog >= 1 && fade > 0.2) {
      const m = p.pts[Math.floor(p.pts.length / 2)];
      ctx.fillStyle = rgba(p.color, fade); ctx.font = "700 11px " + getComputedStyle(document.body).fontFamily;
      ctx.textAlign = "left"; ctx.fillText(p.label, m.x + 8, m.y);
    }
  }

  function drawNode(n) {
    if (n.col === "request") return;
    const font = getComputedStyle(document.body).fontFamily;
    const inactive = n.model && n.model.active === false, paid = n.model && n.model.cost === "paid";
    const base = inactive ? "#2a3a52" : paid ? "#ff2fd1" : "#00e5ff";
    if (n.heat > 0.02) {
      const r = 10 + (1 - n.heat) * 22, g = ctx.createRadialGradient(n.x, n.y, 0, n.x, n.y, r + 18);
      g.addColorStop(0, rgba(n.color, 0.55 * n.heat)); g.addColorStop(1, rgba(n.color, 0));
      ctx.fillStyle = g; ctx.beginPath(); ctx.arc(n.x, n.y, r + 18, 0, Math.PI * 2); ctx.fill();
      ctx.strokeStyle = rgba(n.color, 0.9 * n.heat); ctx.lineWidth = 1.5;
      ctx.beginPath(); ctx.arc(n.x, n.y, r, 0, Math.PI * 2); ctx.stroke();
    }
    ctx.fillStyle = "#04070f"; ctx.strokeStyle = rgba(n.heat > 0.05 ? n.color : base, 0.55 + n.heat * 0.45);
    ctx.lineWidth = 1.6; ctx.beginPath(); ctx.arc(n.x, n.y, 5.5, 0, Math.PI * 2); ctx.fill(); ctx.stroke();
    if (n.heat > 0.05) { ctx.fillStyle = rgba(n.color, n.heat); ctx.beginPath(); ctx.arc(n.x, n.y, 3, 0, Math.PI * 2); ctx.fill(); }

    ctx.font = `${n.heat > 0.3 ? 700 : 500} 12.5px ${font}`; ctx.textAlign = "left"; ctx.textBaseline = "middle";
    ctx.fillStyle = inactive ? "#2a3a52" : n.heat > 0.3 ? "#ffffff" : paid ? "rgba(255,47,209,0.85)" : "rgba(170,198,226,0.78)";
    let label = n.label;
    if (n.col === "model") {
      label += inactive ? "  · OFFLINE" : paid ? "  · $" : "";
    }
    ctx.fillText(label, n.x + 14, n.y);
    if (n.count) {
      const w = ctx.measureText(label).width;
      ctx.fillStyle = "rgba(95,120,148,0.9)"; ctx.font = `500 11px ${font}`;
      ctx.fillText(`×${n.count}`, n.x + 22 + w, n.y);
    }
    n.heat *= 0.985;
  }

  // ------------------------------------------------------------------ olay isleme
  function gateOf(d) {
    if (d.rule) return "rule";
    if (d.agent_source === "conductor_llm") return "conductor";
    if (d.source === "llm_fallback") return "llm";
    return "pass";
  }
  function isQa(d) { return String(d.request_id || "").endsWith("-qa") || d.rule === "qa"; }

  function ingest(ev) {
    if (!ev || !ev.kind) return;
    if (ev.kind === "decision") onDecision(ev);
    else if (ev.kind === "done") onDone(ev);
    else if (ev.kind === "qa") onQa(ev);
  }

  function onDecision(d) {
    const qa = isQa(d), task = d.task_type || "sohbet", color = TASK_COLOR[task] || "#00e5ff";
    ensureModelNode(d.model_id);
    S.byId[d.request_id] = d;
    if (!qa) {
      S.cases++;
      const kind = d.rule ? "rule" : (d.source === "llm_fallback" || d.agent_source === "conductor_llm") ? "llm" : "local";
      S.counts[kind]++;
      if (typeof d.latency_ms === "number") { S.lat.push(d.latency_ms); if (S.lat.length > 50) S.lat.shift(); }
      S.taskMix[task] = (S.taskMix[task] || 0) + 1;
    }
    showCase(d, qa, color);
    const keys = ["request:in", `rules:${d.rule || "none"}`, `classifier:${task}`, `gate:${gateOf(d)}`, `model:${d.model_id}`];
    const stagesAt = ["request", "rules", "classifier", "gate", "model"];
    resetPills(d);
    const card = $("#request-card");
    card.classList.add("pulse"); setTimeout(() => card.classList.remove("pulse"), 900);
    addPath(keys, color, {
      dur: 1700, width: qa ? 2 : 2.6, dashed: qa,
      onHit: (i) => { lightStage(stagesAt[i], d); if (i === keys.length - 1) { const n = nodes[keys[i]]; if (n) n.count++; } },
    });
    metrics();
    panels(d);
    log(qa ? "qa" : (d.warnings && d.warnings.length ? "warn" : ""),
      qa ? `QA route → <b>${esc(shortModel(d.model_id))}</b> (strongest)`
         : `${esc(d.source)}${d.rule ? "/" + esc(d.rule) : ""} · <b>${esc(TASK_SHORT[task] || task)}</b>/${esc(d.difficulty)}`
           + ` → <b>${esc(d.agent || "-")}</b> · ${esc(shortModel(d.model_id))} · ${fmtMs(d.latency_ms)}`);
    (d.warnings || []).slice(0, 2).forEach((w) => log("warn", `⚠ ${esc(w)}`));
  }

  function onDone(x) {
    const d = S.byId[x.request_id] || {};
    const used = x.model_used || d.model_id;
    if (x.status === "blocked" || x.status === "cancelled") {
      const key = `model:${d.model_id}`;
      S.marks.push({ key, text: x.status === "blocked" ? "HUMAN-LED · BLOCKED" : "APPROVAL DENIED", color: "#ff4d6d", born: S.sim });
      const n = nodes[key]; if (n) spark(n.x, n.y, "#ff4d6d", 22);
      log("err", `✕ <b>${esc(x.agent || "-")}</b> ${x.status === "blocked" ? "insan odakli · calistirilmadi" : "onay verilmedi · calistirilmadi"}`);
      return;
    }
    if (used) {
      ensureModelNode(used);
      S.modelMix[used] = (S.modelMix[used] || 0) + 1;
    }
    const cost = Number(x.est_cost_usd || 0);
    addCost(cost);
    if (x.fallback && used && x.primary_model && used !== x.primary_model) {
      S.fallbacks++;
      addPath([`model:${x.primary_model}`, `model:${used}`], "#ff4d6d", { arc: true, dashed: true, dur: 1100, label: "FALLBACK", width: 2 });
      log("warn", `↯ fallback <b>${esc(shortModel(x.primary_model))}</b> → <b>${esc(shortModel(used))}</b>`);
    }
    const n = nodes[`model:${used}`];
    if (n) { n.heat = 1; n.color = x.ok ? "#3dff9a" : "#ff4d6d"; spark(n.x, n.y, n.color, 16); }
    log(x.ok ? "ok" : "err", `${x.ok ? "✓" : "✕"} <b>${esc(x.agent || "-")}</b> ${x.ok ? "done" : "failed"} · ${esc(shortModel(used || "?"))}`
      + ` · ${x.total_ms ? (x.total_ms / 1000).toFixed(1) + "s" : "-"}${cost ? " · $" + cost.toFixed(4) : ""}`);
    metrics(); panelsModels();
  }

  function onQa(q) {
    const n = nodes[`model:${q.model}`];
    const color = q.approved === true ? "#3dff9a" : q.approved === false ? "#ffb020" : "#ff4d6d";
    if (n) { n.heat = 1; n.color = color; spark(n.x, n.y, color, 30); }
    addCost(Number(q.est_cost_usd || 0));
    const verdict = q.approved === true ? "APPROVED" : q.approved === false ? "REJECTED" : "UNAVAILABLE";
    log("qa", `◆ VERONICA QA <b>${verdict}</b> · ${esc(shortModel(q.model || "-"))}${q.fallback ? " (fallback)" : ""}`
      + (q.retries ? ` · retry ${q.retries}` : "") + (q.issues && q.issues.length ? ` · ${esc(q.issues[0])}` : ""));
    metrics();
  }

  function addCost(c) {
    if (!c) { S.free++; return; }
    S.cost += c; S.paid++;
  }

  // ------------------------------------------------------------------ UI parcalari
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const fmtMs = (v) => (typeof v === "number" ? `${v.toFixed(1)}ms` : "-");

  function showCase(d, qa, color) {
    stage.style.setProperty("--case-color", color);
    const total = S.totalCases || S.cases;
    $("#case-badge").textContent = qa ? `QA · CASE ${pad(S.cases)}` : `CASE ${pad(S.cases)} / ${pad(Math.max(total, S.cases))}`;
    $("#case-title").textContent = qa ? "QA REVIEW" : (TASK_TITLE[d.task_type] || String(d.task_type || "").toUpperCase());
    const tconf = d.scores && d.scores.task_confidence != null ? d.scores.task_confidence : d.confidence;
    let sub = `${esc(d.source)}${d.rule ? " · rule " + esc(d.rule) : ""} · task_type → <em>${esc(d.task_type)}</em> <b>${num(tconf)}</b>`
      + ` · difficulty → <b>${esc(d.difficulty)}</b>`;
    if (d.agent) sub += ` · agent → <em>${esc(d.agent)}</em> <b>${num(d.agent_confidence)}</b>${d.agent_source === "conductor_llm" ? " (llm)" : ""}`;
    if (d.warnings && d.warnings.length) sub += ` · <span class="warn">⚠ ${d.warnings.length} warning</span>`;
    $("#case-sub").innerHTML = sub;
    $("#rq-text").textContent = d.request || "—";
    $("#rq-meta").textContent = `${(d.request_id || "").slice(0, 14)} · ${fmtMs(d.latency_ms)}`;
  }
  const pad = (n) => String(n).padStart(2, "0");
  const num = (v) => (typeof v === "number" ? v.toFixed(2) : "—");

  function resetPills() {
    document.querySelectorAll("#pills span").forEach((p) => (p.className = ""));
    document.querySelectorAll("#flow span").forEach((p) => p.classList.remove("on"));
  }
  function lightStage(stg, d) {
    const flow = document.querySelector(`#flow [data-flow="${stg}"]`);
    if (flow) { document.querySelectorAll("#flow span").forEach((p) => p.classList.remove("on")); flow.classList.add("on"); }
    const pill = (name) => document.querySelector(`#pills [data-stage="${name}"]`);
    if (stg === "rules") { const p = pill("rules"); p.className = d.rule ? "lit rule" : "passed"; }
    if (stg === "classifier") { const p = pill("classifier"); p.className = d.rule && d.rule !== "explicit_model" && d.rule !== "long_context" ? "" : "lit"; }
    if (stg === "gate") {
      pill("gate").className = "lit";
      const usedLlm = d.source === "llm_fallback" || d.agent_source === "conductor_llm";
      pill("llm").className = usedLlm ? "lit llm" : "";
    }
    if (stg === "model") pill("model").className = "lit";
  }

  let shown = 0;
  function metrics() {
    const card = $("#m-decisions"), target = S.cases;
    const from = shown, t0 = performance.now();
    const step = (t) => {
      const k = Math.min(1, (t - t0) / 450), v = Math.round(from + (target - from) * (1 - Math.pow(1 - k, 3)));
      card.querySelector(".num").textContent = String(v).padStart(2, "0");
      if (k < 1) requestAnimationFrame(step); else shown = target;
    };
    if (target !== shown) { requestAnimationFrame(step); card.classList.remove("bump"); void card.offsetWidth; card.classList.add("bump"); }
    $("#m-decisions-foot").textContent = `local ${S.counts.local} · llm ${S.counts.llm} · rule ${S.counts.rule}`;

    const med = median(S.lat);
    $("#m-latency .num").textContent = med == null ? "—" : med.toFixed(1);
    sparkline();

    $("#m-cost .num").textContent = S.cost.toFixed(4);
    $("#m-cost-foot").textContent = `paid calls ${S.paid} · free ${S.free}`;

    const last = Object.values(S.byId).filter((d) => !isQa(d)).slice(-1)[0];
    const thr = S.info.thresholds.task || 0.75;
    $("#m-conf .thr").style.left = `${thr * 100}%`;
    $("#m-conf .thr b").textContent = thr.toFixed(2);
    if (last) {
      const c = typeof last.agent_confidence === "number" ? Math.min(last.confidence, last.agent_confidence) : last.confidence;
      $("#m-conf .num").textContent = num(c);
      const fill = $("#m-conf .fill");
      fill.style.width = `${Math.max(2, (c || 0) * 100)}%`;
      fill.classList.toggle("low", (c || 0) < thr);
    }
  }
  function median(a) {
    if (!a.length) return null;
    const s = [...a].sort((x, y) => x - y), m = s.length >> 1;
    return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
  }
  function sparkline() {
    const c = $("#spark"), g = c.getContext("2d"), w = c.width, h = c.height;
    g.clearRect(0, 0, w, h);
    if (S.lat.length < 2) return;
    const max = Math.max(...S.lat) * 1.15, min = 0;
    g.beginPath();
    S.lat.forEach((v, i) => {
      const x = (i / (S.lat.length - 1)) * (w - 4) + 2, y = h - 3 - ((v - min) / (max - min || 1)) * (h - 8);
      i ? g.lineTo(x, y) : g.moveTo(x, y);
    });
    g.strokeStyle = "#00e5ff"; g.lineWidth = 2; g.shadowColor = "#00e5ff"; g.shadowBlur = 8; g.stroke();
    g.shadowBlur = 0; g.lineTo(w - 2, h); g.lineTo(2, h); g.closePath();
    const grad = g.createLinearGradient(0, 0, 0, h); grad.addColorStop(0, "rgba(0,229,255,0.28)"); grad.addColorStop(1, "rgba(0,229,255,0)");
    g.fillStyle = grad; g.fill();
  }

  function bars(el, entries, total, opts = {}) {
    el.innerHTML = entries.map(([name, n, extra]) => {
      const pct = total ? Math.max(3, (n / total) * 100) : 0;
      return `<div class="bar ${extra && extra.cls || ""}"><span class="name">${esc(extra && extra.label || name)}</span>`
        + `<span class="track"><i style="width:${pct}%;background:${extra && extra.color || "#00e5ff"};box-shadow:0 0 10px ${extra && extra.color || "#00e5ff"}"></i></span>`
        + `<span class="n">${n}</span></div>`;
    }).join("") || `<div class="bar"><span class="name" style="color:var(--faint)">${opts.empty || "—"}</span></div>`;
  }
  function panels(d) {
    const tasks = Object.entries(S.taskMix).sort((a, b) => b[1] - a[1]).slice(0, 8);
    const total = tasks.reduce((s, x) => s + x[1], 0);
    bars($("#p-tasks"), tasks.map(([t, n]) => [t, n, { label: TASK_SHORT[t] || t, color: TASK_COLOR[t] }]), total, { empty: "no decisions yet" });
    panelsModels();
    signal(d);
  }
  function panelsModels() {
    const models = Object.entries(S.modelMix).sort((a, b) => b[1] - a[1]).slice(0, 7);
    const total = models.reduce((s, x) => s + x[1], 0);
    const info = Object.fromEntries(modelList().map((m) => [m.id, m]));
    bars($("#p-models"), models.map(([m, n]) => {
      const mi = info[m] || {};
      return [m, n, { label: shortModel(m), color: mi.cost === "paid" ? "#ff2fd1" : "#00e5ff",
        cls: `${mi.cost === "paid" ? "paid" : ""} ${mi.active === false ? "inactive" : ""}` }];
    }), total, { empty: "awaiting completions" });
    $("#p-fallbacks").textContent = `· fallbacks ${S.fallbacks}`;
  }
  function signal(d) {
    if (!d || isQa(d)) return;
    const groups = [
      ["TASK TYPE", (d.scores && d.scores.task_types) || [], d.scores && d.scores.task_confidence],
      ["DIFFICULTY", (d.scores && d.scores.difficulty) || [], d.scores && d.scores.difficulty_confidence],
      ["AGENT", d.agent_scores || [], d.agent_confidence],
    ];
    $("#p-signal").innerHTML = groups.map(([h, rows, conf]) => {
      const vals = rows.map((r) => r.p), max = Math.max(...vals, 0.0001), min = Math.min(...vals, max) - 0.02;
      return `<div class="sig-group"><div class="sig-h">${h}${typeof conf === "number" ? ` · conf ${conf.toFixed(2)}` : ""}</div>`
        + (rows.slice(0, 3).map((r, i) => {
          const w = max === min ? 100 : Math.max(4, ((r.p - min) / (max - min)) * 100);
          return `<div class="sig-row ${i === 0 ? "top" : ""}"><span class="name">${esc(TASK_SHORT[r.label] || r.label)}</span>`
            + `<span class="track"><i style="width:${w}%;${i ? "opacity:.45" : ""}"></i></span><span class="v">${Number(r.p).toFixed(3)}</span></div>`;
        }).join("") || `<div class="sig-row"><span class="name">—</span></div>`) + `</div>`;
    }).join("");
  }
  function log(cls, html) {
    const el = $("#p-log"), line = document.createElement("div");
    if (cls) line.className = cls;
    const t = new Date().toTimeString().slice(0, 8);
    line.innerHTML = `<span class="t">${t}</span>${html}`;
    el.appendChild(line);
    while (el.children.length > 9) el.removeChild(el.firstChild);
  }
  function status(cls, text) {
    const s = $("#status"); s.className = `status ${cls}`; s.querySelector("b").textContent = text;
  }

  // ------------------------------------------------------------------ modlar
  function resetRun() {
    S.cases = 0; S.totalCases = 0; S.counts = { local: 0, llm: 0, rule: 0 }; S.lat = []; S.cost = 0; S.paid = 0; S.free = 0;
    S.taskMix = {}; S.modelMix = {}; S.fallbacks = 0; S.byId = {}; S.paths = []; S.sparks = []; S.marks = [];
    shown = 0; $("#m-decisions .num").textContent = "00";
    for (const k in nodes) { nodes[k].count = 0; nodes[k].heat = 0; }
    $("#p-log").innerHTML = ""; $("#p-signal").innerHTML = "";
    panels(null); metrics(); resetPills();
    $("#case-badge").textContent = "CASE 00 / 00"; $("#case-title").textContent = "AWAITING DECISIONS";
    $("#case-sub").textContent = "router idle · bir istek bekleniyor"; $("#rq-text").textContent = "—"; $("#rq-meta").textContent = "";
    $("#m-latency .num").textContent = "—"; $("#m-conf .num").textContent = "—"; $("#m-conf .fill").style.width = "0";
  }
  function stopMode() {
    S.gen++;
    if (S.ws) { try { S.ws.onclose = null; S.ws.close(); } catch (e) { /* yok */ } S.ws = null; }
    clearTimeout(S.timer); S.timer = null;
  }
  function setMode(mode) {
    stopMode(); S.mode = mode; resetRun();
    document.querySelectorAll(".modes button").forEach((b) => b.classList.toggle("on", b.dataset.mode === mode));
    $("#speed").classList.toggle("hidden", mode === "live");
    if (mode === "live") { S.speed = 1; markSpeed(); startLive(); }
    else if (mode === "replay") startReplay();
    else startDemo();
    const q = new URLSearchParams(location.search); q.set("mode", mode); history.replaceState(null, "", `?${q}`);
  }

  function startLive() {
    if (!HTTP) { status("bad", "NO SERVER · file://"); log("err", "LIVE icin panoyu JARVIS sunucusundan ac (http://127.0.0.1:8772/dashboard/)"); return; }
    const gen = S.gen, url = `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws/decisions`;
    status("warn", "CONNECTING");
    const ws = new WebSocket(url); S.ws = ws;
    ws.onopen = () => { if (gen !== S.gen) return; S.wsTry = 0; status("ok", "LIVE"); log("ok", "<b>live</b> · /ws/decisions baglandi"); };
    ws.onmessage = (m) => { if (gen !== S.gen) return; try { const ev = JSON.parse(m.data); if (ev.kind !== "ping" && ev.kind !== "hello") ingest(ev); } catch (e) { /* bozuk mesaj */ } };
    ws.onclose = () => {
      if (gen !== S.gen) return;
      S.wsTry++; const wait = Math.min(10000, 800 * 2 ** Math.min(S.wsTry, 4));
      status("bad", `OFFLINE · retry ${Math.round(wait / 1000)}s`);
      S.timer = setTimeout(() => { if (gen === S.gen) startLive(); }, wait);
    };
  }

  async function startReplay() {
    const gen = S.gen;
    if (!HTTP) { status("bad", "NO SERVER"); log("err", "REPLAY icin sunucu gerekli; DEMO kullan"); return; }
    status("warn", "LOADING");
    let rows = [];
    try { rows = (await (await fetch("/api/decisions?limit=1500")).json()).rows || []; }
    catch (e) { status("bad", "LOAD FAILED"); log("err", "routing.jsonl okunamadi"); return; }
    if (gen !== S.gen) return;
    rows = rows.filter((r) => ["decision", "done", "qa"].includes(r.kind));
    if (!rows.length) { status("warn", "EMPTY LOG"); log("warn", "routing.jsonl bos · DEMO modunu dene"); return; }
    S.totalCases = rows.filter((r) => r.kind === "decision" && !isQa(r)).length;
    status("ok", `REPLAY · ${S.totalCases} cases`);
    log("ok", `<b>replay</b> · ${rows.length} kayit yuklendi`);
    let i = 0;
    const next = () => {
      if (gen !== S.gen) return;
      if (S.paused) { S.timer = setTimeout(next, 200); return; }
      if (i >= rows.length) {
        log("ok", "<b>replay complete</b> · 5 sn sonra bastan"); status("ok", "REPLAY · COMPLETE");
        S.timer = setTimeout(() => { if (gen === S.gen) setMode("replay"); }, 5000); return;
      }
      const r = rows[i++]; ingest(r);
      const gap = i < rows.length ? (Date.parse(rows[i].ts) - Date.parse(r.ts)) || 0 : 0;
      const wait = Math.min(2600, Math.max(rows[i] && rows[i].kind === "decision" ? 650 : 160, gap)) / S.speed;
      S.timer = setTimeout(next, wait);
    };
    next();
  }

  // DEMO: sahte ama gercekci kararlar (video icin)
  const DEMO = [
    { r: "yarın hangi derslerim var", t: "okul", d: "basit", a: "ders_programi", m: "gemini-flash-lite-latest" },
    { r: "agents klasöründeki python kodunu güvenlik açısından incele", t: "kod", d: "zor", a: "kod_denetcisi", m: "poolside/laguna-s-2.1:free", cond: true, qa: true },
    { r: "okunmamış maillerimi önem sırasına göre özetle", t: "iletisim", d: "orta", a: "eposta_triyaj", m: "gemini-3.5-flash" },
    { r: "İzmir'de yarın hava nasıl olacak", t: "sohbet", d: "basit", a: "hava_durumu", m: "gemini-flash-lite-latest" },
    { r: "Kotlin ile Android geliştirme hakkında kaynaklı kapsamlı araştırma yap", t: "arastirma", d: "zor", a: "arastirmaci", m: "nvidia/nemotron-3-ultra-550b-a55b:free", qa: true, fb: "gemini-3.6-flash" },
    { r: "bu ekran görüntüsündeki hatayı açıkla", t: "gorsel", d: "orta", a: "pc_operatoru", m: "gemini-3.5-flash", rule: "image_attachment" },
    { r: "bilgisayarın disk ve RAM durumunu raporla", t: "sistem_komutu", d: "orta", a: "sistem_sagligi", m: "gemini-flash-lite-latest" },
    { r: "claude ile mikroservis mimarisi tasarla", t: "kod", d: "zor", a: "kodcu", m: "claude-opus-5-5", rule: "explicit_model", cost: 0.031 },
    { r: "hocama ödev uzatma için kibar bir yanıt taslağı yaz", t: "yazi", d: "orta", a: "yanit_taslakcisi", m: "gemini-3.5-flash", cond: true },
    { r: "bunu bir düşün bakalım", t: "planlama", d: "basit", a: "planlayici", m: "gemini-flash-lite-latest", cond: true, llm: true, deny: true },
    { r: "Matematik vizesine 5 gün kaldı, gün gün çalışma planı yap", t: "okul", d: "zor", a: "sinav_kocu", m: "nvidia/nemotron-3-ultra-550b-a55b:free", qa: true },
    { r: "Tarkan'dan bir şarkı çal", t: "sistem_komutu", d: "basit", a: "muzik_dj", m: "gemini-flash-lite-latest" },
  ];
  function rnd(a, b) { return a + Math.random() * (b - a); }
  function startDemo() {
    const gen = S.gen; let i = 0;
    S.totalCases = DEMO.length;
    status("ok", "DEMO · synthetic");
    log("qa", "<b>demo</b> · sahte kararlar (video modu)");
    const later = (ms, fn) => setTimeout(() => { if (gen === S.gen) fn(); }, ms / S.speed);
    const next = () => {
      if (gen !== S.gen) return;
      if (S.paused) { S.timer = setTimeout(next, 200); return; }
      if (i && i % DEMO.length === 0) { resetRun(); S.totalCases = DEMO.length; }
      const c = DEMO[i % DEMO.length], id = `demo${Date.now().toString(36)}${i}`; i++;
      const conf = c.rule ? 1 : c.llm ? 0.8 : rnd(0.78, 0.99), aconf = c.cond ? rnd(0.5, 0.7) : rnd(0.86, 1);
      const others = TASKS.filter((t) => t !== c.t && t !== "qa").sort(() => Math.random() - 0.5);
      const top = rnd(0.86, 0.92);
      const dec = {
        kind: "decision", request_id: id, request: c.r, task_type: c.t, difficulty: c.d,
        source: c.rule ? "rule" : c.llm ? "llm_fallback" : "classifier", rule: c.rule || null,
        confidence: conf, model_id: c.m, chain: [c.m], latency_ms: rnd(8, 34),
        agent: c.a, agent_source: c.cond ? "conductor_llm" : "classifier", agent_confidence: c.cond ? 0.9 : aconf,
        warnings: c.llm ? ["LLM yonlendirmesi basarisiz (TimeoutError)"] : [],
        scores: {
          task_types: [{ label: c.t, p: top }, { label: others[0], p: top - rnd(0.01, 0.04) }, { label: others[1], p: top - rnd(0.04, 0.07) }],
          difficulty: [c.d, ...["basit", "orta", "zor"].filter((x) => x !== c.d)]
            .map((label, k) => ({ label, p: k === 0 ? rnd(0.84, 0.9) : k === 1 ? rnd(0.82, 0.84) : rnd(0.8, 0.82) })),
          task_confidence: conf, difficulty_confidence: rnd(0.62, 0.95),
        },
        agent_scores: [{ label: c.a, p: rnd(0.88, 0.93) }, { label: "planlayici", p: rnd(0.84, 0.87) }, { label: "mesaj_yazari", p: rnd(0.82, 0.84) }],
      };
      ingest(dec);
      later(rnd(1900, 2600), () => {
        if (c.deny) { ingest({ kind: "done", request_id: id, status: "cancelled", ok: false, agent: c.a }); return; }
        const fb = !!c.fb;
        ingest({ kind: "done", request_id: id, ok: true, status: "done", agent: c.a, model_used: fb ? c.fb : c.m,
          primary_model: c.m, fallback: fb, total_ms: rnd(9000, 42000), est_cost_usd: c.cost || 0 });
        if (c.qa) {
          later(900, () => {
            const qid = `${id}-qa`;
            ingest({ kind: "decision", request_id: qid, request: c.r, task_type: "qa", difficulty: "zor", source: "rule", rule: "qa",
              confidence: 1, model_id: "claude-opus-5-5", chain: ["claude-opus-5-5"], latency_ms: rnd(1, 4), warnings: [], scores: {} });
            later(1700, () => ingest({ kind: "qa", request_id: id, approved: Math.random() > 0.25, model: "claude-opus-5-5",
              fallback: false, retries: 0, issues: [], est_cost_usd: rnd(0.012, 0.03) }));
          });
        }
      });
      S.timer = setTimeout(next, (c.qa ? 6200 : 3600) / S.speed);
    };
    next();
  }

  // ------------------------------------------------------------------ kontroller
  function markSpeed() {
    document.querySelectorAll("#speed button").forEach((b) => b.classList.toggle("on", Number(b.dataset.speed) === S.speed));
  }
  function setSpeed(v) {
    S.speed = Math.max(0.5, Math.min(4, v)); markSpeed();
    const q = new URLSearchParams(location.search); q.set("speed", S.speed); history.replaceState(null, "", `?${q}`);
  }
  document.querySelectorAll(".modes button").forEach((b) => b.addEventListener("click", () => setMode(b.dataset.mode)));
  document.querySelectorAll("#speed button").forEach((b) => b.addEventListener("click", () => setSpeed(Number(b.dataset.speed))));
  addEventListener("keydown", (e) => {
    if (e.key === "1") setMode("live"); else if (e.key === "2") setMode("replay"); else if (e.key === "3") setMode("demo");
    else if (e.key === "+" || e.key === "=") setSpeed([0.5, 1, 2, 4].find((s) => s > S.speed) || 4);
    else if (e.key === "-") setSpeed([4, 2, 1, 0.5].find((s) => s < S.speed) || 0.5);
    else if (e.key === " ") { S.paused = !S.paused; $("#paused").classList.toggle("on", S.paused); e.preventDefault(); }
  });
  addEventListener("resize", fit);

  // ------------------------------------------------------------------ dongu
  let last = performance.now();
  function frame(t) {
    const dt = Math.min(64, t - last); last = t;
    if (!S.paused) {
      S.sim += dt * S.speed;
      for (const s of S.sparks) { s.x += s.vx * dt; s.y += s.vy * dt; s.vx *= 0.97; s.vy *= 0.97; s.life -= dt / 900; }
    }
    draw();
    requestAnimationFrame(frame);
  }
  setInterval(() => { $("#clock").textContent = new Date().toTimeString().slice(0, 8); }, 250);

  async function boot() {
    fit();
    if (HTTP) {
      try {
        const info = await (await fetch("/api/info")).json();
        if (info && info.models && info.models.length) {
          S.info = { ...S.info, ...info, thresholds: { ...S.info.thresholds, ...(info.thresholds || {}) } };
          layout();
        }
      } catch (e) { /* sunucu yok: varsayilanlar */ }
    }
    $("#version").textContent = `${S.info.version || "router"}`;
    const sp = Number(params.get("speed")); if ([0.5, 1, 2, 4].includes(sp)) S.speed = sp;
    markSpeed();
    const m = params.get("mode");
    setMode(["live", "replay", "demo"].includes(m) ? m : HTTP ? "live" : "demo");
    requestAnimationFrame(frame);
  }
  boot();
})();
