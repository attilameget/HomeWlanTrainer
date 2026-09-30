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
};

const HISTORY_WINDOW_MS = 10 * 60 * 1000;

function adherenceColor(power, target) {
  if (target == null || target <= 0 || power == null) return "#4a5874";
  const pct = Math.abs(power - target) / target;
  if (pct <= 0.05) return "#3dd68c";
  if (pct <= 0.1) return "#f0b429";
  return "#f07178";
}

function resetPowerHistory() {
  state.history = [];
  state.historyActiveMs = 0;
  state.historyLastTickAt = null;
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

  state.history.push({
    t: state.historyActiveMs,
    power: live.power_w ?? 0,
    target: live.target_w ?? 0,
  });
  const cutoff = state.historyActiveMs - HISTORY_WINDOW_MS;
  while (state.history.length && state.history[0].t < cutoff) {
    state.history.shift();
  }
}

function drawPowerHistory() {
  const canvas = $("power-history");
  if (!canvas) return;
  const dpr = window.devicePixelRatio || 1;
  const cssW = canvas.clientWidth || 300;
  const cssH = canvas.clientHeight || 120;
  if (canvas.width !== Math.floor(cssW * dpr) || canvas.height !== Math.floor(cssH * dpr)) {
    canvas.width = Math.floor(cssW * dpr);
    canvas.height = Math.floor(cssH * dpr);
  }
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, cssW, cssH);

  const padL = 28;
  const padR = 6;
  const padT = 8;
  const padB = 6;
  const plotW = cssW - padL - padR;
  const plotH = cssH - padT - padB;
  // Active ride time only — paused/stopped time does not scroll the window
  const now = state.historyActiveMs;
  const t0 = Math.max(0, now - HISTORY_WINDOW_MS);
  const span = Math.max(now - t0, 1);

  // grid
  ctx.strokeStyle = "#243049";
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

  ctx.fillStyle = "#8b9bb8";
  ctx.font = "10px system-ui, sans-serif";
  ctx.textAlign = "right";
  ctx.fillText(String(maxW), padL - 4, padT + 8);
  ctx.fillText("0", padL - 4, padT + plotH);

  // target line (latest target as dashed guide across window using per-sample targets)
  if (samples.length >= 2) {
    ctx.beginPath();
    ctx.setLineDash([4, 4]);
    ctx.strokeStyle = "rgba(232,238,252,0.35)";
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

  // power as colored vertical bars / thick line segments
  if (samples.length === 0) {
    ctx.fillStyle = "#8b9bb8";
    ctx.textAlign = "center";
    ctx.fillText("Waiting for ride data…", padL + plotW / 2, padT + plotH / 2);
    return;
  }

  const barW = Math.max(1.5, plotW / 600);
  for (const s of samples) {
    const x = padL + ((s.t - t0) / span) * plotW;
    const h = ((s.power || 0) / maxW) * plotH;
    const y = padT + plotH - h;
    ctx.fillStyle = adherenceColor(s.power, s.target);
    ctx.fillRect(x - barW / 2, y, barW, Math.max(h, 1));
  }
}

function show(view) {
  ["home", "preview", "ride", "settings"].forEach((name) => {
    $(`view-${name}`).classList.toggle("hidden", name !== view);
  });
  if (view === "ride") {
    requestAnimationFrame(drawPowerHistory);
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
  const today = await api("/api/workouts/today");
  const item = today[0];
  if (item) {
    state.workoutId = item.id;
    $("today-name").textContent = item.name;
    $("today-meta").textContent = [
      item.duration_s ? `${Math.round(item.duration_s / 60)} min` : null,
      item.sport,
      "Garmin Coach",
    ]
      .filter(Boolean)
      .join(" · ");
    $("btn-preview").disabled = false;
    $("btn-preview").textContent = "Open workout";
  } else {
    state.workoutId = null;
    $("today-name").textContent = st.garmin_authenticated
      ? "No bike workout today"
      : "Log in to Garmin";
    $("today-meta").textContent = st.garmin_authenticated
      ? "Nothing cycling scheduled on the Garmin calendar for today."
      : "Open Settings and sign in to fetch today’s ride.";
    $("btn-preview").disabled = true;
    $("btn-preview").textContent = "Open workout";
  }
  const lib = await api("/api/workouts");
  const ul = $("library");
  ul.innerHTML = "";
  if (!lib.length) {
    const empty = document.createElement("li");
    empty.className = "muted";
    empty.textContent = st.garmin_authenticated
      ? "No cycling workouts in your Garmin library."
      : "Sign in to Garmin to load workouts.";
    ul.appendChild(empty);
    return;
  }
  lib.forEach((w) => {
    const li = document.createElement("li");
    if (w.is_today) {
      li.classList.add("today-item");
      const label = document.createElement("span");
      label.className = "today-badge";
      label.textContent = "Today's workout";
      const name = document.createElement("span");
      name.className = "today-name";
      name.textContent = w.name;
      li.appendChild(label);
      li.appendChild(name);
    } else {
      li.textContent = w.name;
    }
    li.onclick = () => {
      state.workoutId = w.id;
      openPreview();
    };
    ul.appendChild(li);
  });
}

async function openPreview() {
  if (!state.workoutId) return;
  const w = await api(`/api/workouts/${state.workoutId}`);
  $("preview-name").textContent = w.name;
  $("preview-meta").textContent = `${Math.round(w.total_s / 60)} min · ${w.stages.length} stages`;
  const ol = $("preview-stages");
  ol.innerHTML = "";
  w.stages.forEach((s) => {
    const li = document.createElement("li");
    const target =
      s.target_mode === "ramp"
        ? `${s.start_w}→${s.end_w} W`
        : s.target_w != null
          ? `${s.target_w} W`
          : "free";
    li.textContent = `${s.name} · ${fmtMinutes(s.duration_s)} · ${target}`;
    ol.appendChild(li);
  });
  show("preview");
}

async function startRide(payload) {
  resetPowerHistory();
  state.historySession = "active";
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

function renderLive(live) {
  state.live = live;
  const trainer = $("chip-trainer");
  trainer.textContent = live.trainer_connected ? "Trainer OK" : "Trainer off";
  trainer.className = `chip ${live.trainer_connected ? "ok" : "bad"}`;
  $("chip-engine").textContent = live.engine_state;

  if (["running", "paused", "reconnecting"].includes(live.engine_state)) {
    show("ride");
  }

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
  $("ride-intensity").textContent = `Intensity ${live.intensity_pct}%`;
  $("btn-pause").textContent =
    live.engine_state === "paused" ? "Resume" : "Pause";
  $("btn-pause-m").textContent =
    live.engine_state === "paused" ? "Resume" : "Pause";

  pushHistory(live);
  drawPowerHistory();

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
    if (msg.type === "tick") renderLive(msg.data);
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

async function loadSettings() {
  const [s, st] = await Promise.all([api("/api/settings"), api("/api/status")]);
  $("set-ftp").value = s.ftp_w;
  $("set-host").value = s.trainer_host || "";
  $("set-port").value = s.trainer_port;
  if (st.garmin_authenticated) {
    $("garmin-status").textContent = `Logged in as ${st.garmin_display_name || "Garmin user"}`;
    $("garmin-mfa-wrap").classList.add("hidden");
  } else {
    $("garmin-status").textContent = "Not logged in";
  }
  if (st.engine?.trainer_connected) {
    const ep = st.trainer_endpoint
      ? `${st.trainer_endpoint.host}:${st.trainer_endpoint.port}`
      : `${s.trainer_host}:${s.trainer_port}`;
    $("discover-out").textContent = `Already connected to ${ep} (Direct Connect is 1:1 — no need to Connect again).`;
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
  const watts = Number($("manual-watts").value);
  if (!Number.isFinite(watts) || watts < 0) {
    status.textContent = "Enter a valid watt target.";
    return;
  }
  state.manualWatts = watts;
  btn.disabled = true;
  status.textContent = `Starting manual ERG at ${watts} W…`;
  try {
    await startRide({ workoutId: "manual", targetW: Math.round(watts) });
    status.textContent = "";
  } catch (e) {
    status.textContent = e.message || String(e);
    alert(e.message || String(e));
  } finally {
    btn.disabled = false;
  }
};

$("btn-preview").onclick = openPreview;
$("btn-start").onclick = () => {
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
    if (!confirm("Stop workout?")) return;
    try {
      await command("stop");
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

$("btn-save").onclick = async () => {
  await api("/api/settings", {
    method: "PUT",
    body: JSON.stringify({
      ftp_w: Number($("set-ftp").value),
      trainer_mode: "dircon",
      trainer_host: $("set-host").value || null,
      trainer_port: Number($("set-port").value),
    }),
  });
  alert("Saved.");
};

$("btn-discover").onclick = async () => {
  $("discover-out").textContent = "Searching LAN for KICKR (mDNS)…";
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
  }
};

$("btn-connect").onclick = async () => {
  $("discover-out").textContent = "Connecting…";
  try {
    const body = {
      host: $("set-host").value || null,
      port: Number($("set-port").value) || 36866,
    };
    const res = await api("/api/trainer/connect", {
      method: "POST",
      body: JSON.stringify(body),
    });
    $("discover-out").textContent = res.already_connected
      ? `Already connected to ${res.host}:${res.port}`
      : `Connected ${res.host}:${res.port}`;
  } catch (e) {
    $("discover-out").textContent = e.message;
  }
};

$("btn-disconnect").onclick = async () => {
  $("discover-out").textContent = "Disconnecting…";
  try {
    const res = await api("/api/trainer/disconnect", { method: "POST" });
    if (res.was_connected && res.disconnected_from) {
      $("discover-out").textContent =
        `Disconnected from ${res.disconnected_from.host}:${res.disconnected_from.port}. ` +
        "Other apps can take Direct Connect now.";
    } else {
      $("discover-out").textContent = "Already disconnected.";
    }
  } catch (e) {
    $("discover-out").textContent = e.message;
  }
};

window.addEventListener("resize", () => {
  if (!$("view-ride").classList.contains("hidden")) drawPowerHistory();
});

loadHome().catch(console.error);
connectWs();
