// Live progress for reports being generated.
// Elements with [data-progress-id] are updated from /status/?ids=...; when a run finishes
// the page reloads so downloads/actions appear. Between polls the elapsed time and the
// countdown tick locally every second so the numbers move smoothly.
(() => {
  const nodes = () => [...document.querySelectorAll("[data-progress-id]")];
  if (!nodes().length) return;
  const url = document.body.dataset.statusUrl;
  const state = {}; // id -> {elapsed, remaining, at}

  const fmt = (sec) => {
    sec = Math.max(0, Math.round(sec));
    if (sec < 60) return `${sec} detik`;
    const m = Math.floor(sec / 60), s = sec % 60;
    return s ? `${m} menit ${s} detik` : `${m} menit`;
  };

  function render(el, d) {
    const pct = Math.max(0, Math.min(100, d.progress));
    el.querySelector("[data-fill]").style.width = pct + "%";
    const bar = el.querySelector("[role=progressbar]");
    bar.setAttribute("aria-valuenow", pct);
    el.querySelector("[data-pct]").textContent = pct + "%";
    el.querySelector("[data-label]").textContent = d.label;
  }

  function tick() {
    const now = Date.now();
    for (const el of nodes()) {
      const s = state[el.dataset.progressId];
      if (!s) continue;
      const dt = (now - s.at) / 1000;
      const el_elapsed = el.querySelector("[data-elapsed]");
      if (el_elapsed) el_elapsed.textContent = fmt(s.elapsed + dt);
      const eta = el.querySelector("[data-eta]");
      if (s.remaining == null) eta.textContent = "menghitung estimasi…";
      else if (s.remaining - dt <= 1) eta.textContent = "sebentar lagi…";
      else eta.textContent = "± " + fmt(s.remaining - dt) + " lagi";
    }
  }

  async function poll() {
    const ids = nodes().map((n) => n.dataset.progressId);
    if (!ids.length) return;
    try {
      const r = await fetch(`${url}?ids=${ids.join(",")}`, { headers: { Accept: "application/json" } });
      if (!r.ok) throw new Error(r.status);
      const { runs } = await r.json();
      for (const d of runs) {
        if (!d.busy) { location.reload(); return; }
        const el = document.querySelector(`[data-progress-id="${d.id}"]`);
        if (!el) continue;
        state[d.id] = { elapsed: d.elapsed_seconds, remaining: d.remaining_seconds, at: Date.now() };
        render(el, d);
      }
    } catch (e) { /* transient network error: keep the last values and try again */ }
    setTimeout(poll, 1500);
  }

  poll();
  setInterval(tick, 1000);
})();
