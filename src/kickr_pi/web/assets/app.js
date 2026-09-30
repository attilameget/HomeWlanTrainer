const $ = (id) => document.getElementById(id);

const state = {
  workoutId: "demo-1",
  live: null,
  wakeLock: null,
};

function show(view) {
  ["home", "preview", "ride", "settings"].forEach((name) => {
    $(`view-${name}`).classList.toggle("hidden", name !== view);
  });
}

function fmtSec(s) {
  if (s == null || Number.isNaN(s)) return "—";
  const n = Math.max(0, Math.round(s));
  const m = Math.floor(n / 60);
  const r = n % 60;
  return `${m}:${String(r).padStart(2, "0")}`;
}

async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(opts.headers || {}) },
    ...opts,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || res.statusText);
  }
  return res.json();
}

async function loadHome() {
  const today = await api("/api/workouts/today");
  const item = today[0];
  if (item) {
    state.workoutId = item.id;
    $("today-name").textContent = item.name;
    $("today-meta").textContent = item.duration_s
      ? `${Math.round(item.duration_s / 60)} min · ${item.sport}`
      : item.sport;
  }
  const lib = await api("/api/workouts");
  const ul = $("library");
  ul.innerHTML = "";
  lib.forEach((w) => {
    const li = document.createElement("li");
    li.textContent = w.name;
    li.onclick = () => {
      state.workoutId = w.id;
      openPreview();
    };
    ul.appendChild(li);
  });
}

async function openPreview() {
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
    li.textContent = `${s.name} · ${s.duration_s ?? "∞"}s · ${target}`;
    ol.appendChild(li);
  });
  show("preview");
}

async function startRide() {
  await api("/api/session", {
    method: "POST",
    body: JSON.stringify({ workoutId: state.workoutId }),
  });
  show("ride");
  requestWakeLock();
}

async function command(cmd) {
  await api("/api/session/command", {
    method: "POST",
    body: JSON.stringify({ command: cmd }),
  });
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

  $("ride-stage-label").textContent =
    `${live.stage_name} (${live.stage_index + 1}/${live.stage_count || 1})`;
  $("ride-target").textContent = live.target_w ?? "—";
  const powerEl = $("ride-power");
  powerEl.textContent = live.power_w ?? "—";
  powerEl.className = "value";
  if (live.target_w && live.power_w != null) {
    const pct = Math.abs(live.power_w - live.target_w) / live.target_w;
    if (pct <= 0.05) powerEl.classList.add("good");
    else if (pct > 0.1) powerEl.classList.add("warn");
  }
  $("ride-cadence").textContent =
    live.cadence_rpm != null ? Math.round(live.cadence_rpm) : "—";
  $("ride-stage-left").textContent = fmtSec(live.stage_remaining_s);
  $("ride-total-left").textContent = fmtSec(live.total_remaining_s);
  $("ride-next").textContent = live.next_stage_name
    ? `Next: ${live.next_stage_name}`
    : "";
  $("ride-intensity").textContent = `Intensity ${live.intensity_pct}%`;
  $("btn-pause").textContent =
    live.engine_state === "paused" ? "Resume" : "Pause";
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

async function requestWakeLock() {
  try {
    if ("wakeLock" in navigator) {
      state.wakeLock = await navigator.wakeLock.request("screen");
    }
  } catch (_) {
    /* ignore */
  }
}

async function loadSettings() {
  const s = await api("/api/settings");
  $("set-ftp").value = s.ftp_w;
  $("set-mode").value = s.trainer_mode;
  $("set-host").value = s.trainer_host || "";
  $("set-port").value = s.trainer_port;
}

document.querySelectorAll("[data-nav]").forEach((el) => {
  el.addEventListener("click", async () => {
    const view = el.getAttribute("data-nav");
    show(view);
    if (view === "settings") await loadSettings();
    if (view === "home") await loadHome();
  });
});

$("btn-preview").onclick = openPreview;
$("btn-start").onclick = () => startRide().catch((e) => alert(e.message));
$("btn-pause").onclick = () => {
  const cmd = state.live?.engine_state === "paused" ? "resume" : "pause";
  command(cmd).catch((e) => alert(e.message));
};
$("btn-skip").onclick = () => command("skip").catch((e) => alert(e.message));
$("btn-prev").onclick = () => command("previous").catch((e) => alert(e.message));
$("btn-minus").onclick = () => command("-5").catch((e) => alert(e.message));
$("btn-plus").onclick = () => command("+5").catch((e) => alert(e.message));
$("btn-stop").onclick = () => {
  if (confirm("Stop workout?")) command("stop").catch((e) => alert(e.message));
};

$("btn-save").onclick = async () => {
  await api("/api/settings", {
    method: "PUT",
    body: JSON.stringify({
      ftp_w: Number($("set-ftp").value),
      trainer_mode: $("set-mode").value,
      trainer_host: $("set-host").value || null,
      trainer_port: Number($("set-port").value),
    }),
  });
  alert("Saved. Restart the app if you changed trainer mode.");
};

$("btn-discover").onclick = async () => {
  $("discover-out").textContent = "Searching…";
  try {
    const res = await api("/api/trainer/discover", { method: "POST" });
    $("discover-out").textContent = JSON.stringify(res.trainers, null, 2);
    if (res.trainers[0]) {
      $("set-host").value = res.trainers[0].host;
      $("set-port").value = res.trainers[0].port;
    }
  } catch (e) {
    $("discover-out").textContent = e.message;
  }
};

$("btn-connect").onclick = async () => {
  try {
    await api("/api/settings", {
      method: "PUT",
      body: JSON.stringify({
        trainer_host: $("set-host").value || null,
        trainer_port: Number($("set-port").value),
      }),
    });
    const res = await api("/api/trainer/connect", { method: "POST" });
    $("discover-out").textContent = `Connected ${res.host}:${res.port}`;
  } catch (e) {
    $("discover-out").textContent = e.message;
  }
};

loadHome().catch(console.error);
connectWs();
