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
  /** When preview was opened from Plan, Back returns there instead of Home. */
  previewReturnView: "home",
  /** When true, live ticks must not auto-navigate to the ride view (user left mid-ride). */
  suppressRideAutoNav: false,
};

const HISTORY_WINDOW_MS = 10 * 60 * 1000;
/** Ride structure panel: 2 min past + 10 min ahead, so the next block is on screen before it arrives. */
const RIDE_STRUCT_PAST_S = 2 * 60;
const RIDE_STRUCT_AHEAD_S = 10 * 60;

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
  if (state.view === "plan" && view !== "plan") {
    flushPlanFormPersist();
  }
  if (view === "ride") {
    state.suppressRideAutoNav = false;
  } else if (
    (view === "settings" || view === "home" || view === "preview" || view === "plan") &&
    sessionActive()
  ) {
    state.suppressRideAutoNav = true;
  }
  state.view = view;
  ["home", "preview", "ride", "settings", "plan"].forEach((name) => {
    const el = $(`view-${name}`);
    if (el) el.classList.toggle("hidden", name !== view);
  });
  updateSettingsBackNav();
  if (view === "ride") {
    requestAnimationFrame(() => drawRideChart(state.live));
    setEmulatorPanelVisible(state.emulator);
  } else {
    // Never leave the emulator panel/layout active off the ride screen
    setEmulatorPanelVisible(false);
  }
  if (view === "plan") {
    loadPlanView().catch((e) => {
      const msg = $("plan-msg");
      if (msg) msg.textContent = e.message || String(e);
    });
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
  // One workouts call covers Today + Library (avoids a second calendar round-trip).
  // Settings FTP is best-effort and must not block the rest.
  const [st, settingsResult, lib] = await Promise.all([
    api("/api/status"),
    api("/api/settings").then((s) => s).catch(() => null),
    api("/api/workouts"),
  ]);
  state.emulator = !!st.emulator;
  state.trainerConnected = !!st.engine?.trainer_connected;
  state.hrSupported = !!st.hr_supported;
  state.hrConnected = !!st.hr_connected;
  updateTrainerChip();
  updateStartButtons();
  updateHrVisibility();
  updateHrConnectionButtons();
  if (settingsResult?.ftp_w) {
    state.ftpW = Number(settingsResult.ftp_w) || state.ftpW;
  }
  // Today card stays Garmin-only (plan bikes with is_today stay in Library)
  const item =
    (lib || []).find(
      (w) => w.is_today && String(w.source || "") !== "plan",
    ) || null;
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
  const tbody = $("library");
  tbody.innerHTML = "";
  if (!lib.length) {
    const tr = document.createElement("tr");
    tr.className = "empty-row";
    const td = document.createElement("td");
    td.colSpan = 5;
    td.textContent = st.garmin_authenticated
      ? "No cycling workouts in your Garmin library."
      : "Sign in to Garmin or open Plan to generate workouts.";
    tr.appendChild(td);
    tbody.appendChild(tr);
  } else {
    const shapeJobs = [];
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
      const src = String(w.source || "");
      if (src === "plan") {
        srcTd.textContent = "Plan";
      } else if (w.is_today) {
        srcTd.textContent = "Garmin Coach";
      } else {
        srcTd.textContent = "Garmin";
      }
      const durTd = document.createElement("td");
      durTd.textContent = w.duration_s
        ? `${Math.round(w.duration_s / 60)} min`
        : "—";
      const shapeTd = document.createElement("td");
      shapeTd.className = "library-shape-cell";
      const knownStages = Array.isArray(w.stages) ? w.stages : null;
      const cached = libraryShapeCache.get(String(w.id));
      const stagesNow = knownStages || cached || null;
      if (stagesNow && stagesNow.length) {
        const canvas = libraryShapeCanvas();
        shapeTd.appendChild(canvas);
        drawLibraryShape(canvas, stagesNow, state.ftpW || 200);
        if (knownStages) libraryShapeCache.set(String(w.id), knownStages);
      } else if (stagesNow) {
        shapeTd.textContent = "—";
      } else {
        const canvas = libraryShapeCanvas();
        canvas.classList.add("is-loading");
        shapeTd.appendChild(canvas);
        shapeJobs.push({ id: String(w.id), canvas });
      }
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
      tr.appendChild(shapeTd);
      tr.appendChild(actTd);
      tbody.appendChild(tr);
    });
    fillLibraryShapes(shapeJobs);
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
      "Saved rides unavailable — restart steadyGrind, then reload this page.";
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

const libraryShapeCache = new Map();
let libraryShapeGen = 0;

function libraryShapeCanvas() {
  const canvas = document.createElement("canvas");
  canvas.className = "library-shape";
  canvas.width = 112;
  canvas.height = 32;
  canvas.setAttribute("aria-label", "Workout structure");
  return canvas;
}

function paleSketchColor(hex) {
  const raw = String(hex || "").replace("#", "");
  const n = Number.parseInt(raw.length === 3
    ? raw.split("").map((c) => c + c).join("")
    : raw, 16);
  if (!Number.isFinite(n)) return "#d5e3ee";
  const mix = 0.62;
  const channel = (shift) => {
    const v = (n >> shift) & 255;
    return Math.round(v + (255 - v) * mix);
  };
  return `rgb(${channel(16)}, ${channel(8)}, ${channel(0)})`;
}

function drawLibraryShape(canvas, stages, ftp) {
  if (!canvas || !stages.length) return;
  const built = buildPreviewSegments(stages, ftp);
  const dpr = window.devicePixelRatio || 1;
  const cssW = 112;
  const cssH = 32;
  canvas.width = Math.floor(cssW * dpr);
  canvas.height = Math.floor(cssH * dpr);
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, cssW, cssH);
  const plotW = cssW;
  const plotH = cssH;
  const maxW = built.maxW;
  const totalS = built.totalS;
  for (const seg of built.segments) {
    const x0 = (seg.t0 / totalS) * plotW;
    const x1 = (seg.t1 / totalS) * plotW;
    const yTop0 = plotH * (1 - seg.startW / maxW);
    const yTop1 = plotH * (1 - seg.endW / maxW);
    const kind = seg.stage.kind || "interval";
    ctx.beginPath();
    ctx.moveTo(x0, plotH);
    ctx.lineTo(x0, yTop0);
    ctx.lineTo(x1, yTop1);
    ctx.lineTo(x1, plotH);
    ctx.closePath();
    const ink = KIND_COLORS[kind] || ZONE_COLORS[(seg.zone || 2) - 1] || "#9ccbe5";
    ctx.fillStyle = paleSketchColor(ink);
    ctx.fill();
  }
}

function fillLibraryShapes(jobs) {
  if (!jobs.length) return;
  const gen = ++libraryShapeGen;
  const queue = jobs.slice();
  const workers = Math.min(3, queue.length);
  const run = async () => {
    while (queue.length && gen === libraryShapeGen) {
      const job = queue.shift();
      if (!job || !job.canvas.isConnected) continue;
      try {
        const w = await api(`/api/workouts/${encodeURIComponent(job.id)}`);
        const stages = w.stages || [];
        libraryShapeCache.set(job.id, stages);
        if (gen !== libraryShapeGen) return;
        if (!job.canvas.isConnected) continue;
        job.canvas.classList.remove("is-loading");
        if (stages.length) drawLibraryShape(job.canvas, stages, state.ftpW || 200);
        else job.canvas.replaceWith(document.createTextNode("—"));
      } catch {
        if (gen === libraryShapeGen && job.canvas.isConnected) {
          job.canvas.classList.remove("is-loading");
          job.canvas.replaceWith(document.createTextNode("—"));
        }
      }
    }
  };
  for (let i = 0; i < workers; i++) run();
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

function updatePreviewBackNav() {
  const back = $("btn-preview-back");
  if (!back) return;
  const view = state.previewReturnView === "plan" ? "plan" : "home";
  back.setAttribute("data-nav", view);
}

async function openPreview() {
  if (!state.workoutId) return;
  // Remember where to return before switching to preview
  if (state.view === "plan") {
    state.previewReturnView = "plan";
  } else if (state.view !== "preview") {
    state.previewReturnView = "home";
  }
  updatePreviewBackNav();
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
    title: `Structure + power · −${RIDE_STRUCT_PAST_S / 60}m to +${RIDE_STRUCT_AHEAD_S / 60}m`,
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
  const hrOut = $("hr-out");
  if (!hrOut) return;
  const text = hrOut.textContent || "";
  if (text !== "Not connected." && !text.startsWith("Connected to ")) return;
  if (connected) {
    if (text === "Not connected.") {
      const hr = selectedHrDevice();
      const name = hr.name || hr.device_id || "heart rate monitor";
      setLineStatus("hr-out", `Connected to ${name}.`, true);
    } else {
      hrOut.classList.add("status-connected");
    }
  } else {
    setLineStatus("hr-out", "Not connected.", false);
  }
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
    discover.title = "Search the LAN for a KICKR (mDNS, then IP / port 36866 probe)";
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
  // Connected = pastel green pill; disconnected = bad
  trainer.className = `chip ${connected ? "ok" : "bad"}`;
}

function setLineStatus(id, text, connected) {
  const el = $(id);
  if (!el) return;
  el.textContent = text;
  el.classList.toggle("status-connected", !!connected);
}

function stageCountdownDigit(live) {
  if (!live || live.manual) return null;
  if (String(live.engine_state || "") !== "running") return null;
  if (!live.next_stage_name) return null;
  const remaining = Number(live.stage_remaining_s);
  if (!Number.isFinite(remaining) || remaining <= 0 || remaining > 3) return null;
  const whole = Math.ceil(remaining);
  if (whole < 1 || whole > 3) return null;
  return String(4 - whole);
}

function renderStageCountdown(live) {
  const veil = $("stage-countdown");
  if (!veil) return;
  const digit = stageCountdownDigit(live);
  if (!digit) {
    veil.classList.add("hidden");
    veil.setAttribute("aria-hidden", "true");
    return;
  }
  const num = $("stage-countdown-digit");
  if (num) num.textContent = digit;
  veil.classList.remove("hidden");
  veil.setAttribute("aria-hidden", "false");
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
  const engineState = live.engine_state ? String(live.engine_state) : "idle";
  const engineChip = $("chip-engine");
  engineChip.textContent = engineState.charAt(0).toUpperCase() + engineState.slice(1);
  engineChip.className = engineState === "running" ? "chip ok" : "chip";

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
    hrEl.classList.toggle("status-connected", !!state.hrConnected);
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
  renderStageCountdown(live);
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
    setLineStatus(
      "garmin-status",
      `Logged in as ${st.garmin_display_name || "Garmin user"}`,
      true,
    );
    $("garmin-mfa-wrap").classList.add("hidden");
  } else {
    setLineStatus("garmin-status", "Not logged in", false);
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
    setLineStatus(
      "hr-out",
      st.hr_connected
        ? `Connected to ${s.hr_device_name || s.hr_device_id || "heart rate monitor"}.`
        : "Not connected.",
      st.hr_connected,
    );
  } else if ($("hr-out")) {
    $("hr-out").classList.toggle("status-connected", !!st.hr_connected);
  }
  if (st.engine?.trainer_connected) {
    const ep = st.trainer_endpoint
      ? `${st.trainer_endpoint.host}:${st.trainer_endpoint.port}`
      : `${s.trainer_host}:${s.trainer_port}`;
    setLineStatus(
      "discover-out",
      state.emulator
        ? `Emulator connected (${ep}).`
        : `Already connected to ${ep} (Direct Connect is 1:1 — no need to Connect again).`,
      true,
    );
  } else if (state.emulator) {
    setLineStatus(
      "discover-out",
      "Emulator mode is on — ride controls drive simulated power.",
      false,
    );
  } else if ($("discover-out")) {
    $("discover-out").classList.remove("status-connected");
  }
  await loadBackups();
}

async function loadBackups() {
  const sel = $("backup-select");
  if (!sel) return;
  const data = await api("/api/backups");
  const reveal = $("btn-backup-reveal");
  if (reveal) reveal.classList.toggle("hidden", !data.reveal);
  const items = data.items || [];
  sel.replaceChildren();
  if (!items.length) {
    const opt = document.createElement("option");
    opt.value = "";
    opt.textContent = "No backups yet";
    sel.appendChild(opt);
    $("btn-backup-restore").disabled = true;
    return;
  }
  for (const item of items) {
    const opt = document.createElement("option");
    opt.value = item.id;
    opt.textContent = item.label;
    sel.appendChild(opt);
  }
  $("btn-backup-restore").disabled = false;
}

$("btn-backup").onclick = async () => {
  const msg = $("backup-msg");
  const btn = $("btn-backup");
  btn.disabled = true;
  msg.textContent = "Saving backup…";
  try {
    const res = await api("/api/backups", { method: "POST" });
    await loadBackups();
    if (res.id) $("backup-select").value = res.id;
    msg.textContent = "Backup saved.";
  } catch (e) {
    msg.textContent = e.message || String(e);
  } finally {
    btn.disabled = false;
  }
};

$("btn-backup-restore").onclick = async () => {
  const msg = $("backup-msg");
  const id = $("backup-select").value;
  if (!id) return;
  const btn = $("btn-backup-restore");
  btn.disabled = true;
  msg.textContent = "Restoring backup…";
  try {
    await api(`/api/backups/${encodeURIComponent(id)}/restore`, { method: "POST" });
    await loadSettings();
    $("backup-select").value = id;
    msg.textContent = "Backup restored.";
  } catch (e) {
    msg.textContent = e.message || String(e);
  } finally {
    btn.disabled = !$("backup-select").value;
  }
};

$("btn-backup-reveal").onclick = async () => {
  const msg = $("backup-msg");
  try {
    await api("/api/backups/reveal", { method: "POST" });
    msg.textContent = "Opened the backup folder.";
  } catch (e) {
    msg.textContent = e.message || String(e);
  }
};

$("btn-garmin-login").onclick = async () => {
  const msg = $("garmin-msg");
  const btn = $("btn-garmin-login");
  btn.disabled = true;
  const hasMfa = !!$("garmin-mfa").value.trim();
  msg.textContent = hasMfa
    ? "Verifying MFA code with Garmin…"
    : "Contacting Garmin… (SSO can take up to a minute; MFA field appears if needed)";
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
      msg.textContent =
        "Check your email/authenticator for a code, enter it below, then Log in again.";
      $("garmin-mfa").focus();
      return;
    }
    $("garmin-mfa-wrap").classList.add("hidden");
    $("garmin-password").value = "";
    $("garmin-mfa").value = "";
    msg.textContent = `Signed in${res.display_name ? ` as ${res.display_name}` : ""}. Refreshing workouts…`;
    // Update Settings status immediately; refresh Home in the background so
    // the login button is not blocked on Garmin calendar/library fetches.
    await loadSettings();
    msg.textContent = `Signed in${res.display_name ? ` as ${res.display_name}` : ""}.`;
    loadHome().catch((e) => {
      msg.textContent = `Signed in, but workout refresh failed: ${e.message || e}`;
    });
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
    if (view === "plan") await loadPlanView();
  });
});

function fmtPlanLength(day) {
  if (day.sport === "rest" || !day.duration_s) return "—";
  const mins = fmtMinutes(day.duration_s);
  if (day.sport === "running" && day.distance_m) {
    const km = (day.distance_m / 1000).toFixed(1);
    return `${mins} · ~${km} km`;
  }
  return mins;
}

/** Short weekday for a plan calendar date (YYYY-MM-DD, local). */
function fmtPlanWeekday(isoDate) {
  const parts = String(isoDate || "").split("-").map(Number);
  if (parts.length < 3 || parts.some((n) => !Number.isFinite(n))) return "—";
  const [y, m, d] = parts;
  const dt = new Date(y, m - 1, d);
  if (Number.isNaN(dt.getTime())) return "—";
  return dt.toLocaleDateString(undefined, { weekday: "short" });
}

function readPlanRestWeekdays() {
  const root = $("plan-rest-days");
  if (!root) return [4, 6];
  const selected = [...root.querySelectorAll(".plan-rest-chip.selected, .plan-rest-chip[aria-pressed='true']")]
    .map((btn) => Number(btn.getAttribute("data-dow")))
    .filter((n) => Number.isFinite(n) && n >= 0 && n <= 6);
  const unique = [...new Set(selected)].sort((a, b) => a - b);
  if (!unique.length) return [4, 6];
  if (unique.length >= 7) return unique.filter((d) => d !== 2).slice(0, 6);
  return unique;
}

function setPlanRestWeekdays(days) {
  const root = $("plan-rest-days");
  if (!root) return;
  let list = Array.isArray(days) ? days.map(Number).filter((n) => n >= 0 && n <= 6) : [];
  list = [...new Set(list)].sort((a, b) => a - b);
  if (!list.length) list = [4, 6];
  if (list.length >= 7) list = list.filter((d) => d !== 2).slice(0, 6);
  root.querySelectorAll(".plan-rest-chip").forEach((btn) => {
    const dow = Number(btn.getAttribute("data-dow"));
    const on = list.includes(dow);
    btn.classList.toggle("selected", on);
    btn.setAttribute("aria-pressed", on ? "true" : "false");
  });
}

function readPlanForm() {
  return {
    plan_weeks: Number($("plan-weeks")?.value) || 4,
    plan_hours_per_week: Number($("plan-hours")?.value) || 6,
    plan_bike_days_per_week: Number($("plan-bike-days")?.value) || 3,
    plan_run_days_per_week: Number($("plan-run-days")?.value) || 0,
    plan_strength_days_per_week: Number($("plan-strength-days")?.value) || 0,
    plan_rest_weekdays: readPlanRestWeekdays(),
    plan_goal: $("plan-goal")?.value || "general",
    plan_notes: ($("plan-notes")?.value || "").trim(),
  };
}

function applyPlanForm(s, plan) {
  const goals = plan?.goals || {};
  const weeks = s?.plan_weeks ?? goals.weeks ?? 4;
  const hours = s?.plan_hours_per_week ?? goals.hours_per_week ?? 6;
  const bike = s?.plan_bike_days_per_week ?? goals.bike_days_per_week ?? 3;
  const run = s?.plan_run_days_per_week ?? goals.run_days_per_week ?? 2;
  const strength =
    s?.plan_strength_days_per_week ?? goals.strength_days_per_week ?? 0;
  const rest =
    s?.plan_rest_weekdays ?? goals.rest_weekdays ?? [4, 6];
  const goal = s?.plan_goal ?? goals.goal ?? "general";
  const notes = s?.plan_notes ?? goals.notes ?? "";
  if ($("plan-weeks")) $("plan-weeks").value = String(weeks);
  if ($("plan-hours")) $("plan-hours").value = String(hours);
  if ($("plan-bike-days")) $("plan-bike-days").value = String(bike);
  if ($("plan-run-days")) $("plan-run-days").value = String(run);
  if ($("plan-strength-days")) $("plan-strength-days").value = String(strength);
  setPlanRestWeekdays(rest);
  if ($("plan-goal")) $("plan-goal").value = goal || "general";
  if ($("plan-notes")) $("plan-notes").value = notes || "";
  planFormHydrated = true;
}

let planFormHydrated = false;

async function persistPlanForm() {
  // The form starts as factory HTML. Saving before the saved values load
  // would overwrite hours, session counts, and rest days on quit.
  if (!planFormHydrated) return null;
  const body = readPlanForm();
  const res = await fetch("/api/settings", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    keepalive: true,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || res.statusText);
  }
  return body;
}

let _planFormSaveTimer = null;
function schedulePersistPlanForm() {
  if (!planFormHydrated) return;
  if (_planFormSaveTimer) clearTimeout(_planFormSaveTimer);
  _planFormSaveTimer = setTimeout(() => {
    persistPlanForm().catch((e) => {
      console.warn("plan preferences save failed", e);
    });
  }, 400);
}

/** Flush pending Plan form edits before leave / background (best-effort). */
function flushPlanFormPersist() {
  if (!planFormHydrated) return;
  if (_planFormSaveTimer) {
    clearTimeout(_planFormSaveTimer);
    _planFormSaveTimer = null;
  }
  if (!$("plan-weeks")) return;
  persistPlanForm().catch(() => {});
}

window.addEventListener("pagehide", flushPlanFormPersist);
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "hidden") flushPlanFormPersist();
});

function renderPlan(plan) {
  const active = $("plan-active");
  const syncBtn = $("btn-plan-sync");
  const clearBtn = $("btn-plan-clear");
  if (!plan) {
    active?.classList.add("hidden");
    if (syncBtn) syncBtn.disabled = true;
    if (clearBtn) clearBtn.disabled = true;
    return;
  }
  active?.classList.remove("hidden");
  if (syncBtn) syncBtn.disabled = false;
  if (clearBtn) clearBtn.disabled = false;
  if ($("plan-summary")) $("plan-summary").textContent = plan.summary || "";
  if ($("plan-history-note")) {
    const gen = plan.generator || "rules";
    const model = plan.model ? ` · ${plan.model}` : "";
    const note = plan.history_note || "";
    $("plan-history-note").textContent = `Generator: ${gen}${model}. ${note}`.trim();
  }
  const coachingRoot = $("plan-coaching");
  const coaching = plan.coaching;
  if (coachingRoot) {
    const has =
      coaching &&
      (coaching.goal || coaching.why || coaching.expect);
    coachingRoot.classList.toggle("hidden", !has);
    if ($("plan-coaching-goal")) {
      $("plan-coaching-goal").textContent = coaching?.goal || "";
    }
    if ($("plan-coaching-why")) {
      $("plan-coaching-why").textContent = coaching?.why || "";
    }
    if ($("plan-coaching-expect")) {
      $("plan-coaching-expect").textContent = coaching?.expect || "";
    }
  }
  // Form fields are restored from persisted settings (not overwritten here)
  const tbody = $("plan-days");
  if (!tbody) return;
  tbody.innerHTML = "";
  const today = new Date().toISOString().slice(0, 10);
  for (const day of plan.days || []) {
    const tr = document.createElement("tr");
    if (day.date === today) tr.classList.add("is-today");
    const sportClass =
      day.sport === "cycling"
        ? "bike"
        : day.sport === "running"
          ? "run"
          : day.sport === "strength"
            ? "strength"
            : "rest";
    const sportLabel =
      day.sport === "cycling"
        ? "Bike"
        : day.sport === "running"
          ? "Run"
          : day.sport === "strength"
            ? "Strength"
            : "Rest";
    const detail = day.rationale
      ? `<div class="plan-day-detail">${escapeHtml(day.rationale)}</div>`
      : "";
    let action = "";
    if (day.playable && day.sport === "cycling") {
      action = `<button class="btn" type="button" data-plan-preview="${escapeHtml(day.id)}">Open</button>`;
    } else if (day.sport === "running" || day.sport === "strength") {
      action = day.scheduled
        ? `<span class="muted">On Garmin</span>`
        : `<span class="muted">Guidance</span>`;
    } else {
      action = "";
    }
    tr.innerHTML = `
      <td class="plan-date">${escapeHtml(day.date)}</td>
      <td class="plan-weekday">${escapeHtml(fmtPlanWeekday(day.date))}</td>
      <td><span class="sport-pill ${sportClass}">${sportLabel}</span></td>
      <td><strong>${escapeHtml(day.title)}</strong>${detail}</td>
      <td class="plan-length">${escapeHtml(fmtPlanLength(day))}</td>
      <td>${action}</td>`;
    tbody.appendChild(tr);
  }
  tbody.querySelectorAll("[data-plan-preview]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const id = btn.getAttribute("data-plan-preview");
      if (!id) return;
      state.workoutId = id;
      openPreview().catch((e) => alert(e.message || String(e)));
    });
  });
}

function escapeHtml(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function normalizeClaudeModel(model) {
  const m = String(model || "").trim();
  if (!m || m === "claude-sonnet-4-5" || m === "claude-sonnet-4-5-20250929") {
    return "claude-sonnet-5-5";
  }
  return m;
}

function readClaudeSettings({ clearKey = false } = {}) {
  const anthropic_model = normalizeClaudeModel(
    ($("plan-anthropic-model")?.value || "").trim()
  );
  if (clearKey) {
    return { anthropic_api_key: "", anthropic_model };
  }
  const key = ($("plan-anthropic-key")?.value || "").trim();
  // Omit empty key so Save/Generate do not wipe a stored secret.
  const out = { anthropic_model };
  if (key) out.anthropic_api_key = key;
  return out;
}

function applyClaudeSettings(s) {
  if ($("plan-anthropic-key")) {
    // Server never echoes the raw key; leave blank and hint when configured.
    $("plan-anthropic-key").value = "";
    $("plan-anthropic-key").placeholder = s.anthropic_configured
      ? "•••• saved — paste a new key to replace"
      : "sk-ant-…";
  }
  if ($("plan-anthropic-model")) {
    $("plan-anthropic-model").value = normalizeClaudeModel(
      s.anthropic_model || "claude-sonnet-5-5"
    );
  }
  const configured = !!s.anthropic_configured;
  const status = $("plan-anthropic-status");
  if (status) {
    status.textContent = configured
      ? "API key saved on this host — Generate will prefer Claude (rules fallback on failure)."
      : "No API key — Generate uses the on-host rules planner.";
  }
  const summary = $("plan-claude-summary-status");
  if (summary) {
    const model = normalizeClaudeModel(s.anthropic_model || "claude-sonnet-5-5");
    summary.textContent = configured
      ? `API key saved · ${model}`
      : "No API key — rules planner";
  }
  const clearBtn = $("btn-plan-clear-claude");
  if (clearBtn) clearBtn.disabled = !configured;
}

async function loadPlanView() {
  const [res, s] = await Promise.all([api("/api/plan"), api("/api/settings")]);
  applyClaudeSettings(s);
  applyPlanForm(s, res.plan || null);
  renderPlan(res.plan || null);
  if ($("plan-msg") && !res.plan) {
    $("plan-msg").textContent =
      "Set your bike/run mix and generate a plan. Bike sessions will appear in Library.";
  }
}

$("btn-plan-test-claude").onclick = async () => {
  const msg = $("plan-claude-msg");
  const btn = $("btn-plan-test-claude");
  const { anthropic_api_key, anthropic_model } = readClaudeSettings();
  btn.disabled = true;
  if (msg) {
    msg.textContent = anthropic_api_key
      ? `Testing Claude model “${anthropic_model}”…`
      : "Testing saved API key…";
  }
  try {
    const res = await api("/api/plan/claude/test", {
      method: "POST",
      body: JSON.stringify({
        anthropicApiKey: anthropic_api_key || null,
        anthropicModel: anthropic_model,
      }),
    });
    let text = res.message || (res.ok ? "Claude OK." : "Claude not ready.");
    if (res.ok) {
      text += " Tap Save to keep these settings, then Generate.";
    }
    if (msg) msg.textContent = text;
  } catch (e) {
    const raw = e.message || String(e);
    let text = raw;
    if (/^not found$/i.test(raw.trim())) {
      text =
        "Could not reach the Test API on this steadyGrind server (Not Found). " +
        "Restart steadyGrind so /api/plan/claude/test is available.";
    } else if (/failed to fetch|networkerror|load failed/i.test(raw)) {
      text = `Network error talking to steadyGrind while testing Claude (${raw}).`;
    }
    if (msg) msg.textContent = text;
  } finally {
    btn.disabled = false;
  }
};

$("btn-plan-save-claude").onclick = async () => {
  const msg = $("plan-claude-msg");
  const btn = $("btn-plan-save-claude");
  btn.disabled = true;
  if (msg) msg.textContent = "Saving…";
  try {
    const saved = await api("/api/settings", {
      method: "PUT",
      body: JSON.stringify(readClaudeSettings()),
    });
    applyClaudeSettings(saved);
    if (msg) {
      msg.textContent = saved.anthropic_configured
        ? "Claude settings saved."
        : "Saved — no API key on this host (rules planner only).";
    }
  } catch (e) {
    if (msg) msg.textContent = e.message || String(e);
  } finally {
    btn.disabled = false;
  }
};

$("btn-plan-clear-claude").onclick = async () => {
  if (!confirm("Remove the saved Anthropic API key from this host?")) return;
  const msg = $("plan-claude-msg");
  const btn = $("btn-plan-clear-claude");
  btn.disabled = true;
  if (msg) msg.textContent = "Clearing…";
  try {
    const saved = await api("/api/settings", {
      method: "PUT",
      body: JSON.stringify(readClaudeSettings({ clearKey: true })),
    });
    applyClaudeSettings(saved);
    if (msg) msg.textContent = "API key cleared — rules planner only.";
  } catch (e) {
    if (msg) msg.textContent = e.message || String(e);
  } finally {
    btn.disabled = false;
  }
};

$("btn-plan-generate").onclick = async () => {
  const msg = $("plan-msg");
  const btn = $("btn-plan-generate");
  btn.disabled = true;
  msg.textContent = "Building plan from goals and recent history…";
  try {
    const form = readPlanForm();
    // Persist Claude + plan form before generate so they survive reloads
    await api("/api/settings", {
      method: "PUT",
      body: JSON.stringify({
        ...readClaudeSettings(),
        ...form,
      }),
    });
    const body = {
      weeks: form.plan_weeks,
      hoursPerWeek: form.plan_hours_per_week,
      bikeDaysPerWeek: form.plan_bike_days_per_week,
      runDaysPerWeek: form.plan_run_days_per_week,
      strengthDaysPerWeek: form.plan_strength_days_per_week,
      restWeekdays: form.plan_rest_weekdays,
      goal: form.plan_goal,
      notes: form.plan_notes,
    };
    const res = await api("/api/plan/generate", {
      method: "POST",
      body: JSON.stringify(body),
    });
    renderPlan(res.plan);
    msg.textContent =
      "Plan ready. Bike days are in Home Library (Source: Plan); Sync pushes to Garmin.";
    await loadHome();
  } catch (e) {
    msg.textContent = e.message || String(e);
  } finally {
    btn.disabled = false;
  }
};

$("btn-plan-sync").onclick = async () => {
  const msg = $("plan-msg");
  const btn = $("btn-plan-sync");
  btn.disabled = true;
  msg.textContent = "Uploading and scheduling on Garmin…";
  try {
    const res = await api("/api/plan/sync-garmin", { method: "POST" });
    renderPlan(res.plan);
    msg.textContent = `Synced ${res.synced_days || 0} session(s) to Garmin calendar.`;
  } catch (e) {
    msg.textContent = e.message || String(e);
  } finally {
    btn.disabled = false;
  }
};

$("btn-plan-clear").onclick = async () => {
  if (!confirm("Clear the active training plan?")) return;
  await persistPlanForm().catch(() => {});
  await api("/api/plan", { method: "DELETE" });
  renderPlan(null);
  $("plan-msg").textContent = "Plan cleared. Your generate parameters are kept.";
  await loadHome();
};

[
  "plan-weeks",
  "plan-hours",
  "plan-bike-days",
  "plan-run-days",
  "plan-strength-days",
  "plan-goal",
  "plan-notes",
].forEach((id) => {
  const el = $(id);
  if (!el) return;
  el.addEventListener("change", schedulePersistPlanForm);
  el.addEventListener("input", schedulePersistPlanForm);
});

(() => {
  const root = $("plan-rest-days");
  if (!root) return;
  root.querySelectorAll(".plan-rest-chip").forEach((btn) => {
    btn.addEventListener("click", () => {
      const wasOn = btn.classList.contains("selected");
      if (wasOn) {
        btn.classList.remove("selected");
        btn.setAttribute("aria-pressed", "false");
        // Keep at least one rest day selected for a clear weekly rhythm
        if (!readPlanRestWeekdays().length) {
          btn.classList.add("selected");
          btn.setAttribute("aria-pressed", "true");
          return;
        }
      } else {
        // Disallow selecting all seven (need ≥1 training day)
        const nextCount = readPlanRestWeekdays().length + 1;
        if (nextCount >= 7) return;
        btn.classList.add("selected");
        btn.setAttribute("aria-pressed", "true");
      }
      schedulePersistPlanForm();
    });
  });
})();

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
          "This ride was not saved as a FIT. Restart steadyGrind and try again.",
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
      msg.textContent = "Emulator on — Start is enabled; open a ride to drive power from the training page.";
    } else {
      msg.textContent = res.connected
        ? "Switched to Real KICKR (connected)."
        : "Switched to Real KICKR but no bike on this LAN — use Discover/Connect when the KICKR is on, or Apply Emulator (dev) for desk use.";
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
  setLineStatus("discover-out", "Searching LAN for KICKR (mDNS + IP resolve)…", false);
  $("btn-discover").disabled = true;
  try {
    const res = await api("/api/trainer/discover", { method: "POST" });
    if (!res.trainers.length) {
      setLineStatus(
        "discover-out",
        "No KICKR on this LAN. Desk/cloud without a bike: set Trainer mode to Emulator (dev) → Apply mode. " +
        "Real bike: power on, same Wi‑Fi, allow Local Network for Terminal/Python (macOS System Settings → Privacy → Local Network).",
        false,
      );
      return;
    }
    const lines = res.trainers.map(
      (t) => `${t.name} → ${t.host}:${t.port}${t.serial ? ` (serial ${t.serial})` : ""}`
    );
    setLineStatus("discover-out", lines.join("\n"), false);
    $("set-host").value = res.trainers[0].host;
    $("set-port").value = res.trainers[0].port;
  } catch (e) {
    setLineStatus("discover-out", e.message, !!state.trainerConnected);
  } finally {
    updateTrainerConnectionButtons();
  }
};

$("btn-connect").onclick = async () => {
  if ($("btn-connect").disabled) return;
  setLineStatus("discover-out", "Connecting…", false);
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
    setLineStatus(
      "discover-out",
      res.already_connected
        ? `Already connected to ${res.host}:${res.port}`
        : `Connected ${res.host}:${res.port}`,
      true,
    );
  } catch (e) {
    setLineStatus("discover-out", e.message, !!state.trainerConnected);
    updateTrainerConnectionButtons();
  }
};

$("btn-hr-discover")?.addEventListener("click", async () => {
  if ($("btn-hr-discover").disabled) return;
  setLineStatus("hr-out", "Scanning for a heart-rate strap…", false);
  $("btn-hr-discover").disabled = true;
  try {
    const res = await api("/api/hr/discover", { method: "POST" });
    if (!res.devices?.length) {
      setLineStatus(
        "hr-out",
        "No strap found. Wear it, wake it, stay near the Mac, and allow Bluetooth for steadyGrind.",
        false,
      );
      return;
    }
    setHrDeviceOptions(res.devices, selectedHrDevice().device_id);
    const lines = res.devices.map((d) => `${d.name} (${d.device_id})`);
    setLineStatus(
      "hr-out",
      `Found ${res.count}.\n${lines.join("\n")}\nConnect to pair the selected strap.`,
      false,
    );
  } catch (e) {
    setLineStatus("hr-out", e.message, !!state.hrConnected);
  } finally {
    updateHrConnectionButtons();
  }
});

$("btn-hr-connect")?.addEventListener("click", async () => {
  if ($("btn-hr-connect").disabled) return;
  setLineStatus("hr-out", "Connecting…", false);
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
    setLineStatus(
      "hr-out",
      res.already_connected
        ? `Already connected to ${res.name || res.device_id}`
        : `Connected to ${res.name || res.device_id}`,
      true,
    );
  } catch (e) {
    setLineStatus("hr-out", e.message, !!state.hrConnected);
    updateHrConnectionButtons();
  }
});

$("btn-hr-disconnect")?.addEventListener("click", async () => {
  if ($("btn-hr-disconnect").disabled) return;
  setLineStatus("hr-out", "Disconnecting…", false);
  $("btn-hr-disconnect").disabled = true;
  try {
    const res = await api("/api/hr/disconnect", { method: "POST" });
    state.hrConnected = false;
    updateHrConnectionButtons();
    const who = res.name || res.device_id;
    setLineStatus(
      "hr-out",
      res.was_connected
        ? `Disconnected from ${who}. Autoconnect is paused until you Connect again.`
        : "Already disconnected.",
      false,
    );
  } catch (e) {
    setLineStatus("hr-out", e.message, !!state.hrConnected);
    updateHrConnectionButtons();
  }
});

$("btn-disconnect").onclick = async () => {
  if ($("btn-disconnect").disabled) return;
  setLineStatus("discover-out", "Disconnecting…", false);
  $("btn-disconnect").disabled = true;
  try {
    const res = await api("/api/trainer/disconnect", { method: "POST" });
    state.trainerConnected = false;
    updateTrainerChip();
    updateStartButtons();
    if (res.was_connected && res.disconnected_from) {
      setLineStatus(
        "discover-out",
        `Disconnected from ${res.disconnected_from.host}:${res.disconnected_from.port}. ` +
        "Other apps can take Direct Connect now.",
        false,
      );
    } else {
      setLineStatus("discover-out", "Already disconnected.", false);
    }
  } catch (e) {
    setLineStatus("discover-out", e.message, !!state.trainerConnected);
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
