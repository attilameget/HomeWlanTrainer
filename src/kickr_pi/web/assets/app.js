const $ = (id) => document.getElementById(id);

const state = {
  workoutId: null,
  live: null,
  wakeLock: null,
  wakeLockWanted: false,
  manualWatts: 100,
  history: [], // { t, power, target } — t is active ride ms (pauses excluded)
  historySession: null,
  historyActiveMs: 0,
  historyLastTickAt: null,
  powerSum: 0,
  powerCount: 0,
  emulator: false,
  trainerConnected: false,
  hrSupported: false,
  hrConnected: false,
  hasTodayWorkout: false,
  ftpW: 200,
  preview: null, // { stages, ftp, totalS, selected, layout }
  rideProfile: null, // { workoutId, stages, ftp } for structure chart
  view: "home",
  /** When true, live ticks must not auto-navigate to the ride view (user left mid-ride). */
  suppressRideAutoNav: false,
};

const HISTORY_WINDOW_MS = 10 * 60 * 1000;
/** Ride structure panel: 2 min past + 8 min ahead (same 10 min span as power history). */
const RIDE_STRUCT_PAST_S = 2 * 60;
const RIDE_STRUCT_AHEAD_S = 8 * 60;

function adherenceColor(power, target) {
  if (target == null || target <= 0 || power == null) return "#8a9aa8";
  const pct = Math.abs(power - target) / target;
  if (pct <= 0.05) return "#1f5f85";
  if (pct <= 0.1) return "#f0a03c";
  return "#e25b65";
}

function resetPowerHistory() {
  state.history = [];
  state.historyActiveMs = 0;
  state.historyLastTickAt = null;
  state.powerSum = 0;
  state.powerCount = 0;
}

function pushHistory(live) {
  // Only advance the chart clock while the workout is actively running
  if (live.engine_state !== "running") {
    state.historyLastTickAt = null;
    return;
  }

  const wall = Date.now();
  if (state.historyLastTickAt != null) {
    state.historyActiveMs += wall - state.historyLastTickAt;
  }
  state.historyLastTickAt = wall;

  const last = state.history[state.history.length - 1];
  if (last && state.historyActiveMs - last.t < 800) return;

  const power = live.power_w ?? 0;
  state.history.push({
    t: state.historyActiveMs,
    power,
    target: live.target_w ?? 0,
  });
  state.powerSum += power;
  state.powerCount += 1;
  const cutoff = state.historyActiveMs - HISTORY_WINDOW_MS;
  while (state.history.length && state.history[0].t < cutoff) {
    state.history.shift();
  }
}

function sessionAverageWatts() {
  if (!state.powerCount) {
    const liveW = state.live?.power_w;
    return liveW != null ? Math.round(liveW) : null;
  }
  return Math.round(state.powerSum / state.powerCount);
}

function rideChartCanvasSetup(canvas) {
  const dpr = window.devicePixelRatio || 1;
  const cssW = canvas.clientWidth || 320;
  const cssH = canvas.clientHeight || 180;
  if (canvas.width !== Math.floor(cssW * dpr) || canvas.height !== Math.floor(cssH * dpr)) {
    canvas.width = Math.floor(cssW * dpr);
    canvas.height = Math.floor(cssH * dpr);
  }
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, cssW, cssH);
  return {
    ctx,
    cssW,
    cssH,
    padL: 36,
    padR: 10,
    padT: 12,
    padB: 6,
  };
}

function drawPowerLineOnChart(ctx, samples, {
  padL, padT, plotW, plotH, maxW, tToX,
}) {
  if (!samples.length) return;

  const point = (s) => ({
    x: tToX(s.t),
    y: padT + plotH - ((s.power || 0) / maxW) * plotH,
  });

  if (samples.length >= 2) {
    const first = point(samples[0]);
    const last = point(samples[samples.length - 1]);
    ctx.beginPath();
    ctx.moveTo(first.x, padT + plotH);
    for (const s of samples) {
      const p = point(s);
      ctx.lineTo(p.x, p.y);
    }
    ctx.lineTo(last.x, padT + plotH);
    ctx.closePath();
    ctx.fillStyle = "rgba(31, 95, 133, 0.12)";
    ctx.fill();
  }

  if (samples.length === 1) {
    const p = point(samples[0]);
    ctx.fillStyle = adherenceColor(samples[0].power, samples[0].target);
    ctx.beginPath();
    ctx.arc(p.x, p.y, 3, 0, Math.PI * 2);
    ctx.fill();
    return;
  }

  ctx.lineWidth = 2.4;
  ctx.lineJoin = "round";
  ctx.lineCap = "round";
  for (let i = 1; i < samples.length; i++) {
    const a = samples[i - 1];
    const b = samples[i];
    const pa = point(a);
    const pb = point(b);
    ctx.beginPath();
    ctx.strokeStyle = adherenceColor(b.power, b.target);
    ctx.moveTo(pa.x, pa.y);
    ctx.lineTo(pb.x, pb.y);
    ctx.stroke();
  }

  const last = samples[samples.length - 1];
  const tip = point(last);
  ctx.fillStyle = adherenceColor(last.power, last.target);
  ctx.beginPath();
  ctx.arc(tip.x, tip.y, 3.5, 0, Math.PI * 2);
  ctx.fill();
}

/** Manual / fallback: power history only (−10m → now). */
function drawPowerOnlyChart() {
  const canvas = $("ride-chart");
  if (!canvas) return;
  const { ctx, cssW, cssH, padL, padR, padT, padB } = rideChartCanvasSetup(canvas);
  const plotW = cssW - padL - padR;
  const plotH = cssH - padT - padB;
  const now = state.historyActiveMs;
  const t0 = Math.max(0, now - HISTORY_WINDOW_MS);
  const span = Math.max(now - t0, 1);

  ctx.strokeStyle = "#d7e2ea";
  ctx.lineWidth = 1;
  ctx.beginPath();
  for (let i = 0; i <= 4; i++) {
    const y = padT + (plotH * i) / 4;
    ctx.moveTo(padL, y);
    ctx.lineTo(padL + plotW, y);
  }
  ctx.stroke();

  const samples = state.history.filter((s) => s.t >= t0);
  let maxW = 50;
  for (const s of samples) {
    maxW = Math.max(maxW, s.power || 0, s.target || 0);
  }
  maxW = Math.ceil(maxW / 50) * 50 || 50;

  ctx.fillStyle = "#8a9aa8";
  ctx.font = "10px 'Public Sans', system-ui, sans-serif";
  ctx.textAlign = "right";
  ctx.fillText(String(maxW), padL - 4, padT + 8);
  ctx.fillText("0", padL - 4, padT + plotH);

  if (samples.length >= 2) {
    ctx.beginPath();
    ctx.setLineDash([4, 4]);
    ctx.strokeStyle = "rgba(140, 158, 176, 0.55)";
    ctx.lineWidth = 1.5;
    let started = false;
    for (const s of samples) {
      if (!s.target) continue;
      const x = padL + ((s.t - t0) / span) * plotW;
      const y = padT + plotH - (s.target / maxW) * plotH;
      if (!started) {
        ctx.moveTo(x, y);
        started = true;
      } else ctx.lineTo(x, y);
    }
    if (started) ctx.stroke();
    ctx.setLineDash([]);
  }

  if (samples.length === 0) {
    ctx.fillStyle = "#8a9aa8";
    ctx.textAlign = "center";
    ctx.fillText("Waiting for ride data…", padL + plotW / 2, padT + plotH / 2);
  } else {
    drawPowerLineOnChart(ctx, samples, {
      padL,
      padT,
      plotW,
      plotH,
      maxW,
      tToX: (t) => padL + ((t - t0) / span) * plotW,
    });
  }

  setRideChartChrome({
    mode: "power",
    title: "Power · last 10 min",
    start: "−10m",
    mid: "−5m",
    end: "now",
    caption: "",
  });
}

function setRideChartChrome({ mode, title, start, mid, end, caption }) {
  const panel = $("ride-chart-panel");
  if (panel) panel.dataset.mode = mode || "power";
  if ($("ride-chart-title")) $("ride-chart-title").textContent = title;
  if ($("ride-chart-axis-start")) $("ride-chart-axis-start").textContent = start;
  if ($("ride-chart-axis-mid")) $("ride-chart-axis-mid").textContent = mid;
  if ($("ride-chart-axis-end")) $("ride-chart-axis-end").textContent = end;
  const cap = $("ride-structure-caption");
  if (cap) {
    cap.textContent = caption || "";
    cap.classList.toggle("hidden", !caption);
  }
}

function drawPowerHistory() {
  drawRideChart(state.live);
}

function sessionActive(live = state.live) {
  return ["running", "paused", "reconnecting", "loaded"].includes(
    live?.engine_state
  );
}

function updateSettingsBackNav() {
  const back = $("btn-settings-back");
  if (!back) return;
  if (sessionActive()) {
    back.textContent = "← Back to ride";
    back.setAttribute("data-nav", "ride");
  } else {
    back.textContent = "← Back";
    back.setAttribute("data-nav", "home");
  }
}

function show(view) {
  if (view === "ride") {
    state.suppressRideAutoNav = false;
  } else if (
    (view === "settings" || view === "home" || view === "preview") &&
    sessionActive()
  ) {
    state.suppressRideAutoNav = true;
  }
  state.view = view;
  ["home", "preview", "ride", "settings"].forEach((name) => {
    $(`view-${name}`).classList.toggle("hidden", name !== view);
  });
  updateSettingsBackNav();
  if (view === "ride") {
    requestAnimationFrame(() => drawRideChart(state.live));
    setEmulatorPanelVisible(state.emulator);
  } else {
    // Never leave the emulator panel/layout active off the ride screen
    setEmulatorPanelVisible(false);
  }
}

function fmtSec(s) {
  if (s == null || Number.isNaN(s)) return "—";
  const n = Math.max(0, Math.round(s));
  const m = Math.floor(n / 60);
  const r = n % 60;
  return `${m}:${String(r).padStart(2, "0")}`;
}

/** Stage/interval duration for workout lists — minutes, not raw seconds. */
function fmtMinutes(s) {
  if (s == null || Number.isNaN(s)) return "∞";
  const mins = Math.max(0, s) / 60;
  if (Math.abs(mins - Math.round(mins)) < 0.05) return `${Math.round(mins)} min`;
  return `${(Math.round(mins * 10) / 10).toFixed(1)} min`;
}

async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(opts.headers || {}) },
    ...opts,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    const detail = err.detail;
    const msg = Array.isArray(detail)
      ? detail.map((d) => d.msg || JSON.stringify(d)).join("; ")
      : detail || res.statusText;
    throw new Error(msg);
  }
  return res.json();
}

async function loadHome() {
  const st = await api("/api/status");
  state.emulator = !!st.emulator;
  state.trainerConnected = !!st.engine?.trainer_connected;
  state.hrSupported = !!st.hr_supported;
  state.hrConnected = !!st.hr_connected;
  updateTrainerChip();
  updateStartButtons();
  updateHrVisibility();
  updateHrConnectionButtons();
  try {
    const s = await api("/api/settings");
    if (s.ftp_w) state.ftpW = Number(s.ftp_w) || state.ftpW;
  } catch (_) {
    /* keep cached ftp */
  }
  const today = await api("/api/workouts/today");
  const item = today[0];
  const rideBtn = $("btn-ride-today");
  const previewBtn = $("btn-preview");
  const chartWrap = $("today-chart-wrap");
  const empty = $("today-empty");
  if (item) {
    state.workoutId = item.id;
    state.hasTodayWorkout = true;
    $("today-eyebrow").textContent = item.is_today !== false ? "Today · Garmin Coach" : "Workout";
    $("today-name").textContent = item.name;
    $("today-meta").textContent = [
      item.duration_s ? `${Math.round(item.duration_s / 60)} min` : null,
      item.sport || "cycling",
    ]
      .filter(Boolean)
      .join(" · ");
    previewBtn.disabled = false;
    rideBtn.disabled = !state.trainerConnected;
    rideBtn.textContent = `Ride ${item.name}`.slice(0, 28);
    if (empty) empty.classList.add("hidden");
    if (chartWrap) chartWrap.classList.remove("hidden");
    loadTodayChart(item.id).catch(() => {
      if (chartWrap) chartWrap.classList.add("hidden");
    });
  } else {
    state.workoutId = null;
    state.hasTodayWorkout = false;
    $("today-eyebrow").textContent = "Today";
    $("today-name").textContent = st.garmin_authenticated
      ? "No bike workout today"
      : "Log in to Garmin";
    $("today-meta").textContent = "";
    previewBtn.disabled = true;
    rideBtn.disabled = true;
    rideBtn.textContent = "Ride";
    if (chartWrap) chartWrap.classList.add("hidden");
    if (empty) {
      empty.classList.remove("hidden");
      empty.textContent = st.garmin_authenticated
        ? "Nothing cycling scheduled on the Garmin calendar for today."
        : "Open Settings and sign in to fetch today’s ride.";
    }
  }
  updateStartButtons();
  const lib = await api("/api/workouts");
  const tbody = $("library");
  tbody.innerHTML = "";
  if (!lib.length) {
    const tr = document.createElement("tr");
    tr.className = "empty-row";
    const td = document.createElement("td");
    td.colSpan = 4;
    td.textContent = st.garmin_authenticated
      ? "No cycling workouts in your Garmin library."
      : "Sign in to Garmin to load workouts.";
    tr.appendChild(td);
    tbody.appendChild(tr);
  } else {
    lib.forEach((w) => {
      const tr = document.createElement("tr");
      const nameTd = document.createElement("td");
      const name = document.createElement("span");
      name.className = "workout-name";
      name.textContent = w.name;
      nameTd.appendChild(name);
      if (w.is_today) {
        const badge = document.createElement("span");
        badge.className = "today-badge";
        badge.textContent = "Today";
        nameTd.appendChild(badge);
      }
      const srcTd = document.createElement("td");
      srcTd.textContent = w.is_today ? "Garmin Coach" : "Garmin";
      const durTd = document.createElement("td");
      durTd.textContent = w.duration_s
        ? `${Math.round(w.duration_s / 60)} min`
        : "—";
      const actTd = document.createElement("td");
      const open = document.createElement("button");
      open.type = "button";
      open.className = "btn ghost";
      open.textContent = "Open";
      open.onclick = () => {
        state.workoutId = w.id;
        openPreview();
      };
      actTd.appendChild(open);
      tr.appendChild(nameTd);
      tr.appendChild(srcTd);
      tr.appendChild(durTd);
      tr.appendChild(actTd);
      tbody.appendChild(tr);
    });
  }
  await loadSavedRides();
}

function fmtRideDate(iso) {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

function fmtRideTime(iso) {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleTimeString(undefined, {
    hour: "2-digit",
    minute: "2-digit",
  });
}

async function loadSavedRides() {
  const tbody = $("saved-rides");
  if (!tbody) return;
  tbody.innerHTML = "";
  let rides = [];
  let loadError = "";
  try {
    rides = await api("/api/rides");
  } catch (e) {
    rides = [];
    loadError = e.message || String(e);
  }
  if (loadError) {
    const tr = document.createElement("tr");
    tr.className = "empty-row";
    const td = document.createElement("td");
    td.colSpan = 5;
    td.textContent =
      "Saved rides unavailable — restart steadyGrind / kickr-pi, then reload this page.";
    tr.appendChild(td);
    tbody.appendChild(tr);
    return;
  }
  if (!rides.length) {
    const tr = document.createElement("tr");
    tr.className = "empty-row";
    const td = document.createElement("td");
    td.colSpan = 5;
    td.textContent = "No saved rides yet. Stop a Real or Emulator ride to save a FIT here.";
    tr.appendChild(td);
    tbody.appendChild(tr);
    return;
  }
  rides.forEach((ride) => {
    const tr = document.createElement("tr");
    tr.dataset.rideId = ride.id;
    const dateTd = document.createElement("td");
    dateTd.textContent = fmtRideDate(ride.started_at);
    const timeTd = document.createElement("td");
    timeTd.textContent = fmtRideTime(ride.started_at);
    const lenTd = document.createElement("td");
    lenTd.textContent = fmtSec(ride.duration_s);
    const avgTd = document.createElement("td");
    avgTd.textContent =
      ride.avg_power_w != null ? String(Math.round(ride.avg_power_w)) : "—";
    const actTd = document.createElement("td");
    actTd.className = "ride-actions";
    const download = document.createElement("a");
    download.className = "btn ghost";
    download.href = `/api/rides/${encodeURIComponent(ride.id)}/fit`;
    download.textContent = "Download";
    download.setAttribute("download", "");
    const del = document.createElement("button");
    del.type = "button";
    del.className = "btn ghost danger-text";
    del.textContent = "Delete";
    del.onclick = async () => {
      const ok = await appConfirm({
        title: "Delete ride?",
        body: "This removes the saved FIT file from this Mac.",
        confirmLabel: "Delete",
        cancelLabel: "Cancel",
        danger: true,
      });
      if (!ok) return;
      try {
        await api(`/api/rides/${encodeURIComponent(ride.id)}`, {
          method: "DELETE",
        });
        await loadSavedRides();
      } catch (e) {
        alert(e.message || String(e));
      }
    };
    actTd.appendChild(download);
    actTd.appendChild(del);
    tr.appendChild(dateTd);
    tr.appendChild(timeTd);
    tr.appendChild(lenTd);
    tr.appendChild(avgTd);
    tr.appendChild(actTd);
    tbody.appendChild(tr);
  });
}

async function loadTodayChart(workoutId) {
  const ftp = state.ftpW || 200;
  const w = await api(`/api/workouts/${workoutId}`);
  drawHomeProfileChart($("today-chart"), w.stages || [], ftp);
  const legend = $("today-chart-legend");
  if (!legend) return;
  const kinds = summarizeKinds(w.stages || []);
  legend.innerHTML = kinds
    .map(
      (k) =>
        `<span style="--swatch:${k.color}">${escapeHtml(k.label)}</span>`
    )
    .join("");
}

function summarizeKinds(stages) {
  const order = ["warmup", "interval", "recovery", "rest", "cooldown", "free"];
  const seen = new Map();
  for (const s of stages) {
    const kind = s.kind || "interval";
    const entry = seen.get(kind) || { kind, count: 0, dur: 0 };
    entry.count += 1;
    entry.dur += s.duration_s > 0 ? Number(s.duration_s) : 0;
    seen.set(kind, entry);
  }
  return order
    .filter((k) => seen.has(k))
    .map((k) => {
      const e = seen.get(k);
      const label =
        k === "interval" && e.count > 1
          ? `${e.count} × interval`
          : k === "warmup"
            ? `Warm-up ${fmtMinutes(e.dur)}`
            : k.charAt(0).toUpperCase() + k.slice(1);
      return { label, color: KIND_COLORS[k] || ZONE_COLORS[1] };
    });
}

function drawHomeProfileChart(canvas, stages, ftp) {
  if (!canvas || !stages.length) return;
  const built = buildPreviewSegments(stages, ftp);
  const dpr = window.devicePixelRatio || 1;
  const cssW = canvas.clientWidth || 320;
  const cssH = canvas.clientHeight || 150;
  canvas.width = Math.floor(cssW * dpr);
  canvas.height = Math.floor(cssH * dpr);
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, cssW, cssH);

  const padL = 4;
  const padR = 4;
  const padT = 8;
  const padB = 4;
  const plotW = cssW - padL - padR;
  const plotH = cssH - padT - padB;
  const maxW = built.maxW;
  const totalS = built.totalS;

  for (const seg of built.segments) {
    const x0 = padL + (seg.t0 / totalS) * plotW;
    const x1 = padL + (seg.t1 / totalS) * plotW;
    const yTop0 = padT + plotH * (1 - seg.startW / maxW);
    const yTop1 = padT + plotH * (1 - seg.endW / maxW);
    const yBase = padT + plotH;
    const kind = seg.stage.kind || "interval";
    const color = KIND_COLORS[kind] || ZONE_COLORS[(seg.zone || 2) - 1] || "#9ccbe5";
    ctx.beginPath();
    ctx.moveTo(x0, yBase);
    ctx.lineTo(x0, yTop0);
    ctx.lineTo(x1, yTop1);
    ctx.lineTo(x1, yBase);
    ctx.closePath();
    ctx.fillStyle = color;
    ctx.globalAlpha = 0.92;
    ctx.fill();
    ctx.globalAlpha = 1;
    ctx.strokeStyle = "rgba(255,255,255,0.65)";
    ctx.lineWidth = 1;
    ctx.stroke();
  }
}

async function openPreview() {
  if (!state.workoutId) return;
  const [w, s] = await Promise.all([
    api(`/api/workouts/${state.workoutId}`),
    api("/api/settings").catch(() => ({ ftp_w: state.ftpW })),
  ]);
  if (s.ftp_w) state.ftpW = Number(s.ftp_w) || state.ftpW;
  const ftp = state.ftpW || 200;

  $("preview-name").textContent = w.name;
  $("preview-meta").textContent = `${Math.round((w.total_s || 0) / 60)} min · ${w.stages.length} stages · FTP ${ftp} W`;

  state.preview = {
    stages: w.stages || [],
    ftp,
    totalS: Number(w.total_s) || 0,
    selected: 0,
    layout: null,
  };
  const legend = $("preview-zone-legend");
  if (legend) {
    legend.innerHTML = [
      `<span class="lz1">Z1</span>`,
      `<span class="lz2">Z2</span>`,
      `<span class="lz3">Z3</span>`,
      `<span class="lz4">Z4</span>`,
      `<span class="lz5">Z5</span>`,
      `<span class="lz6">Z6</span>`,
      `<span class="lz7">Z7</span>`,
    ].join("");
  }
  show("preview");
  updateStartButtons();
  requestAnimationFrame(() => {
    drawPreviewChart();
    renderPreviewStageDetail(0);
  });
}

/** Coggan-style upper bounds as fraction of FTP (Z1…Z7). */
const ZONE_UPPER = [0.55, 0.75, 0.9, 1.05, 1.2, 1.5, Infinity];
const ZONE_NAMES = [
  "Z1 Recovery",
  "Z2 Endurance",
  "Z3 Tempo",
  "Z4 Threshold",
  "Z5 VO2",
  "Z6 Anaerobic",
  "Z7 Neuromuscular",
];
const ZONE_COLORS = [
  "#a8b8c6",
  "#9ccbe5",
  "#5fa8d3",
  "#8d7cc2",
  "#6f5fbf",
  "#e07a55",
  "#b45cc8",
];
const KIND_COLORS = {
  warmup: "#5fa8d3",
  interval: "#8d7cc2",
  recovery: "#c2d3dd",
  rest: "#c2d3dd",
  cooldown: "#a9d8ea",
  free: "#9ccbe5",
};

function zoneForPctFtp(pct) {
  if (pct == null || !Number.isFinite(pct)) return null;
  for (let i = 0; i < ZONE_UPPER.length; i++) {
    if (pct < ZONE_UPPER[i]) return i + 1;
  }
  return 7;
}

function stageRepresentativeWatts(stage) {
  if (stage.target_mode === "ramp" && stage.start_w != null && stage.end_w != null) {
    return (Number(stage.start_w) + Number(stage.end_w)) / 2;
  }
  if (stage.target_w != null) return Number(stage.target_w);
  return null;
}

function formatStageTarget(stage) {
  if (stage.target_mode === "ramp") {
    return `${stage.start_w}→${stage.end_w} W`;
  }
  if (stage.target_w != null) return `${stage.target_w} W`;
  return "Free";
}

function stageDurationS(stage, fallbackS) {
  if (stage.duration_s != null && stage.duration_s > 0) return Number(stage.duration_s);
  return fallbackS;
}

function buildPreviewSegments(stages, ftp) {
  const openCount = stages.filter((s) => !(s.duration_s > 0)).length;
  const known = stages.reduce((sum, s) => sum + (s.duration_s > 0 ? Number(s.duration_s) : 0), 0);
  const openShare = openCount > 0 ? Math.max(120, known * 0.08 || 180) : 0;
  const segments = [];
  let t = 0;
  let maxW = Math.max(ftp * 1.05, 50);
  stages.forEach((stage, index) => {
    const dur = stageDurationS(stage, openShare);
    const startW =
      stage.target_mode === "ramp" && stage.start_w != null
        ? Number(stage.start_w)
        : stage.target_w != null
          ? Number(stage.target_w)
          : 0;
    const endW =
      stage.target_mode === "ramp" && stage.end_w != null
        ? Number(stage.end_w)
        : startW;
    maxW = Math.max(maxW, startW, endW);
    const watts = stageRepresentativeWatts(stage);
    const pct = watts != null && ftp > 0 ? watts / ftp : null;
    const zone = zoneForPctFtp(pct);
    segments.push({
      index,
      stage,
      t0: t,
      t1: t + dur,
      dur,
      startW,
      endW,
      watts,
      pct,
      zone,
    });
    t += dur;
  });
  return { segments, totalS: Math.max(t, 1), maxW: Math.ceil(maxW / 25) * 25 };
}

function renderPreviewStageDetail(index) {
  const detail = $("preview-stage-detail");
  const prev = state.preview;
  if (!detail || !prev?.segments) {
    if (detail) detail.innerHTML = `<p class="muted">Tap a stage on the chart for details</p>`;
    return;
  }
  const seg = prev.segments[index] ?? prev.segments[0];
  if (!seg) {
    detail.innerHTML = `<p class="muted">No stages in this workout</p>`;
    return;
  }
  prev.selected = seg.index;
  const zone = seg.zone;
  const zoneLabel = zone ? `Z${zone} · ${ZONE_NAMES[zone - 1]}` : "No power target";
  const pctText = seg.pct != null ? `${Math.round(seg.pct * 100)}% FTP` : "—";
  detail.innerHTML = `
    <div class="preview-detail-head">
      <span class="preview-detail-index">#${seg.index + 1}</span>
      <strong>${escapeHtml(seg.stage.name || `Stage ${seg.index + 1}`)}</strong>
      ${zone ? `<span class="zone-pill z${zone}">Z${zone}</span>` : ""}
    </div>
    <dl class="preview-detail-grid">
      <div><dt>Duration</dt><dd>${fmtMinutes(seg.stage.duration_s ?? seg.dur)}</dd></div>
      <div><dt>Target</dt><dd>${escapeHtml(formatStageTarget(seg.stage))}</dd></div>
      <div><dt>% FTP</dt><dd>${pctText}</dd></div>
      <div><dt>Zone</dt><dd>${escapeHtml(zoneLabel)}</dd></div>
    </dl>
  `;
}

function drawPreviewChart() {
  const canvas = $("preview-chart");
  const prev = state.preview;
  if (!canvas || !prev) return;

  const built = buildPreviewSegments(prev.stages, prev.ftp);
  prev.segments = built.segments;
  prev.totalS = built.totalS;

  const dpr = window.devicePixelRatio || 1;
  const cssW = canvas.clientWidth || 320;
  const cssH = canvas.clientHeight || 200;
  if (canvas.width !== Math.floor(cssW * dpr) || canvas.height !== Math.floor(cssH * dpr)) {
    canvas.width = Math.floor(cssW * dpr);
    canvas.height = Math.floor(cssH * dpr);
  }
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, cssW, cssH);

  const padL = 36;
  const padR = 10;
  const padT = 12;
  const padB = 8;
  const plotW = cssW - padL - padR;
  const plotH = cssH - padT - padB;
  const maxW = built.maxW;
  const totalS = built.totalS;

  // Grid + FTP line
  ctx.strokeStyle = "#d7e2ea";
  ctx.lineWidth = 1;
  ctx.beginPath();
  for (let i = 0; i <= 4; i++) {
    const y = padT + (plotH * i) / 4;
    ctx.moveTo(padL, y);
    ctx.lineTo(padL + plotW, y);
  }
  ctx.stroke();

  const ftpY = padT + plotH * (1 - Math.min(1, prev.ftp / maxW));
  ctx.strokeStyle = "rgba(31, 95, 133, 0.45)";
  ctx.setLineDash([4, 4]);
  ctx.beginPath();
  ctx.moveTo(padL, ftpY);
  ctx.lineTo(padL + plotW, ftpY);
  ctx.stroke();
  ctx.setLineDash([]);
  ctx.fillStyle = "#1f5f85";
  ctx.font = "10px 'Public Sans', system-ui, sans-serif";
  ctx.textAlign = "left";
  ctx.fillText("FTP", padL + 4, ftpY - 4);

  ctx.fillStyle = "#8a9aa8";
  ctx.textAlign = "right";
  ctx.fillText(String(maxW), padL - 4, padT + 8);
  ctx.fillText("0", padL - 4, padT + plotH);

  const layout = [];
  for (const seg of built.segments) {
    const x0 = padL + (seg.t0 / totalS) * plotW;
    const x1 = padL + (seg.t1 / totalS) * plotW;
    const yTop0 = padT + plotH * (1 - seg.startW / maxW);
    const yTop1 = padT + plotH * (1 - seg.endW / maxW);
    const yBase = padT + plotH;
    const color = seg.zone ? ZONE_COLORS[seg.zone - 1] : "#a8b8c6";
    const selected = seg.index === prev.selected;

    ctx.beginPath();
    ctx.moveTo(x0, yBase);
    ctx.lineTo(x0, yTop0);
    ctx.lineTo(x1, yTop1);
    ctx.lineTo(x1, yBase);
    ctx.closePath();
    ctx.fillStyle = color;
    ctx.globalAlpha = selected ? 0.95 : 0.72;
    ctx.fill();
    ctx.globalAlpha = 1;
    if (selected) {
      ctx.strokeStyle = "#0c2132";
      ctx.lineWidth = 2;
      ctx.stroke();
    } else {
      ctx.strokeStyle = "rgba(255, 255, 255, 0.55)";
      ctx.lineWidth = 1;
      ctx.stroke();
    }
    layout.push({ index: seg.index, x0, x1, yBase, yTop: Math.min(yTop0, yTop1) });
  }
  prev.layout = { padL, padR, padT, padB, plotW, plotH, cssW, cssH, hits: layout };

  const endEl = $("preview-axis-end");
  const midEl = $("preview-axis-mid");
  if ($("preview-axis-start")) $("preview-axis-start").textContent = "0:00";
  if (endEl) endEl.textContent = fmtSec(totalS);
  if (midEl) midEl.textContent = fmtSec(totalS / 2);
}

function previewHitIndex(clientX, clientY) {
  const canvas = $("preview-chart");
  const prev = state.preview;
  if (!canvas || !prev?.layout) return null;
  const rect = canvas.getBoundingClientRect();
  const x = clientX - rect.left;
  for (const hit of prev.layout.hits) {
    if (x >= hit.x0 && x <= hit.x1) return hit.index;
  }
  return null;
}

function onPreviewPointer(ev) {
  if ($("view-preview")?.classList.contains("hidden")) return;
  const idx = previewHitIndex(ev.clientX, ev.clientY);
  if (idx == null || !state.preview) return;
  if (state.preview.selected === idx) return;
  renderPreviewStageDetail(idx);
  drawPreviewChart();
}

function fmtRelMinutes(deltaS) {
  const sign = deltaS < 0 ? "−" : deltaS > 0 ? "+" : "";
  const abs = Math.abs(deltaS);
  const m = Math.floor(abs / 60);
  const s = Math.round(abs % 60);
  if (m === 0 && s === 0) return "now";
  if (s === 0) return `${sign}${m}m`;
  if (m === 0) return `${sign}${s}s`;
  return `${sign}${m}:${String(s).padStart(2, "0")}`;
}

function segmentWattsAt(seg, t) {
  if (!(seg.dur > 0)) return seg.startW;
  const u = Math.max(0, Math.min(1, (t - seg.t0) / seg.dur));
  return seg.startW + (seg.endW - seg.startW) * u;
}

function workoutNowS(live, segments) {
  if (!segments?.length) return Number(live.total_elapsed_s) || 0;
  const idx = Math.max(0, Math.min(segments.length - 1, Number(live.stage_index) || 0));
  let before = 0;
  for (let i = 0; i < idx; i++) before += segments[i].dur;
  return before + (Number(live.stage_elapsed_s) || 0);
}

function cacheRideProfileFromPreview(workoutId) {
  if (
    state.preview?.stages?.length &&
    state.workoutId &&
    String(state.workoutId) === String(workoutId)
  ) {
    state.rideProfile = {
      workoutId: String(workoutId),
      stages: state.preview.stages,
      ftp: state.preview.ftp || state.ftpW || 200,
    };
    return true;
  }
  return false;
}

let _rideStagesFetchId = null;
let _rideStagesFetch = null;

async function ensureRideStages(live) {
  if (!live || live.manual || !live.workout_id) {
    state.rideProfile = null;
    return null;
  }
  const wid = String(live.workout_id);
  if (state.rideProfile?.workoutId === wid && state.rideProfile.stages?.length) {
    return state.rideProfile;
  }
  if (cacheRideProfileFromPreview(wid)) return state.rideProfile;

  if (_rideStagesFetch && _rideStagesFetchId === wid) {
    return _rideStagesFetch;
  }
  _rideStagesFetchId = wid;
  _rideStagesFetch = (async () => {
    try {
      const w = await api(`/api/workouts/${encodeURIComponent(wid)}`);
      if (String(state.live?.workout_id || live.workout_id) !== wid) return null;
      state.rideProfile = {
        workoutId: wid,
        stages: w.stages || [],
        ftp: state.ftpW || 200,
      };
      return state.rideProfile;
    } catch (_) {
      if (state.rideProfile?.workoutId === wid) return state.rideProfile;
      state.rideProfile = null;
      return null;
    } finally {
      if (_rideStagesFetchId === wid) {
        _rideStagesFetchId = null;
        _rideStagesFetch = null;
      }
    }
  })();
  return _rideStagesFetch;
}

function drawRideOverlayChart(live) {
  const canvas = $("ride-chart");
  const profile = state.rideProfile;
  if (!canvas || !profile?.stages?.length || !live) {
    drawPowerOnlyChart();
    return;
  }

  const ftp = profile.ftp || state.ftpW || 200;
  const built = buildPreviewSegments(profile.stages, ftp);
  const nowS = workoutNowS(live, built.segments);
  const winStart = Math.max(0, nowS - RIDE_STRUCT_PAST_S);
  const winEnd = Math.min(built.totalS, nowS + RIDE_STRUCT_AHEAD_S);
  const winSpan = Math.max(winEnd - winStart, 1);

  const { ctx, cssW, cssH, padL, padR, padT, padB } = rideChartCanvasSetup(canvas);
  const plotW = cssW - padL - padR;
  const plotH = cssH - padT - padB;
  const stageIdx = Number(live.stage_index) || 0;

  // Map power samples (historyActiveMs) onto workout seconds around nowS
  const histNow = state.historyActiveMs;
  const powerSamples = state.history
    .map((s) => {
      const workoutT = nowS - (histNow - s.t) / 1000;
      return { ...s, t: workoutT };
    })
    .filter((s) => s.t >= winStart && s.t <= nowS + 0.05);

  let maxW = built.maxW;
  for (const s of powerSamples) {
    maxW = Math.max(maxW, s.power || 0, s.target || 0);
  }
  maxW = Math.ceil(maxW / 25) * 25 || 50;

  ctx.strokeStyle = "#d7e2ea";
  ctx.lineWidth = 1;
  ctx.beginPath();
  for (let i = 0; i <= 4; i++) {
    const y = padT + (plotH * i) / 4;
    ctx.moveTo(padL, y);
    ctx.lineTo(padL + plotW, y);
  }
  ctx.stroke();

  const ftpY = padT + plotH * (1 - Math.min(1, ftp / maxW));
  ctx.strokeStyle = "rgba(31, 95, 133, 0.45)";
  ctx.setLineDash([4, 4]);
  ctx.beginPath();
  ctx.moveTo(padL, ftpY);
  ctx.lineTo(padL + plotW, ftpY);
  ctx.stroke();
  ctx.setLineDash([]);
  ctx.fillStyle = "#1f5f85";
  ctx.font = "10px 'Public Sans', system-ui, sans-serif";
  ctx.textAlign = "left";
  ctx.fillText("FTP", padL + 4, Math.max(padT + 10, ftpY - 4));

  ctx.fillStyle = "#8a9aa8";
  ctx.textAlign = "right";
  ctx.fillText(String(maxW), padL - 4, padT + 8);
  ctx.fillText("0", padL - 4, padT + plotH);

  const xAt = (t) => padL + ((t - winStart) / winSpan) * plotW;
  const yAt = (w) => padT + plotH * (1 - w / maxW);
  const yBase = padT + plotH;

  // Structure (underlay)
  for (const seg of built.segments) {
    if (seg.t1 <= winStart || seg.t0 >= winEnd) continue;
    const t0 = Math.max(seg.t0, winStart);
    const t1 = Math.min(seg.t1, winEnd);
    if (t1 <= t0) continue;
    const w0 = segmentWattsAt(seg, t0);
    const w1 = segmentWattsAt(seg, t1);
    const color = seg.zone ? ZONE_COLORS[seg.zone - 1] : "#a8b8c6";
    const selected = seg.index === stageIdx;

    ctx.beginPath();
    ctx.moveTo(xAt(t0), yBase);
    ctx.lineTo(xAt(t0), yAt(w0));
    ctx.lineTo(xAt(t1), yAt(w1));
    ctx.lineTo(xAt(t1), yBase);
    ctx.closePath();
    ctx.fillStyle = color;
    ctx.globalAlpha = selected ? 0.55 : 0.38;
    ctx.fill();
    ctx.globalAlpha = 1;
    ctx.strokeStyle = selected ? "rgba(12, 33, 50, 0.55)" : "rgba(255, 255, 255, 0.4)";
    ctx.lineWidth = selected ? 1.5 : 1;
    ctx.stroke();
  }

  // Soft veil on the past so the power line reads clearly
  const nowX = xAt(Math.max(winStart, Math.min(winEnd, nowS)));
  if (nowX > padL) {
    ctx.fillStyle = "rgba(255, 255, 255, 0.18)";
    ctx.fillRect(padL, padT, nowX - padL, plotH);
  }

  // Actual power (overlay on past / now)
  drawPowerLineOnChart(ctx, powerSamples, {
    padL,
    padT,
    plotW,
    plotH,
    maxW,
    tToX: (t) => xAt(t),
  });

  // Now marker
  ctx.strokeStyle = "#0c2132";
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.moveTo(nowX, padT);
  ctx.lineTo(nowX, padT + plotH);
  ctx.stroke();
  ctx.fillStyle = "#0c2132";
  ctx.beginPath();
  ctx.moveTo(nowX, padT);
  ctx.lineTo(nowX - 4, padT - 6);
  ctx.lineTo(nowX + 4, padT - 6);
  ctx.closePath();
  ctx.fill();

  const cur = built.segments[stageIdx];
  const next = built.segments[stageIdx + 1];
  const parts = [];
  if (cur) parts.push(cur.stage.name || `Stage ${stageIdx + 1}`);
  if (next) parts.push(`→ ${next.stage.name || `Stage ${stageIdx + 2}`}`);

  setRideChartChrome({
    mode: "overlay",
    title: "Structure + power · −2m to +8m",
    start: fmtRelMinutes(winStart - nowS),
    mid: "now",
    end: fmtRelMinutes(winEnd - nowS),
    caption: parts.join(" "),
  });
}

function drawRideChart(live) {
  const active = ["running", "paused", "reconnecting", "loaded"].includes(
    live?.engine_state
  );
  if (!live || !active || live.manual || !live.workout_id) {
    if (live?.manual) state.rideProfile = null;
    drawPowerOnlyChart();
    return;
  }

  const wid = String(live.workout_id);
  if (state.rideProfile?.workoutId === wid && state.rideProfile.stages?.length) {
    drawRideOverlayChart(live);
    return;
  }

  drawPowerOnlyChart();
  ensureRideStages(live).then((profile) => {
    if (!profile || String(state.live?.workout_id) !== wid) return;
    if ($("view-ride")?.classList.contains("hidden")) return;
    drawRideOverlayChart(state.live || live);
  });
}

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function updateStartButtons() {
  const connected = !!state.trainerConnected;
  const manualBtn = $("btn-manual-start");
  const startBtn = $("btn-start");
  const rideToday = $("btn-ride-today");
  const manualStatus = $("manual-status");
  if (manualBtn) {
    manualBtn.disabled = !connected;
    manualBtn.title = connected
      ? ""
      : "Connect a trainer (or enable Emulator) in Settings";
  }
  if (startBtn) {
    startBtn.disabled = !connected;
    startBtn.title = connected
      ? ""
      : "Connect a trainer (or enable Emulator) in Settings";
  }
  if (rideToday) {
    rideToday.disabled = !connected || !state.hasTodayWorkout;
  }
  if (manualStatus && !manualBtn?.dataset.busy) {
    if (!connected) {
      manualStatus.textContent = state.emulator
        ? "Emulator is off — turn it on in Settings to start."
        : "Trainer is off — connect in Settings to start.";
    } else if (manualStatus.textContent.includes("Trainer is off") ||
               manualStatus.textContent.includes("Emulator is off")) {
      manualStatus.textContent = "";
    }
  }
  updateTrainerConnectionButtons();
  updateHrConnectionButtons();
}

function updateHrVisibility() {
  $("hr-settings")?.classList.toggle("hidden", !state.hrSupported);
  $("ride-hr-wrap")?.classList.toggle("hidden", !state.hrSupported);
}

/** Discover / Connect enabled while offline; Disconnect only while linked. */
function updateHrConnectionButtons() {
  const discover = $("btn-hr-discover");
  const connect = $("btn-hr-connect");
  const disconnect = $("btn-hr-disconnect");
  const select = $("set-hr-device");
  if (!discover || !connect || !disconnect) return;
  if (!state.hrSupported) return;
  const connected = !!state.hrConnected;
  discover.disabled = connected;
  connect.disabled = connected;
  disconnect.disabled = !connected;
  if (select) select.disabled = connected;
  discover.title = connected ? "Disconnect before scanning again" : "Scan for a heart-rate strap";
  connect.title = connected ? "Already connected" : "Connect to the strap selected above";
  disconnect.title = connected ? "Drop the heart-rate strap" : "Not connected";
}

function setHrDeviceOptions(devices, selectedId) {
  const sel = $("set-hr-device");
  if (!sel) return;
  const current = selectedId || sel.value || "";
  sel.innerHTML = "";
  const list = Array.isArray(devices) ? devices.filter((d) => d && d.device_id) : [];
  if (!list.length) {
    const opt = document.createElement("option");
    opt.value = "";
    opt.textContent = "Discover to find a strap";
    sel.appendChild(opt);
    return;
  }
  for (const device of list) {
    const opt = document.createElement("option");
    opt.value = device.device_id;
    opt.textContent = device.name || device.device_id;
    sel.appendChild(opt);
  }
  const match = list.some((d) => d.device_id === current);
  sel.value = match ? current : list[0].device_id;
}

function selectedHrDevice() {
  const sel = $("set-hr-device");
  if (!sel || !sel.value) return { device_id: null, name: null };
  const opt = sel.selectedOptions && sel.selectedOptions[0];
  return {
    device_id: sel.value,
    name: opt ? opt.textContent : null,
  };
}

/** Discover / Connect / Disconnect follow Real KICKR connection state. */
function updateTrainerConnectionButtons() {
  const discover = $("btn-discover");
  const connect = $("btn-connect");
  const disconnect = $("btn-disconnect");
  if (!discover || !connect || !disconnect) return;

  const real = !state.emulator;
  const connected = !!state.trainerConnected;

  if (real) {
    discover.disabled = false;
    discover.title = "Search the LAN for a KICKR (mDNS)";
    connect.disabled = connected;
    connect.title = connected
      ? "Already connected — Disconnect first to reconnect"
      : "Connect to the host/port above";
    disconnect.disabled = !connected;
    disconnect.title = connected
      ? "Drop Direct Connect so other apps can use the trainer"
      : "Not connected";
  } else {
    // Emulator: DirCon Discover/Connect do not apply
    discover.disabled = true;
    discover.title = "Switch to Real KICKR to discover";
    connect.disabled = true;
    connect.title = "Switch to Real KICKR to connect";
    disconnect.disabled = !connected;
    disconnect.title = connected
      ? "Disconnect Emulator (Start will be disabled until reconnected)"
      : "Emulator not connected";
  }
}

async function startRide(payload) {
  resetPowerHistory();
  state.historySession = "active";
  const wid = payload?.workoutId || payload?.workout_id;
  if (wid && wid !== "manual") {
    cacheRideProfileFromPreview(wid);
  } else {
    state.rideProfile = null;
  }
  const live = await api("/api/session", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  if (live?.live) renderLive(live.live);
  show("ride");
  enableWakeLock();
  return live;
}

async function command(cmd) {
  const res = await api("/api/session/command", {
    method: "POST",
    body: JSON.stringify({ command: cmd }),
  });
  if (res?.live) renderLive(res.live);
  return res;
}

function setManualUi(isManual) {
  $("manual-controls").classList.toggle("hidden", !isManual);
  $("manual-session-controls").classList.toggle("hidden", !isManual);
  $("structured-controls").classList.toggle("hidden", isManual);
  $("ride-intensity").classList.toggle("hidden", isManual);
}

function updateTrainerChip() {
  const trainer = $("chip-trainer");
  if (!trainer) return;
  const connected = !!state.trainerConnected;
  if (state.emulator) {
    trainer.textContent = connected ? "Emulator connected" : "Emulator off";
  } else {
    trainer.textContent = connected ? "Trainer connected" : "Trainer off";
  }
  // Connected = ok (theme pill); disconnected = bad
  trainer.className = `chip ${connected ? "ok" : "bad"}`;
}

function renderLive(live, meta = {}) {
  state.live = live;
  if (typeof meta.emulator === "boolean") {
    state.emulator = meta.emulator;
  }
  state.trainerConnected = !!live.trainer_connected;
  if (typeof live.hr_connected === "boolean") {
    state.hrConnected = live.hr_connected;
  }
  updateStartButtons();
  updateTrainerChip();
  updateHrConnectionButtons();
  $("chip-engine").textContent = live.engine_state
    ? String(live.engine_state).charAt(0).toUpperCase() + String(live.engine_state).slice(1)
    : "Idle";

  if (!sessionActive(live)) {
    state.suppressRideAutoNav = false;
  } else if (!state.suppressRideAutoNav && state.view !== "ride") {
    // Enter ride on reload / remote session start — never yank away from Settings.
    show("ride");
  }
  updateSettingsBackNav();
  // Panel only when Emulator mode is on *and* ride is visible
  setEmulatorPanelVisible(state.emulator);

  const isManual = !!live.manual;
  setManualUi(isManual);

  $("ride-stage-label").textContent = isManual
    ? `Manual ERG · ${live.stage_name || "Hold"}`
    : `${live.stage_name} (${live.stage_index + 1}/${live.stage_count || 1})`;
  $("ride-target").textContent = live.target_w ?? "—";
  if (isManual && document.activeElement !== $("ride-set-watts")) {
    $("ride-set-watts").value = live.target_w ?? state.manualWatts;
  }
  const powerEl = $("ride-power");
  powerEl.textContent = live.power_w ?? "—";
  powerEl.className = "value";
  if (live.target_w && live.power_w != null) {
    const pct = Math.abs(live.power_w - live.target_w) / Math.max(live.target_w, 1);
    if (pct <= 0.05) powerEl.classList.add("good");
    else if (pct > 0.1) powerEl.classList.add("warn");
  }
  $("ride-cadence").textContent =
    live.cadence_rpm != null ? Math.round(live.cadence_rpm) : "—";
  const hrEl = $("ride-hr");
  if (hrEl) {
    hrEl.textContent =
      live.heart_rate_bpm != null ? String(live.heart_rate_bpm) : "—";
  }
  $("ride-stage-left").textContent = isManual
    ? fmtSec(live.total_elapsed_s)
    : fmtSec(live.stage_remaining_s);
  $("ride-total-left").textContent = isManual
    ? "∞"
    : fmtSec(live.total_remaining_s);
  $("ride-next").textContent = live.next_stage_name
    ? `Next: ${live.next_stage_name}`
    : isManual
      ? "Change watts below anytime"
      : "";
  if (live.engine_state === "paused" && live.message) {
    $("ride-next").textContent = live.message;
  }
  $("ride-intensity").textContent = `Intensity ${live.intensity_pct}%`;
  $("btn-pause").textContent =
    live.engine_state === "paused" ? "Resume" : "Pause";
  $("btn-pause-m").textContent =
    live.engine_state === "paused" ? "Resume" : "Pause";

  pushHistory(live);
  drawRideChart(live);

  // Workout ended on the host (natural finish or remote stop) — drop the lock
  if (
    state.wakeLockWanted &&
    (live.engine_state === "idle" || live.engine_state === "finished")
  ) {
    releaseWakeLock();
  }
}

function connectWs() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${location.host}/ws/live`);
  ws.onmessage = (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.type === "tick") {
      renderLive(msg.data, { emulator: msg.emulator });
    }
  };
  ws.onclose = () => setTimeout(connectWs, 1500);
}

function enableWakeLock() {
  state.wakeLockWanted = true;
  requestWakeLock();
}

async function requestWakeLock() {
  if (!state.wakeLockWanted) return;
  if (!("wakeLock" in navigator)) return;
  if (document.visibilityState !== "visible") return;
  if (state.wakeLock) return;
  try {
    const lock = await navigator.wakeLock.request("screen");
    state.wakeLock = lock;
    lock.addEventListener("release", () => {
      state.wakeLock = null;
      if (state.wakeLockWanted && document.visibilityState === "visible") {
        requestWakeLock();
      }
    });
  } catch (_) {
    /* ignore — insecure context, permission denied, etc. */
  }
}

async function releaseWakeLock() {
  state.wakeLockWanted = false;
  try {
    if (state.wakeLock) {
      await state.wakeLock.release();
      state.wakeLock = null;
    }
  } catch (_) {
    state.wakeLock = null;
  }
}

document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible" && state.wakeLockWanted) {
    requestWakeLock();
  }
});

async function refreshEmulatorStatus() {
  const panel = $("emulator-panel");
  const statusEl = $("emu-status");
  if (!panel || panel.classList.contains("hidden") || !statusEl) return;
  try {
    const st = await api("/api/emulator/status");
    statusEl.textContent = [
      `Power ${st.power_w ?? 0} W`,
      `target ${st.target_w ?? 0} W`,
      st.paused ? "paused" : "running",
      st.desk_hold ? "desk hold" : "follow ERG",
      st.preset_name ? `preset ${st.preset_name}` : null,
    ]
      .filter(Boolean)
      .join(" · ");
  } catch (e) {
    statusEl.textContent = e.message || String(e);
  }
}

let emulatorPollId = null;

function stopEmulatorPoll() {
  if (emulatorPollId != null) {
    clearInterval(emulatorPollId);
    emulatorPollId = null;
  }
}

function setEmulatorPanelVisible(showPanel) {
  const panel = $("emulator-panel");
  const ride = $("view-ride");
  if (!panel) return;
  const onRide = !!(ride && !ride.classList.contains("hidden"));
  // Strict: only show when Emulator mode is on and the ride view is active
  const visible = !!showPanel && !!state.emulator && onRide;
  panel.classList.toggle("hidden", !visible);
  if (ride) ride.classList.toggle("emu-on", visible);
  stopEmulatorPoll();
  if (visible) {
    refreshEmulatorStatus();
    emulatorPollId = setInterval(refreshEmulatorStatus, 1000);
  }
}

async function loadSettings() {
  const [s, st] = await Promise.all([api("/api/settings"), api("/api/status")]);
  state.emulator = !!st.emulator;
  state.trainerConnected = !!st.engine?.trainer_connected;
  state.hrSupported = !!st.hr_supported;
  state.hrConnected = !!st.hr_connected;
  updateTrainerChip();
  updateStartButtons();
  updateHrVisibility();
  updateHrConnectionButtons();
  $("set-ftp").value = s.ftp_w;
  if (s.ftp_w) state.ftpW = Number(s.ftp_w) || state.ftpW;
  $("set-host").value = s.trainer_host || "";
  $("set-port").value = s.trainer_port;
  $("set-trainer-mode").value =
    s.trainer_mode === "simulated" ? "simulated" : "dircon";
  const autoEl = $("set-auto-connect");
  if (autoEl) {
    autoEl.checked = s.auto_connect !== false;
    autoEl.disabled = !!state.emulator;
  }
  const autoWrap = $("auto-connect-wrap");
  if (autoWrap) {
    autoWrap.classList.toggle("disabled", !!state.emulator);
    autoWrap.title = state.emulator
      ? "Autoconnect applies to Real KICKR mode"
      : "";
  }
  setEmulatorPanelVisible(state.emulator);
  if (st.garmin_authenticated) {
    $("garmin-status").textContent = `Logged in as ${st.garmin_display_name || "Garmin user"}`;
    $("garmin-mfa-wrap").classList.add("hidden");
  } else {
    $("garmin-status").textContent = "Not logged in";
  }
  const hrAuto = $("set-hr-auto-connect");
  if (hrAuto) hrAuto.checked = s.hr_auto_connect !== false;
  if (s.hr_device_id) {
    setHrDeviceOptions(
      [{ device_id: s.hr_device_id, name: s.hr_device_name || s.hr_device_id }],
      s.hr_device_id,
    );
  }
  if (state.hrSupported && $("hr-out") && !$("hr-out").textContent) {
    $("hr-out").textContent = st.hr_connected
      ? `Connected to ${s.hr_device_name || s.hr_device_id || "heart rate monitor"}.`
      : "Not connected.";
  }
  if (st.engine?.trainer_connected) {
    const ep = st.trainer_endpoint
      ? `${st.trainer_endpoint.host}:${st.trainer_endpoint.port}`
      : `${s.trainer_host}:${s.trainer_port}`;
    $("discover-out").textContent = state.emulator
      ? `Emulator connected (${ep}).`
      : `Already connected to ${ep} (Direct Connect is 1:1 — no need to Connect again).`;
  } else if (state.emulator) {
    $("discover-out").textContent = "Emulator mode is on — ride controls drive simulated power.";
  }
}

$("btn-garmin-login").onclick = async () => {
  const msg = $("garmin-msg");
  const btn = $("btn-garmin-login");
  btn.disabled = true;
  msg.textContent = "Signing in to Garmin…";
  try {
    const body = {
      email: $("garmin-email").value.trim(),
      password: $("garmin-password").value,
      mfa: $("garmin-mfa").value.trim() || null,
    };
    if (!body.email || !body.password) {
      throw new Error("Enter Garmin email and password.");
    }
    const res = await api("/api/garmin/login", {
      method: "POST",
      body: JSON.stringify(body),
    });
    if (res.needs_mfa) {
      $("garmin-mfa-wrap").classList.remove("hidden");
      msg.textContent = "Enter the MFA code from your email/authenticator, then Log in again.";
      $("garmin-mfa").focus();
      return;
    }
    $("garmin-mfa-wrap").classList.add("hidden");
    $("garmin-password").value = "";
    $("garmin-mfa").value = "";
    msg.textContent = `Signed in${res.display_name ? ` as ${res.display_name}` : ""}.`;
    await loadSettings();
    await loadHome();
  } catch (e) {
    msg.textContent = e.message || String(e);
  } finally {
    btn.disabled = false;
  }
};

$("btn-garmin-logout").onclick = async () => {
  await api("/api/garmin/logout", { method: "POST" });
  $("garmin-msg").textContent = "Logged out.";
  $("garmin-mfa-wrap").classList.add("hidden");
  await loadSettings();
  await loadHome();
};

document.querySelectorAll("[data-nav]").forEach((el) => {
  el.addEventListener("click", async () => {
    const view = el.getAttribute("data-nav");
    show(view);
    if (view === "settings") await loadSettings();
    if (view === "home") await loadHome();
  });
});

$("btn-manual-start").onclick = async () => {
  const status = $("manual-status");
  const btn = $("btn-manual-start");
  if (!state.trainerConnected) {
    status.textContent = "Trainer is off — connect in Settings to start.";
    return;
  }
  const watts = Number($("manual-watts").value);
  if (!Number.isFinite(watts) || watts < 0) {
    status.textContent = "Enter a valid watt target.";
    return;
  }
  state.manualWatts = watts;
  btn.disabled = true;
  btn.dataset.busy = "1";
  status.textContent = `Starting manual ERG at ${watts} W…`;
  try {
    await startRide({ workoutId: "manual", targetW: Math.round(watts) });
    status.textContent = "";
  } catch (e) {
    status.textContent = e.message || String(e);
    alert(e.message || String(e));
  } finally {
    delete btn.dataset.busy;
    updateStartButtons();
  }
};

$("btn-preview").onclick = openPreview;

function nudgeManualWatts(delta) {
  const input = $("manual-watts");
  if (!input) return;
  const cur = Number(input.value) || 0;
  input.value = String(Math.max(0, Math.min(2000, cur + delta)));
}
$("btn-manual-minus").onclick = () => nudgeManualWatts(-5);
$("btn-manual-plus").onclick = () => nudgeManualWatts(5);

$("btn-ride-today").onclick = () => {
  if (!state.workoutId || !state.trainerConnected) {
    alert("Trainer is off — connect in Settings (or enable Emulator) to start.");
    return;
  }
  startRide({ workoutId: state.workoutId }).catch((e) => alert(e.message));
};

$("btn-start").onclick = () => {
  if (!state.trainerConnected) {
    alert("Trainer is off — connect in Settings (or enable Emulator) to start.");
    return;
  }
  if (!state.workoutId) {
    alert("No workout selected.");
    return;
  }
  startRide({ workoutId: state.workoutId }).catch((e) => alert(e.message));
};
function bindPauseStop(pauseId, stopId) {
  $(pauseId).onclick = () => {
    const cmd = state.live?.engine_state === "paused" ? "resume" : "pause";
    command(cmd).catch((e) => alert(e.message));
  };
  $(stopId).onclick = async () => {
    const leave = await showWorkoutSummary();
    if (!leave) return;
    try {
      const elapsed = state.live?.total_elapsed_s ?? 0;
      const res = await command("stop");
      if (elapsed >= 1 && !res?.saved_ride) {
        console.warn("stop completed without saved_ride", res);
        alert(
          "This ride was not saved as a FIT. Restart steadyGrind / kickr-pi and try again.",
        );
      }
      await releaseWakeLock();
      state.historySession = null;
      resetPowerHistory();
      show("home");
      await loadHome();
    } catch (e) {
      alert(e.message);
    }
  };
}
bindPauseStop("btn-pause", "btn-stop");
bindPauseStop("btn-pause-m", "btn-stop-m");

function showWorkoutSummary() {
  const elapsed = state.live?.total_elapsed_s ?? state.historyActiveMs / 1000;
  const avg = sessionAverageWatts();
  $("summary-elapsed").textContent = fmtSec(elapsed);
  $("summary-avg-watts").textContent = avg != null ? `${avg} W` : "—";
  return appConfirm({
    title: "Workout summary",
    body: "",
    confirmLabel: "Back to main screen",
    cancelLabel: "Back to workout",
    danger: true,
    showSummary: true,
  });
}

function appConfirm({
  title = "Confirm",
  body = "",
  confirmLabel = "OK",
  cancelLabel = "Cancel",
  danger = false,
  showSummary = false,
} = {}) {
  const dialog = $("app-dialog");
  const titleEl = $("app-dialog-title");
  const bodyEl = $("app-dialog-body");
  const summaryEl = $("app-dialog-summary");
  const confirmBtn = $("app-dialog-confirm");
  const cancelBtn = $("app-dialog-cancel");
  const actions = dialog?.querySelector(".app-dialog-actions");
  if (!dialog || !confirmBtn || !cancelBtn) {
    return Promise.resolve(window.confirm(title));
  }

  titleEl.textContent = title;
  bodyEl.textContent = body || "";
  bodyEl.classList.toggle("hidden", !body);
  if (summaryEl) summaryEl.classList.toggle("hidden", !showSummary);
  if (actions) actions.classList.toggle("app-dialog-actions-stack", !!showSummary);
  confirmBtn.textContent = confirmLabel;
  cancelBtn.textContent = cancelLabel;
  confirmBtn.classList.toggle("danger", !!danger);
  confirmBtn.classList.toggle("primary", !danger);
  cancelBtn.classList.toggle("primary", !!showSummary);
  dialog.classList.remove("hidden");
  (showSummary ? cancelBtn : confirmBtn).focus();

  return new Promise((resolve) => {
    const finish = (result) => {
      dialog.classList.add("hidden");
      dialog.removeEventListener("click", onClick);
      document.removeEventListener("keydown", onKey);
      resolve(result);
    };
    const onClick = (ev) => {
      const t = ev.target;
      if (t === confirmBtn || t?.id === "app-dialog-confirm") finish(true);
      else if (
        t === cancelBtn ||
        t?.id === "app-dialog-cancel" ||
        t?.hasAttribute?.("data-dialog-cancel")
      ) {
        finish(false);
      }
    };
    const onKey = (ev) => {
      if (ev.key === "Escape") finish(false);
    };
    dialog.addEventListener("click", onClick);
    document.addEventListener("keydown", onKey);
  });
}

$("btn-skip").onclick = () => command("skip").catch((e) => alert(e.message));
$("btn-prev").onclick = () => command("previous").catch((e) => alert(e.message));
$("btn-minus").onclick = () => command("-5").catch((e) => alert(e.message));
$("btn-plus").onclick = () => command("+5").catch((e) => alert(e.message));

$("btn-set-watts").onclick = () => {
  const watts = Number($("ride-set-watts").value);
  if (!Number.isFinite(watts) || watts < 0) {
    alert("Enter a valid watt target");
    return;
  }
  command(`target:${Math.round(watts)}`).catch((e) => alert(e.message));
};

document.querySelectorAll("[data-watts]").forEach((btn) => {
  btn.addEventListener("click", () => {
    const delta = Number(btn.getAttribute("data-watts"));
    const sign = delta > 0 ? `+${delta}` : String(delta);
    command(`target:${sign}`).catch((e) => alert(e.message));
  });
});

function closeHelpDialog() {
  const dialog = $("help-dialog");
  if (!dialog) return;
  dialog.classList.add("hidden");
  document.removeEventListener("keydown", onHelpDialogKey);
}

function onHelpDialogKey(ev) {
  if (ev.key === "Escape") closeHelpDialog();
}

function openHelpDialog() {
  const dialog = $("help-dialog");
  if (!dialog) return;
  dialog.classList.remove("hidden");
  document.addEventListener("keydown", onHelpDialogKey);
  $("btn-help-dialog-close")?.focus();
}

$("btn-help-garmin-record")?.addEventListener("click", openHelpDialog);
$("btn-help-dialog-close")?.addEventListener("click", closeHelpDialog);
$("help-dialog")?.addEventListener("click", (ev) => {
  if (ev.target?.hasAttribute?.("data-help-dialog-close")) closeHelpDialog();
});

$("btn-save").onclick = async () => {
  const mode = $("set-trainer-mode").value;
  const ftp = Number($("set-ftp").value);
  if (Number.isFinite(ftp) && ftp > 0) state.ftpW = ftp;
  const body = {
    ftp_w: Number($("set-ftp").value),
    trainer_mode: mode,
    allow_simulated: mode === "simulated",
    trainer_host: $("set-host").value || null,
    trainer_port: Number($("set-port").value),
    auto_connect: !!$("set-auto-connect")?.checked,
  };
  if (state.hrSupported) {
    const hr = selectedHrDevice();
    body.hr_auto_connect = !!$("set-hr-auto-connect")?.checked;
    if (hr.device_id) {
      body.hr_device_id = hr.device_id;
      body.hr_device_name = hr.name;
    }
  }
  await api("/api/settings", {
    method: "PUT",
    body: JSON.stringify(body),
  });
  alert("Saved. Use Apply mode to switch Real/Emulator without restart.");
  await loadSettings();
  updateStartButtons();
};

$("btn-apply-mode").onclick = async () => {
  const msg = $("mode-msg");
  const mode = $("set-trainer-mode").value;
  msg.textContent = "Switching trainer mode…";
  try {
    const res = await api("/api/trainer/mode", {
      method: "POST",
      body: JSON.stringify({ mode }),
    });
    state.emulator = !!res.emulator && mode === "simulated";
    state.trainerConnected = !!res.connected;
    updateTrainerChip();
    updateStartButtons();
    // Hide immediately when switching to Real KICKR; show only on ride if Emulator
    setEmulatorPanelVisible(state.emulator);
    const autoEl = $("set-auto-connect");
    if (autoEl) {
      autoEl.disabled = !!state.emulator;
    }
    const autoWrap = $("auto-connect-wrap");
    if (autoWrap) {
      autoWrap.classList.toggle("disabled", !!state.emulator);
      autoWrap.title = state.emulator
        ? "Autoconnect applies to Real KICKR mode"
        : "";
    }
    const label = mode === "simulated" ? "Emulator" : "Real KICKR";
    if (res.unchanged) {
      msg.textContent = `Already on ${label}.`;
    } else if (mode === "simulated") {
      msg.textContent = "Emulator on — open a ride to drive power from the training page.";
    } else {
      msg.textContent = res.connected
        ? "Switched to Real KICKR (connected)."
        : "Switched to Real KICKR (offline — use Discover/Connect when the bike is on).";
    }
  } catch (e) {
    msg.textContent = e.message || String(e);
  }
};

$("btn-emu-target").onclick = async () => {
  const watts = Number($("emu-watts").value);
  if (!Number.isFinite(watts) || watts < 0) {
    alert("Enter a valid watt target");
    return;
  }
  try {
    await api("/api/emulator/target", {
      method: "POST",
      body: JSON.stringify({ watts: Math.round(watts) }),
    });
    await refreshEmulatorStatus();
  } catch (e) {
    alert(e.message);
  }
};

$("btn-emu-pause").onclick = async () => {
  try {
    await api("/api/emulator/pause", { method: "POST" });
    await refreshEmulatorStatus();
  } catch (e) {
    alert(e.message);
  }
};

$("btn-emu-resume").onclick = async () => {
  try {
    await api("/api/emulator/resume", { method: "POST" });
    await refreshEmulatorStatus();
  } catch (e) {
    alert(e.message);
  }
};

$("btn-emu-follow").onclick = async () => {
  try {
    await api("/api/emulator/follow", { method: "POST" });
    await refreshEmulatorStatus();
  } catch (e) {
    alert(e.message);
  }
};

document.querySelectorAll("[data-preset]").forEach((btn) => {
  btn.addEventListener("click", async () => {
    const name = btn.getAttribute("data-preset");
    try {
      await api("/api/emulator/preset", {
        method: "POST",
        body: JSON.stringify({ name }),
      });
      await refreshEmulatorStatus();
    } catch (e) {
      alert(e.message);
    }
  });
});

$("btn-discover").onclick = async () => {
  if ($("btn-discover").disabled) return;
  $("discover-out").textContent = "Searching LAN for KICKR (mDNS)…";
  $("btn-discover").disabled = true;
  try {
    const res = await api("/api/trainer/discover", { method: "POST" });
    if (!res.trainers.length) {
      $("discover-out").textContent =
        "No trainer found. Power on the KICKR, stay on the same Wi‑Fi, and allow Local Network for Python.";
      return;
    }
    $("discover-out").textContent = JSON.stringify(res.trainers, null, 2);
    $("set-host").value = res.trainers[0].host;
    $("set-port").value = res.trainers[0].port;
  } catch (e) {
    $("discover-out").textContent = e.message;
  } finally {
    updateTrainerConnectionButtons();
  }
};

$("btn-connect").onclick = async () => {
  if ($("btn-connect").disabled) return;
  $("discover-out").textContent = "Connecting…";
  $("btn-connect").disabled = true;
  try {
    const body = {
      host: $("set-host").value || null,
      port: Number($("set-port").value) || 36866,
    };
    const res = await api("/api/trainer/connect", {
      method: "POST",
      body: JSON.stringify(body),
    });
    state.trainerConnected = true;
    updateTrainerChip();
    updateStartButtons();
    $("discover-out").textContent = res.already_connected
      ? `Already connected to ${res.host}:${res.port}`
      : `Connected ${res.host}:${res.port}`;
  } catch (e) {
    $("discover-out").textContent = e.message;
    updateTrainerConnectionButtons();
  }
};

$("btn-hr-discover")?.addEventListener("click", async () => {
  if ($("btn-hr-discover").disabled) return;
  $("hr-out").textContent = "Scanning for a heart-rate strap…";
  $("btn-hr-discover").disabled = true;
  try {
    const res = await api("/api/hr/discover", { method: "POST" });
    if (!res.devices?.length) {
      $("hr-out").textContent =
        "No strap found. Wear it, wake it, stay near the Mac, and allow Bluetooth for steadyGrind.";
      return;
    }
    setHrDeviceOptions(res.devices, selectedHrDevice().device_id);
    const lines = res.devices.map((d) => `${d.name} (${d.device_id})`);
    $("hr-out").textContent =
      `Found ${res.count}.\n${lines.join("\n")}\nConnect to pair the selected strap.`;
  } catch (e) {
    $("hr-out").textContent = e.message;
  } finally {
    updateHrConnectionButtons();
  }
});

$("btn-hr-connect")?.addEventListener("click", async () => {
  if ($("btn-hr-connect").disabled) return;
  $("hr-out").textContent = "Connecting…";
  $("btn-hr-connect").disabled = true;
  try {
    const hr = selectedHrDevice();
    const res = await api("/api/hr/connect", {
      method: "POST",
      body: JSON.stringify({
        device_id: hr.device_id,
        name: hr.name,
      }),
    });
    state.hrConnected = true;
    if (res.device_id) {
      setHrDeviceOptions(
        [{ device_id: res.device_id, name: res.name || res.device_id }],
        res.device_id,
      );
    }
    updateHrConnectionButtons();
    $("hr-out").textContent = res.already_connected
      ? `Already connected to ${res.name || res.device_id}`
      : `Connected to ${res.name || res.device_id}`;
  } catch (e) {
    $("hr-out").textContent = e.message;
    updateHrConnectionButtons();
  }
});

$("btn-hr-disconnect")?.addEventListener("click", async () => {
  if ($("btn-hr-disconnect").disabled) return;
  $("hr-out").textContent = "Disconnecting…";
  $("btn-hr-disconnect").disabled = true;
  try {
    const res = await api("/api/hr/disconnect", { method: "POST" });
    state.hrConnected = false;
    updateHrConnectionButtons();
    const who = res.name || res.device_id;
    $("hr-out").textContent = res.was_connected
      ? `Disconnected from ${who}. Autoconnect is paused until you Connect again.`
      : "Already disconnected.";
  } catch (e) {
    $("hr-out").textContent = e.message;
    updateHrConnectionButtons();
  }
});

$("btn-disconnect").onclick = async () => {
  if ($("btn-disconnect").disabled) return;
  $("discover-out").textContent = "Disconnecting…";
  $("btn-disconnect").disabled = true;
  try {
    const res = await api("/api/trainer/disconnect", { method: "POST" });
    state.trainerConnected = false;
    updateTrainerChip();
    updateStartButtons();
    if (res.was_connected && res.disconnected_from) {
      $("discover-out").textContent =
        `Disconnected from ${res.disconnected_from.host}:${res.disconnected_from.port}. ` +
        "Other apps can take Direct Connect now.";
    } else {
      $("discover-out").textContent = "Already disconnected.";
    }
  } catch (e) {
    $("discover-out").textContent = e.message;
    updateTrainerConnectionButtons();
  }
};

window.addEventListener("resize", () => {
  if (!$("view-ride").classList.contains("hidden")) {
    drawRideChart(state.live);
  }
  if (!$("view-preview").classList.contains("hidden")) drawPreviewChart();
});

const previewCanvas = $("preview-chart");
if (previewCanvas) {
  previewCanvas.addEventListener("pointerdown", onPreviewPointer);
  previewCanvas.addEventListener("pointermove", (ev) => {
    if (ev.buttons) onPreviewPointer(ev);
  });
}

loadHome().catch(console.error);
connectWs();
