(function () {
  "use strict";

  const MAX_FIX = window.MAX_FIX;
  let lastStatus = null;
  let pendingSet = {};
  let setTimer = null;

  function postJSON(url, body) {
    return fetch(url, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(body || {})
    });
  }

  function flushSet() {
    if (Object.keys(pendingSet).length === 0) return;
    const body = pendingSet;
    pendingSet = {};
    postJSON("/api/set", body).catch(() => {});
  }

  function queueSet(patch) {
    Object.assign(pendingSet, patch);
    if (setTimer) clearTimeout(setTimer);
    setTimer = setTimeout(flushSet, 150);
  }

  function $(id) { return document.getElementById(id); }

  const sliders = ["bpm", "fixtures", "dimmer", "cycle_speed", "hue_start", "hue_width"];
  sliders.forEach(k => {
    const el = $(k);
    el.addEventListener("input", () => {
      $(k + "-v").textContent = el.value;
      queueSet({[k]: parseInt(el.value, 10)});
    });
  });

  ["cR", "cG", "cB", "cW"].forEach(k => {
    const el = $(k);
    el.addEventListener("input", () => {
      $(k + "-v").textContent = el.value;
      const stored = (lastStatus && lastStatus.color) || [0, 0, 0, 0];
      const read = (id, idx) => $(id).disabled ? stored[idx] : parseInt($(id).value, 10);
      queueSet({color: [read("cR",0), read("cG",1), read("cB",2), read("cW",3)]});
    });
  });

  document.querySelectorAll("#patterns button").forEach(b => {
    b.addEventListener("click", () => {
      queueSet({pattern: b.dataset.pattern});
      flushSet();
    });
  });

  $("b-run").addEventListener("click", () => { flushSet(); postJSON("/api/run"); });
  $("b-stop").addEventListener("click", () => { flushSet(); postJSON("/api/stop"); });
  $("b-step").addEventListener("click", () => { flushSet(); postJSON("/api/step"); });
  $("b-bo").addEventListener("click", () => { postJSON("/api/blackout"); });

  function isDragging(id) {
    return document.activeElement && document.activeElement.id === id;
  }

  function applyStatus(s) {
    lastStatus = s;
    const play = $("play"), lbl = $("dot-label");
    play.classList.toggle("run", !!s.running && !s.blackout);
    play.classList.toggle("bo", !!s.blackout);
    play.textContent = s.blackout ? "■" : (s.running ? "▶" : "■");
    lbl.textContent = s.blackout ? "blackout" : (s.running ? "running" : "stopped");

    const dmxEl = $("dmx");
    const dmxState = s.dmx || "demo";
    dmxEl.classList.remove("ok", "demo", "error", "unpatched");
    dmxEl.classList.add(dmxState);
    const dmxLabels = {ok: "DMX OK", demo: "DEMO", error: "DMX ERR", unpatched: "UNPATCHED"};
    dmxEl.textContent = dmxLabels[dmxState] || dmxState;
    dmxEl.title = dmxState === "unpatched"
      ? `${s.dmx_target} has no output port patched at olad. Run: ola_dev_info; ola_patch -d <DEV> -p <PORT> -u 0`
      : `DMX ${dmxState} (${s.dmx_target || ""})`;

    const active = new Set(s.active || []);
    document.querySelectorAll("#grid .par").forEach(el => {
      const i = parseInt(el.dataset.i, 10);
      el.classList.toggle("disabled", i >= s.fixtures);
      el.classList.toggle("on", active.has(i) && !s.blackout);
    });

    document.querySelectorAll("#patterns button").forEach(b => {
      b.classList.toggle("sel", b.dataset.pattern === s.pattern);
    });

    const setSlider = (id, v) => {
      if (!isDragging(id)) {
        $(id).value = v;
        $(id + "-v").textContent = v;
      }
    };
    setSlider("bpm", s.bpm);
    setSlider("fixtures", s.fixtures);
    setSlider("dimmer", s.dimmer);
    const ec = s.effective_color || s.color;
    setSlider("cR", ec[0]);
    setSlider("cG", ec[1]);
    setSlider("cB", ec[2]);
    setSlider("cW", ec[3]);
    setSlider("cycle_speed", s.cycle_speed);
    setSlider("hue_start", s.hue_start);
    setSlider("hue_width", s.hue_width);
    const cycling = s.cycle_speed > 0;
    ["cR", "cG", "cB"].forEach(k => { $(k).disabled = cycling; });

    $("b-run").classList.toggle("active", !!s.running);
    $("b-bo").classList.toggle("active", !!s.blackout);

    $("meta").textContent = `step ${s.step} / ${s.seq_len}`;
  }

  async function poll() {
    try {
      const r = await fetch("/api/status");
      if (r.ok) applyStatus(await r.json());
    } catch (e) {}
  }

  let lastBytesAt = Date.now();
  let lastErrorAt = 0;
  const es = new EventSource("/api/stream");
  es.onmessage = (e) => {
    lastBytesAt = Date.now();
    try { applyStatus(JSON.parse(e.data)); } catch (err) {}
  };
  es.addEventListener("hb", () => { lastBytesAt = Date.now(); });
  es.onerror = () => { lastErrorAt = Date.now(); };

  function updateLink() {
    const now = Date.now();
    const gap = now - lastBytesAt;
    const recentError = (now - lastErrorAt) < 5000;
    const linkEl = $("link");
    let state, title;
    if (es.readyState !== 1 || gap > 6000) {
      state = "off"; title = `offline (${gap}ms since last event)`;
    } else if (gap > 4000 || recentError) {
      state = "warn"; title = `degraded (${gap}ms gap${recentError ? ", recent reconnect" : ""})`;
    } else {
      state = "ok"; title = `ok (${gap}ms since last event)`;
    }
    linkEl.classList.remove("ok", "warn", "off");
    linkEl.classList.add(state);
    linkEl.title = title;
  }
  setInterval(updateLink, 500);
  updateLink();
  poll();
})();
