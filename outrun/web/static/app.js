// Outrun the Earthquake: browser interface (a SIMULATION).
//
// The browser only DRAWS results. Every number shown (alert time, location,
// warnings, test results) is computed by the Python code: the simulation
// creates the quake and phone reports, the warning server works from the
// reports alone, and the evaluation compares afterwards. That Python code runs
// either in the Flask server (python -m outrun.web.app) or, in the web
// version, inside the browser itself (Pyodide, see outrun/web/browser/).
"use strict";

const $ = (id) => document.getElementById(id);
const canvas = $("map");
const ctx = canvas.getContext("2d");
const SIZE = canvas.width;            // drawing units (640 x 640)
const DPR = Math.min(2, Math.max(1, Math.round(window.devicePixelRatio || 1)));
canvas.width = canvas.height = SIZE * DPR;   // sharper on high-resolution screens
ctx.scale(DPR, DPR);

// Colours come from the CSS variables in style.css, so the map follows the
// light/dark theme. A hidden element turns light-dark(...) into a real colour.
const probe = document.createElement("span");
probe.style.display = "none";
document.body.appendChild(probe);
function cssColour(name) {
  probe.style.color = `var(${name})`;
  return getComputedStyle(probe).color;
}
let C = {};
function readPalette() {
  for (const name of ["map-bg", "map-grid", "map-town", "map-phone", "map-label", "map-faint",
                      "ink", "muted", "surface", "accent", "p-wave", "s-wave", "felt", "rejected", "line"]) {
    C[name] = cssColour("--" + name);
  }
}
readPalette();

const state = {
  world: null,
  run: null,
  k: 10,
  you: { x: 120, y: 60 },
  quake: null,
  t: 0, tStart: 0, tEnd: 0,
  playing: false,
  lastFrame: 0,
  draggingYou: false,
  falseAlarms: null,
  hiddenBatch: 0,
  flashUntil: 0,
  base: null, // pre-drawn background (map, towns, phones)
};

// ---------------------------------------------------------------------------
// Coordinates: km (y up, north) <-> canvas pixels (y down)
// ---------------------------------------------------------------------------
function scale() { return SIZE / state.world.map.width_km; }
function toPx(x, y) { const s = scale(); return [x * s, SIZE - y * s]; }
function fromEvent(ev) {
  const rect = canvas.getBoundingClientRect();
  const px = (ev.clientX - rect.left) * (SIZE / rect.width);
  const py = (ev.clientY - rect.top) * (SIZE / rect.height);
  const s = scale();
  return { x: Math.min(Math.max(px / s, 0), state.world.map.width_km),
           y: Math.min(Math.max((SIZE - py) / s, 0), state.world.map.height_km) };
}

function setInstruction(text) { $("instruction-text").textContent = text; }
function fmt(v, d = 1) { return v === null || v === undefined ? "–" : Number(v).toFixed(d); }

async function api(path, body) {
  // Web version: the same requests are answered by Python in the browser.
  if (window.OutrunPy) return window.OutrunPy.call(path, body);
  const res = await fetch(path, body === undefined ? {} : {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || ("HTTP " + res.status));
  return data;
}

// ---------------------------------------------------------------------------
// Background layer
// ---------------------------------------------------------------------------
function drawBase() {
  const off = document.createElement("canvas");
  off.width = off.height = SIZE * DPR;
  const c = off.getContext("2d");
  c.scale(DPR, DPR);
  c.fillStyle = C["map-bg"]; c.fillRect(0, 0, SIZE, SIZE);
  // grid every 50 km
  c.strokeStyle = C["map-grid"]; c.lineWidth = 1;
  for (let km = 50; km < state.world.map.width_km; km += 50) {
    const [gx] = toPx(km, 0); const [, gy] = toPx(0, km);
    c.beginPath(); c.moveTo(gx, 0); c.lineTo(gx, SIZE); c.stroke();
    c.beginPath(); c.moveTo(0, gy); c.lineTo(SIZE, gy); c.stroke();
  }
  for (const t of state.world.towns) {
    const [tx, ty] = toPx(t.x_km, t.y_km);
    c.fillStyle = C["map-town"];
    c.beginPath(); c.arc(tx, ty, t.radius_km * scale(), 0, 2 * Math.PI); c.fill();
  }
  c.fillStyle = C["map-phone"];
  for (const [x, y] of state.world.phones) {
    const [px, py] = toPx(x, y);
    c.beginPath(); c.arc(px, py, 1.1, 0, 2 * Math.PI); c.fill();
  }
  c.font = "600 13px Inter, system-ui, sans-serif"; c.fillStyle = C["map-label"]; c.textAlign = "center";
  for (const t of state.world.towns) {
    const [tx, ty] = toPx(t.x_km, t.y_km);
    c.fillText(t.name + " (simulated)", tx, ty - t.radius_km * scale() - 6);
  }
  c.textAlign = "left"; c.font = "11px Inter, system-ui, sans-serif"; c.fillStyle = C["map-faint"];
  c.fillText("200 × 200 km simulated region · grid every 50 km", 8, SIZE - 8);
  state.base = off;
}

// ---------------------------------------------------------------------------
// Drawing one moment of the replay
// ---------------------------------------------------------------------------
function latestSnapshot(t) {
  let best = null;
  for (const s of state.run.snapshots) { if (s.t_s <= t) best = s; else break; }
  return best;
}

function waveRadius(speed, t) {
  const tr = state.run.truth;
  const dist = speed * (t - tr.origin_time_s);
  return dist > tr.depth_km ? Math.sqrt(dist * dist - tr.depth_km * tr.depth_km) : 0;
}

function drawPerson(x, y) {
  const [px, py] = toPx(x, y);
  ctx.fillStyle = C.ink; ctx.strokeStyle = C["map-bg"]; ctx.lineWidth = 2;
  ctx.beginPath(); ctx.arc(px, py - 9, 5, 0, 2 * Math.PI); ctx.fill(); ctx.stroke();
  ctx.beginPath(); ctx.moveTo(px - 6, py + 8); ctx.lineTo(px, py - 3); ctx.lineTo(px + 6, py + 8);
  ctx.closePath(); ctx.fill(); ctx.stroke();
  ctx.font = "700 12px Inter, system-ui, sans-serif"; ctx.textAlign = "center";
  ctx.lineWidth = 3; ctx.strokeStyle = C["map-bg"]; ctx.strokeText("You", px, py + 22);
  ctx.fillStyle = C.ink; ctx.fillText("You", px, py + 22); ctx.textAlign = "left";
}

function roundRect(x, y, w, h, r) {
  ctx.beginPath();
  ctx.moveTo(x + r, y); ctx.arcTo(x + w, y, x + w, y + h, r); ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r); ctx.arcTo(x, y, x + w, y, r); ctx.closePath();
}

function draw() {
  if (!state.world) return;
  ctx.drawImage(state.base, 0, 0, SIZE, SIZE);
  const run = state.run;
  const t = state.t;
  const s = scale();

  if (run) {
    const a = run.alert;
    // No-warning zone (predicted by the server) once the alert is delivered
    if (a && t >= a.t_delivered_s) {
      const [ex, ey] = toPx(a.estimate.x_km, a.estimate.y_km);
      ctx.fillStyle = "rgba(210,56,44,0.16)";
      ctx.beginPath(); ctx.arc(ex, ey, a.predicted_blind_radius_km * s, 0, 2 * Math.PI); ctx.fill();
    }
    // Phones that felt the quake (or were bumped) and reported
    for (const r of run.reports) {
      if (r.t_detect_s > t) continue;
      const [x, y] = state.world.phones[r.phone];
      const [px, py] = toPx(x, y);
      const rejected = r.processed && !r.trusted && t >= r.t_received_s;
      ctx.fillStyle = rejected ? C.rejected : C.felt;
      ctx.beginPath(); ctx.arc(px, py, rejected ? 3.2 : 2.4, 0, 2 * Math.PI); ctx.fill();
    }
    // Waves (true, simulated)
    const tr = run.truth;
    const [qx, qy] = toPx(tr.x_km, tr.y_km);
    const rp = waveRadius(tr.vp_km_s, t), rs = waveRadius(tr.vs_km_s, t);
    if (rp > 0) {
      ctx.setLineDash([7, 6]); ctx.strokeStyle = C["p-wave"]; ctx.lineWidth = 2;
      ctx.beginPath(); ctx.arc(qx, qy, rp * s, 0, 2 * Math.PI); ctx.stroke(); ctx.setLineDash([]);
    }
    if (rs > 0) {
      ctx.strokeStyle = C["s-wave"]; ctx.lineWidth = 4;
      ctx.beginPath(); ctx.arc(qx, qy, rs * s, 0, 2 * Math.PI); ctx.stroke();
    }
    // Server's current estimate
    const snap = latestSnapshot(t);
    if (snap && snap.estimate && snap.estimate.x_km !== null) {
      const e = snap.estimate;
      const [ex, ey] = toPx(e.x_km, e.y_km);
      if (e.predicted_error_km !== null && e.predicted_error_km < 400) {
        ctx.strokeStyle = C.accent; ctx.lineWidth = 1.5;
        ctx.beginPath(); ctx.arc(ex, ey, Math.max(e.predicted_error_km * s, 3), 0, 2 * Math.PI); ctx.stroke();
      }
      ctx.strokeStyle = C.accent; ctx.lineWidth = 3; ctx.lineCap = "round";
      ctx.beginPath(); ctx.moveTo(ex - 9, ey); ctx.lineTo(ex + 9, ey); ctx.moveTo(ex, ey - 9); ctx.lineTo(ex, ey + 9); ctx.stroke();
    }
    // Where the user started the quake (drawn on top so the estimate never hides it)
    ctx.font = "700 22px system-ui, sans-serif"; ctx.textAlign = "center";
    ctx.lineWidth = 3; ctx.strokeStyle = C["map-bg"]; ctx.strokeText("★", qx, qy + 8);
    ctx.fillStyle = C["s-wave"]; ctx.fillText("★", qx, qy + 8); ctx.textAlign = "left";
    // Server box
    const received = run.reports.filter((r) => r.processed && r.t_received_s <= t).length;
    const sent = a && t >= a.t_issued_s;
    const line2 = sent ? `${received} reports · ALERT SENT` : `${received} reports · needs ${run.k} that agree`;
    ctx.font = "13px Inter, system-ui, sans-serif";
    const boxW = Math.max(170, ctx.measureText(line2).width + 28);
    ctx.fillStyle = sent ? C.accent : "rgba(18,21,25,0.86)";
    roundRect(10, 10, boxW, 48, 9); ctx.fill();
    ctx.fillStyle = "#fff"; ctx.font = "600 13px Inter, system-ui, sans-serif";
    ctx.fillText("Server (simulated)", 24, 30);
    ctx.font = "13px Inter, system-ui, sans-serif";
    ctx.fillText(line2, 24, 48);
    // Alert flash
    if (performance.now() < state.flashUntil) {
      const left = (state.flashUntil - performance.now()) / 700;
      ctx.globalAlpha = 0.22 * left; ctx.fillStyle = C.accent; ctx.fillRect(0, 0, SIZE, SIZE); ctx.globalAlpha = 1;
    }
  }
  drawPerson(state.you.x, state.you.y);
  if (!run) {
    const msg = "Click anywhere to start an earthquake";
    ctx.font = "600 15px Inter, system-ui, sans-serif"; ctx.textAlign = "center";
    const w = ctx.measureText(msg).width + 36;
    ctx.fillStyle = "rgba(18,21,25,0.86)"; roundRect(SIZE / 2 - w / 2, SIZE / 2 - 22, w, 44, 22); ctx.fill();
    ctx.fillStyle = "#fff"; ctx.fillText(msg, SIZE / 2, SIZE / 2 + 5); ctx.textAlign = "left";
  }
}

// ---------------------------------------------------------------------------
// Panel numbers and messages for the current moment
// ---------------------------------------------------------------------------
function youPlace() { return state.run && state.run.places.find((p) => p.name === "You"); }

function updatePanel() {
  const run = state.run;
  const t = state.t;
  $("clock").textContent = run ? `t = ${fmt(t - run.truth.origin_time_s, 1)} s after the quake started` : "t = –";
  drawTimeline();
  if (!run) return;
  const a = run.alert;
  const received = run.reports.filter((r) => r.processed && r.t_received_s <= t).length;
  $("n-reports").textContent = `${received}`;
  const alertShown = a && t >= a.t_issued_s;
  const box = $("alert-box");
  if (alertShown) {
    box.className = "alert-box sent";
    box.textContent = `ALERT SENT ${fmt(a.seconds_after_quake_start, 1)} s after the quake started`;
  } else if (state.playing || a) {
    box.className = "alert-box listening";
    box.textContent = received ? `Server listening: ${received} report${received === 1 ? "" : "s"} so far` : "Earthquake started: waiting for reports";
  } else {
    box.className = "alert-box none";
    box.textContent = "No alert: the reports never agreed well enough";
  }
  const num = (v, d, unit, sub) => `${fmt(v, d)}<span class="unit">${unit}</span>${sub ? `<span class="sub">${sub}</span>` : ""}`;
  $("n-alert").innerHTML = alertShown ? num(a.seconds_after_quake_start, 1, "s", "after the quake started")
    : (a || state.playing ? "waiting…" : "no alert");
  $("n-error").innerHTML = alertShown ? num(a.location_error_km, 1, "km", "from the true epicentre") : "–";
  $("n-blind").innerHTML = alertShown ? num(a.predicted_blind_radius_km, 0, "km", `actual ${fmt(a.true_blind_radius_km, 0)} km`) : "–";
  const you = youPlace();
  $("n-warning").innerHTML = alertShown && you
    ? `${fmt(you.predicted_warning_s, 1)}<span class="unit">/</span> ${fmt(you.true_warning_s, 1)}<span class="unit">s</span>` : "–";

  const ybox = $("you-box");
  if (alertShown && you && t >= a.t_delivered_s) {
    const sArrival = a.t_delivered_s + you.true_warning_s;
    ybox.classList.remove("hidden");
    if (you.true_warning_s <= 0) {
      ybox.textContent = "You: no warning possible here (too close)"; ybox.classList.add("shaking");
    } else if (t < sArrival) {
      ybox.textContent = `You: strong shaking in ${fmt(sArrival - t, 1)} s`; ybox.classList.remove("shaking");
    } else {
      ybox.textContent = `You: strong shaking now (you had ${fmt(you.true_warning_s, 1)} s of warning)`; ybox.classList.add("shaking");
    }
  } else {
    ybox.classList.add("hidden");
  }

  if (!state.playing) return;
  if (!a || t < a.t_issued_s) {
    setInstruction(received === 0
      ? "Watch: the dashed P-wave spreads first. Phones it reaches light up yellow and report to the server."
      : `The server is working it out from ${received} report${received === 1 ? "" : "s"}. Teal cross: its current estimate.`);
  } else {
    setInstruction("ALERT SENT. The warning travels faster than the red S-wave. Drag the person to see warnings elsewhere.");
  }
}

// ---------------------------------------------------------------------------
// The race timeline: quake start -> alert sent -> alert delivered -> strong
// shaking reaches "You". All times come from the run (computed in Python).
// ---------------------------------------------------------------------------
function drawTimeline() {
  const track = $("track");
  const run = state.run;
  const you = youPlace();
  if (!run) { track.innerHTML = '<div class="track-empty">Start a quake to see the race between the alert and the strong shaking.</div>'; return; }
  const t0 = run.truth.origin_time_s;
  const a = run.alert;
  // When the S-wave reaches "You": from the alert's numbers if there was an
  // alert, otherwise from the true quake (the same values that draw the rings).
  const tr = run.truth;
  const sAtYou = a && you
    ? a.t_delivered_s + you.true_warning_s - t0
    : Math.hypot(Math.hypot(state.you.x - tr.x_km, state.you.y - tr.y_km), tr.depth_km) / tr.vs_km_s;
  const marks = [{ at: 0, cls: "quake", label: "<b>Quake</b> 0 s" }];
  if (a) {
    marks.push({ at: a.t_issued_s - t0, cls: "alert", label: `<b>Alert sent</b> ${fmt(a.t_issued_s - t0, 1)} s` });
  }
  marks.push({ at: sAtYou, cls: "shake", label: `<b>Shaking at You</b> ${fmt(sAtYou, 1)} s` });
  const end = Math.max(...marks.map((m) => m.at), a ? a.t_delivered_s - t0 : 0, 4) * 1.08 + 0.5;
  const pos = (sec) => `calc(14px + (100% - 28px) * ${Math.min(Math.max(sec / end, 0), 1)})`;
  let html = '<div class="axis"></div>';
  if (a && you) {
    const from = a.t_delivered_s - t0, to = sAtYou;
    if (to > from) {
      html += `<div class="window" style="left:${pos(from)};width:calc((100% - 28px) * ${(to - from) / end})"></div>`;
      html += `<div class="window-label" style="left:${pos((from + to) / 2)}">Your warning: ${fmt(to - from, 1)} s</div>`;
    } else {
      html += `<div class="window-label none" style="left:${pos(Math.max(0, to))}">No warning for You: shaking arrives before the alert</div>`;
    }
  } else if (!a && !state.playing) {
    html += `<div class="window-label none" style="left:50%">No alert was sent</div>`;
  }
  // Labels sit in a top row; a label that would overlap the one before it
  // (measured in pixels, so it also works on a phone) moves to a bottom row.
  const usable = Math.max(track.clientWidth - 28, 1);
  let lastTopPx = -Infinity;
  marks.forEach((m) => {
    const frac = Math.min(Math.max(m.at / end, 0), 1);
    const side = frac < 0.12 ? " left" : frac > 0.88 ? " right" : "";
    const px = frac * usable;
    const bottom = px - lastTopPx < 120;
    if (!bottom) lastTopPx = px;
    html += `<div class="tick ${m.cls}" style="left:${pos(m.at)}"></div>`;
    html += `<div class="tick-label${side}" style="left:${pos(m.at)};${bottom ? "top:70px;" : ""}">${m.label}</div>`;
  });
  html += `<div class="head" style="left:${pos(state.t - t0)}"></div>`;
  track.innerHTML = html;
}

function updateFalseAlarms() {
  const fa = state.falseAlarms;
  if (!fa || fa.status !== "ready") { $("n-false").textContent = fa && fa.status === "error" ? "unavailable" : "measuring…"; return; }
  const n = fa.hours_with_false_alert[String(state.k)];
  $("n-false").textContent = `${n} of ${fa.hours} simulated hours of noise`;
}

// ---------------------------------------------------------------------------
// Replay loop
// ---------------------------------------------------------------------------
function frame(now) {
  if (!state.playing) return;
  const speed = Number($("speed").value) * 8; // simulated seconds per real second
  const dt = state.lastFrame ? (now - state.lastFrame) / 1000 : 0;
  state.lastFrame = now;
  const before = state.t;
  state.t = Math.min(state.t + dt * speed, state.tEnd);
  const a = state.run.alert;
  if (a && before < a.t_delivered_s && state.t >= a.t_delivered_s) state.flashUntil = performance.now() + 700;
  draw(); updatePanel();
  if (state.t >= state.tEnd) { finish(); return; }
  requestAnimationFrame(frame);
}

function finish() {
  state.playing = false;
  draw(); updatePanel();
  $("replay").disabled = false;
  const run = state.run;
  if (!run.alert) {
    setInstruction("No alert: the reports never agreed well enough (try a quake nearer the phones, or a lower K).");
  } else {
    setInstruction("Now move the slider: how many reports should the server wait for? Then test it blind.");
  }
}

function computeTimes() {
  // Replay from just before the quake until the S-wave has reached "You".
  const run = state.run;
  const tr = run.truth;
  const you = youPlace();
  const lastReport = Math.max(...run.reports.filter((r) => r.processed).map((r) => r.t_received_s), tr.origin_time_s);
  let end = lastReport + 1;
  if (run.alert) end = Math.max(end, run.alert.t_delivered_s + 2);
  if (run.alert && you) end = Math.max(end, run.alert.t_delivered_s + you.true_warning_s + 2);
  state.tStart = tr.origin_time_s - 0.5;
  state.tEnd = Math.min(end, tr.origin_time_s + 60);
}

function play(fromStart = true) {
  computeTimes();
  if (fromStart) state.t = state.tStart;
  state.playing = true; state.lastFrame = 0;
  $("replay").disabled = true;
  requestAnimationFrame(frame);
}

async function startRun({ replay = true } = {}) {
  if (!state.quake) return;
  try {
    if (replay) setInstruction("Simulating the earthquake and running the warning server…");
    state.run = await api("/api/run", {
      seed: state.world.seed, k: state.k,
      quake_x_km: state.quake.x, quake_y_km: state.quake.y,
      you_x_km: state.you.x, you_y_km: state.you.y,
    });
    if (replay) {
      play(true);
    } else {
      // Moving "You" does not change the quake: show the final outcome for the new spot.
      computeTimes(); state.t = state.tEnd; draw(); updatePanel();
    }
  } catch (err) {
    setInstruction("Something went wrong: " + err.message);
  }
}

// ---------------------------------------------------------------------------
// Input
// ---------------------------------------------------------------------------
function nearYou(p) {
  return Math.hypot(p.x - state.you.x, p.y - (state.you.y)) < 14 / scale() + 2;
}

canvas.addEventListener("pointerdown", (ev) => {
  if (!state.world) return;
  const p = fromEvent(ev);
  if (nearYou(p)) { state.draggingYou = true; canvas.setPointerCapture(ev.pointerId); return; }
  state.quake = p;
  state.run = null;
  startRun({ replay: true });
});
canvas.addEventListener("pointermove", (ev) => {
  if (!state.draggingYou) return;
  const p = fromEvent(ev);
  state.you = p;
  if (!state.playing) draw();
});
canvas.addEventListener("pointerup", () => {
  if (!state.draggingYou) return;
  state.draggingYou = false;
  if (state.run && !state.playing) startRun({ replay: false });
});

$("k").addEventListener("input", () => { $("k-value").textContent = $("k").value; });
$("k").addEventListener("change", () => {
  state.k = Number($("k").value);
  updateFalseAlarms();
  if (state.quake) startRun({ replay: true });
});
$("replay").addEventListener("click", () => { if (state.run) play(true); });

$("hidden-test").addEventListener("click", async () => {
  const button = $("hidden-test");
  button.disabled = true;
  $("hidden-result").textContent = `Running 25 hidden quakes the server has never seen (K = ${state.k})…`;
  try {
    const res = await api("/api/hidden-test", { k: state.k, n: 25, batch: state.hiddenBatch++ });
    $("hidden-result").innerHTML =
      `<b>${res.alerted} of ${res.quakes}</b> hidden quakes alerted. ` +
      `Median location error <b>${fmt(res.median_error_km, 1)} km</b>, 90 % within <b>${fmt(res.p90_error_km, 1)} km</b>. ` +
      `Median alert <b>${fmt(res.median_alert_delay_s, 1)} s</b> after the quake started. ` +
      `<span class="small">(validation stream, seeds ${res.first_seed}–${res.first_seed + res.quakes - 1}; the server never saw where they were)</span>`;
    state.lastHistogram = res.errors_km;
    drawHistogram(res.errors_km);
  } catch (err) {
    $("hidden-result").textContent = "Test failed: " + err.message;
  }
  button.disabled = false;
});

function drawHistogram(errors) {
  const h = $("histogram"); h.classList.remove("hidden");
  const W = 340, H = 150;
  h.width = W * DPR; h.height = H * DPR;
  const c = h.getContext("2d"); c.setTransform(DPR, 0, 0, DPR, 0, 0);
  const bins = new Array(11).fill(0);
  for (const e of errors) bins[Math.min(10, Math.floor(e))] += 1;
  const max = Math.max(1, ...bins);
  c.clearRect(0, 0, W, H);
  c.font = "12px Inter, system-ui, sans-serif"; c.fillStyle = C.muted;
  c.fillText("Location error of each hidden quake (km)", 4, 13);
  const bw = (W - 10) / 11, base = H - 18;
  bins.forEach((n, i) => {
    const bh = (n / max) * (base - 34);
    c.fillStyle = i < 10 ? C.accent : C["s-wave"];
    c.fillRect(6 + i * bw, base - bh, bw - 4, bh);
    c.fillStyle = C.muted; c.textAlign = "center";
    c.fillText(i < 10 ? String(i) : "10+", 6 + i * bw + bw / 2 - 1, H - 5);
    if (n) c.fillText(String(n), 6 + i * bw + bw / 2 - 1, base - bh - 3);
  });
  c.textAlign = "left";
}

async function pollFalseAlarms() {
  try {
    state.falseAlarms = await api("/api/false-alarms");
  } catch (err) {
    state.falseAlarms = { status: "error" };
  }
  updateFalseAlarms();
  if (!state.falseAlarms || state.falseAlarms.status === "measuring") setTimeout(pollFalseAlarms, 3000);
}

async function init() {
  try {
    state.world = await api("/api/world?seed=7");
  } catch (err) {
    setInstruction("Could not reach the simulation server: " + err.message);
    return;
  }
  const k = state.world.k;
  Object.assign($("k"), { min: k.min, max: k.max, value: k.default });
  state.k = k.default; $("k-value").textContent = k.default;
  drawBase(); draw(); drawTimeline();
  $("hidden-test").disabled = false;
  setInstruction("Click anywhere on the map to start an earthquake.");
  pollFalseAlarms();
}

// Redraw in the new colours when the light/dark theme changes.
function onThemeChange() {
  readPalette();
  if (!state.world) return;
  drawBase(); draw();
  if (state.lastHistogram) drawHistogram(state.lastHistogram);
}
window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", onThemeChange);
const themeWatch = new MutationObserver(onThemeChange);
themeWatch.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });

init();
