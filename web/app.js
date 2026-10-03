const $ = (id) => document.getElementById(id) || {
  innerHTML: "", textContent: "", hidden: true, value: "60", dataset: {},
  classList: { add() {}, remove() {}, toggle() {} },
  setAttribute() {}, removeAttribute() {}, addEventListener() {},
};
const fmt = (v, d = 0) => (v === null || v === undefined || v === "" ? "—" : "$" + Number(v).toLocaleString("en-US", { maximumFractionDigits: d }));
const pct = (v) => (v === null || v === undefined ? "—" : (v >= 0 ? "+" : "") + Number(v).toFixed(1) + "%");
const cls = (v) => (v > 0 ? "up" : v < 0 ? "down" : "mut");

let timer = null;
let clockTimer = null;
let secondsToClose = null;
let failures = 0;
let haveData = false;

const fmtDur = (s) => {
  if (s === null || s === undefined || s < 0) return "—";
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60);
  return h > 0 ? `${h}h ${String(m).padStart(2, "0")}m` : `${m}m ${String(Math.floor(s % 60)).padStart(2, "0")}s`;
};

function fail(stage, e) {
  console.error(`[dashboard] ${stage} failed`, e);
  const msg = e && e.message ? e.message : String(e);
  $("live").classList.remove("on");
  $("stamp").textContent = stage === "fetch" ? "server unreachable" : "update failed";
  $("pred-error-msg").textContent =
    stage === "fetch" ? `Could not reach the dashboard API (${msg}).` : `Display failed (${msg}). Showing the last good update.`;
  $("pred-error").hidden = false;
  $("pred-panel").setAttribute("aria-busy", "false");
}

async function loadSnapshot(force) {
  try {
    const res = await fetch("/api/snapshot" + (force ? "?force=1" : ""), { cache: "no-store" });
    if (!res.ok) throw new Error("HTTP " + res.status);
    const d = await res.json();
    try {
      render(d);
      failures = 0;
      haveData = true;
      $("live").classList.add("on");
      return true;
    } catch (e) {
      fail("render", e);
      return false;
    }
  } catch (e) {
    fail("fetch", e);
    failures += 1;
    return false;
  }
}

function paintClock() {
  if (secondsToClose === null) return;
  const node = $("countdown");
  node.textContent = secondsToClose <= 0 ? "closing now — waiting for the exchange" : `next daily close in ${fmtDur(secondsToClose)}`;
  node.classList.toggle("warn", secondsToClose <= 0);
  secondsToClose = Math.max(0, secondsToClose - 1);
}

async function pollTick() {
  let t;
  try {
    const res = await fetch("/api/tick", { cache: "no-store" });
    if (!res.ok) throw new Error("HTTP " + res.status);
    t = await res.json();
  } catch (e) {
    fail("fetch", e);
    return;
  }
  secondsToClose = t.seconds_to_daily_close;
  $("countdown").textContent = t.stale_tf && t.stale_tf.length
    ? `new ${t.stale_tf.join("/")} bar available`
    : `next daily close in ${fmtDur(secondsToClose)}`;
  if (!haveData || t.changed) {
    const ok = await loadSnapshot(false);
    if (!ok) failures += 1;
  }
  scheduleRetry();
}

const BACKOFF = [30, 60, 120, 300];
function scheduleRetry() {
  clearTimeout(retryTimer);
  const base = Number($("interval").value);
  const wait = failures ? BACKOFF[Math.min(failures - 1, BACKOFF.length - 1)] : base;
  retryTimer = setTimeout(pollTick, failures ? wait : base);
}

let retryTimer = null;

function arm() {
  clearInterval(clockTimer);
  clockTimer = setInterval(paintClock, 1000);
  failures = 0;
  scheduleRetry();
}

function render(d) {
  const p = d.prediction;
  $("stamp").textContent = `data as of ${p.price_date} close`;
  $("generated").textContent = `computed ${p.generated.replace("T", " ").replace("+00:00", "Z")}`;

  const c = p.cycle;
  const buyLabel = { active: "ACTIVE", done: "done", upcoming: "upcoming" }[c.buy_status] || c.buy_status;
  const buyClass = { active: "up", done: "", upcoming: "warn" }[c.buy_status] || "";
  const buySub = c.buy_status === "done"
    ? `next buy ${c.next_buy || "—"}`
    : `${c.buy_window_days[0]}–${c.buy_window_days[1]} d after ${c.halving}`;
  const sellCard = c.sell_status === "reached"
    ? { v: "due", s: `${c.sell_date} · within data`, cls: "warn" }
    : { v: c.sell_date || "—", s: c.sell_date ? `${c.sell_status} · after ${c.next_halving}${c.next_halving_is_estimate ? " (est.)" : ""}` : "awaiting next halving", cls: "" };

  const cards = [
    { k: "price", v: fmt(p.price) },
    { k: "ATH", v: fmt(p.ath), s: "as of " + p.ath_date },
    { k: "drawdown", v: pct(p.dd_from_ath_pct), s: "from ATH" },
    { k: "ewma vol", v: p.ewma_vol_pct + "%", s: "annualised" },
    { k: "days since halving", v: c.days_since, s: c.halving },
    { k: "buy window", v: buyLabel, s: buySub, cls: buyClass },
    { k: "cycle progress", v: `${c.buys_placed}/${c.buys_total}`, s: "installments placed" },
    { k: "next sell", v: sellCard.v, s: sellCard.s, cls: sellCard.cls },
  ];
  $("cards").innerHTML = cards
    .map((c2) => `<div class="card"><div class="k">${c2.k}</div><div class="v ${c2.cls || ""}">${c2.v}</div><div class="k">${c2.s || ""}</div></div>`)
    .join("");

  $("states").innerHTML = d.states.map((s) => {
    const mas = Object.entries(s.mas).map(([n, v]) => `<span class="${cls(v.vs)}">${n}: ${pct(v.vs)}</span>`).join("&nbsp; ");
    return `<div class="panel">
      <h3>${s.tf} <span class="mut">${s.last_date}</span></h3>
      <div class="v" style="font-size:20px;font-weight:600">${fmt(s.last)}</div>
      <div style="margin:8px 0">${mas}</div>
      <table><tbody>
        <tr><td>RSI(14)</td><td class="${s.rsi > 70 ? "warn" : s.rsi < 30 ? "down" : ""}">${s.rsi}</td></tr>
        <tr><td>phase</td><td><span class="badge">${s.phase}</span></td></tr>
        <tr><td>drawdown from TF high</td><td class="down">${pct(s.dd)}</td></tr>
        <tr><td>ATR%</td><td>${s.atr_pct}</td></tr>
        <tr><td>vol 20 / 90</td><td>${s.vol20 ?? "—"}% / ${s.vol90 ?? "—"}%</td></tr>
      </tbody></table></div>`;
  }).join("");

  renderPrediction(d);
  drawChart(d);
  renderTables(d);
}

const svgEl = (t, a = {}) => Object.entries(a).map(([k, v]) => `${k}="${v}"`).join(" ");

function priceRange(pred, analogs) {
  const b365 = pred.bands.find((x) => x.horizon === 365);
  const last = pred.price;
  const lo = [b365.lows["95"], b365.lows["90"], b365.lows["80"]];
  const hi = [b365.highs["80"], b365.highs["90"], b365.highs["95"]];
  if (analogs && analogs.low_pct) [50, 25].forEach((q) => { if (analogs.low_pct[q] !== undefined) lo.push(last * (1 + analogs.low_pct[q])); });
  if (pred.amplitude) [pred.amplitude.next_peak, pred.amplitude.flat_peak].forEach((v) => { if (v) hi.push(v); });
  const clean = (a) => a.filter((x) => Number.isFinite(x) && x > 0);
  lo.sort((a, b) => a - b);
  hi.sort((a, b) => a - b);
  return { lo: clean(lo), hi: clean(hi) };
}

function renderPrediction(d) {
  const p = d.prediction;
  const an = p.analogs || {};
  const r = priceRange(p, an);
  const openCycle = (d.history.cycles || []).slice(-1)[0];

  renderAxis(p, r);
  renderTiles(p, r, an, openCycle);
  renderEvidence(p, an);

  $("pred-panel").setAttribute("aria-busy", "false");
  $("pred-error").hidden = true;
}

function renderAxis(p, r) {
  const W = 1000, M = { t: 12, r: 30, b: 62, l: 30 };
  const cur = p.price;
  const lo = Math.min(r.lo[0], cur * 0.72);
  const hi = Math.max(r.hi[r.hi.length - 1], p.ath * 1.06);
  const X = (v) => M.l + (Math.log(v) - Math.log(lo)) / (Math.log(hi) - Math.log(lo)) * (W - M.l - M.r);

  const axisY = 96;
  const laneTop = { y: 20, h: 30 };
  const laneBottom = { y: 62, h: 30 };
  const laneEnd = laneBottom.y + laneBottom.h + 8;

  const ticks = [0.5, 0.75, 1, 1.5, 2, 3].map((m) => m * 1e4)
    .concat([1, 2].map((m) => m * 1e5))
    .filter((v) => v > lo && v < hi);

  let g = ticks.map((v) => `<line x1="${X(v)}" x2="${X(v)}" y1="${M.t}" y2="${axisY}" stroke="var(--line)" stroke-width="1"/>
    <text x="${X(v)}" y="${axisY + 15}" fill="var(--mut)" font-size="11" text-anchor="middle">$${v >= 1e5 ? Math.round(v / 1e4) * 10 + "k" : v / 1e3 + "k"}</text>`).join("");
  g += `<line x1="${M.l}" x2="${W - M.r}" y1="${axisY}" y2="${axisY}" stroke="var(--line)"/>`;

  const bar = (x1, x2, lane, color, text) => {
    const w = Math.max(x2 - x1, 3);
    const inside = w >= text.length * 7 + 24;
    const tx = inside ? x1 + 10 : Math.min(Math.max((x1 + x2) / 2, M.l + text.length * 3.4), W - M.r - text.length * 3.4);
    const ty = inside ? lane.y + lane.h / 2 + 4 : lane.y - 6;
    return `<rect x="${x1}" y="${lane.y}" width="${w}" height="${lane.h}" rx="4" fill="${color}" opacity=".3"/>
      <rect x="${x1}" y="${lane.y}" width="${w}" height="${lane.h}" rx="4" fill="none" stroke="${color}" stroke-opacity=".8"/>
      <text x="${tx}" y="${ty}" fill="var(--txt)" font-size="12" font-weight="600" text-anchor="${inside ? "start" : "middle"}">${text}</text>`;
  };

  g += bar(X(r.hi[0]), X(r.hi[r.hi.length - 1]), laneTop, "var(--up)", `next top  ${fmt(r.hi[0])} – ${fmt(r.hi[r.hi.length - 1])}`);
  g += bar(X(r.lo[0]), X(r.lo[r.lo.length - 1]), laneBottom, "var(--down)", `next bottom  ${fmt(r.lo[0])} – ${fmt(r.lo[r.lo.length - 1])}`);

  const vline = (v, color, dash) =>
    `<line x1="${X(v)}" x2="${X(v)}" y1="${M.t}" y2="${axisY}" stroke="${color}" stroke-width="1.5" ${dash ? `stroke-dasharray="4 3"` : ""}/>`;
  g += vline(p.ath, "var(--warn)", true);
  g += vline(cur, "var(--txt)", false);

  const legend = [
    { color: "var(--txt)", dash: false, text: `last price  ${fmt(cur)}  (${p.dd_from_ath_pct}%)` },
    { color: "var(--warn)", dash: true, text: `all-time high  ${fmt(p.ath)}  ${p.ath_date}` },
    { color: "var(--up)", dash: false, text: "top forecast band" },
    { color: "var(--down)", dash: false, text: "bottom forecast band" },
  ];
  let lx = M.l, ly = 122;
  g += legend.map((e) => {
    const w = e.text.length * 6.4 + 26;
    if (lx + w > W - M.r) { lx = M.l; ly += 17; }
    const row = `<line x1="${lx}" x2="${lx + 14}" y1="${ly - 4}" y2="${ly - 4}" stroke="${e.color}" stroke-width="2" ${e.dash ? `stroke-dasharray="4 3"` : ""}/>
      <text x="${lx + 20}" y="${ly}" fill="var(--mut)" font-size="11.5">${e.text}</text>`;
    lx += w;
    return row;
  }).join("");

  const H = Math.max(ly + 14, laneEnd + 16);
  $("axis").classList.remove("skeleton");
  $("axis").innerHTML = `<svg viewBox="0 0 ${W} ${H}" role="img"
    aria-label="Price scale. Next bottom forecast ${fmt(r.lo[0])} to ${fmt(r.lo[r.lo.length - 1])}. Next top forecast ${fmt(r.hi[0])} to ${fmt(r.hi[r.hi.length - 1])}. Last price ${fmt(cur)}. All-time high ${fmt(p.ath)}.">${g}</svg>`;

  $("axis-table").innerHTML = `<caption class="sr-only">Forecast values used in the price map</caption>
    <thead><tr><th>item</th><th>low</th><th>high</th></tr></thead><tbody>
      <tr><td>next bottom</td><td>${fmt(r.lo[0])}</td><td>${fmt(r.lo[r.lo.length - 1])}</td></tr>
      <tr><td>next top</td><td>${fmt(r.hi[0])}</td><td>${fmt(r.hi[r.hi.length - 1])}</td></tr>
      <tr><td>last price</td><td colspan="2">${fmt(cur)} (${p.dd_from_ath_pct}% from all-time high)</td></tr>
      <tr><td>all-time high</td><td colspan="2">${fmt(p.ath)} (${p.ath_date})</td></tr>
    </tbody>`;
}

function renderTiles(p, r, an, openCycle) {
  const b365 = p.bands.find((x) => x.horizon === 365);
  const lowNote = openCycle
    ? `cycle low ${fmt(openCycle.low_close)} printed ${openCycle.low_date}, inside the range`
    : "cycle low not yet recorded";

  const tile = (kind, range, color, bullets, chips) => `
    <article class="tile">
      <h3 class="tile__label"><span class="dot" style="background:${color}"></span>next ${kind} · 12 months</h3>
      <p class="tile__value" style="color:${color}">${fmt(range[0])} – ${fmt(range[range.length - 1])}</p>
      <p class="tile__sub">from last close ${fmt(p.price)}</p>
      <ul class="tile__list">${bullets.map((b) => `<li>${b}</li>`).join("")}</ul>
      <div class="chips">${chips}</div>
    </article>`;

  $("pred-tiles").innerHTML =
    tile("top", r.hi, "var(--up)", [
      `volatility band 80–95% at 12m: ${fmt(b365.highs["80"])} – ${fmt(b365.highs["95"])}`,
      p.amplitude ? `cycle amplitude model: ${fmt(p.amplitude.next_peak)} decaying, ${fmt(p.amplitude.flat_peak)} flat` : "cycle amplitude model unavailable",
      `recovers the ${fmt(p.ath)} all-time high and extends`,
    ], p.bear_scenarios.slice().reverse().map((s) => `<span class="chip">−${s.drawdown_pct}% → <b>${fmt(s.price)}</b></span>`)) +
    tile("bottom", r.lo, "var(--down)", [
      `volatility band 5–20% at 12m: ${fmt(b365.lows["95"])} – ${fmt(b365.lows["90"])}`,
      an.low_pct ? `analogs 25–50th percentile: ${fmt(p.price * (1 + an.low_pct["25"]))} – ${fmt(p.price * (1 + an.low_pct["50"]))}` : "analog study unavailable",
      lowNote,
    ], [
      `<span class="chip">now <b>${fmt(p.price)}</b></span>`,
      `<span class="chip">drawdown <b>${pct(p.dd_from_ath_pct)}</b></span>`,
      `<span class="chip">EWMA vol <b>${p.ewma_vol_pct}%</b></span>`,
    ]);
}

function rangeBar(label, lo, hi, values, color, fmtVals) {
  const all = values.filter((v) => Number.isFinite(v));
  const min = Math.min(...all), max = Math.max(...all);
  const span = max - min || 1;
  const X = (v) => ((v - min) / span) * 100;
  const band = `<rect x="0" y="6" width="100" height="6" rx="3" fill="var(--line)"/>
    <rect x="${X(lo)}" y="6" width="${Math.max(X(hi) - X(lo), 1)}" height="6" rx="3" fill="${color}" opacity=".55"/>`;
  const dots = values.map((v) => `<circle cx="${X(v)}" cy="9" r="2.5" fill="${color}"/>`).join("");
  return `<div class="figure__row"><span class="figure__key">${label}</span>
    <svg viewBox="0 0 100 18" preserveAspectRatio="none" role="img" aria-label="${label} range ${fmt(lo)} to ${fmt(hi)}">${band}${dots}</svg></div>
    <div class="figure__val">${fmtVals}</div>`;
}

function renderEvidence(p, an) {
  const panel = (title, note, body, footnote) => `
    <article class="panel">
      <h3>${title}</h3>
      ${note ? `<p class="tile__sub" style="margin:-4px 0 12px">${note}</p>` : ""}
      ${body}
      ${footnote ? `<p class="caveat">${footnote}</p>` : ""}
    </article>`;

  const bands = p.bands.map((b) => `
    <div class="figure">
      ${rangeBar(`${b.horizon}d`, b.lows["90"], b.highs["90"], [b.lows["95"], b.lows["90"], b.lows["80"], b.highs["80"], b.highs["90"], b.highs["95"]], "var(--acc)",
        `${fmt(b.lows["90"])} – ${fmt(b.highs["90"])}`)}
    </div>`).join("");

  const a = p.amplitude || {};
  const ampBody = `
    <div class="figure">
      ${rangeBar("log10 peaks", Math.min(...(a.log10_peaks || [0])), Math.max(...(a.log10_peaks || [0])), a.log10_peaks || [0], "var(--warn)",
        (a.log10_peaks || []).join(" → ") || "—")}
    </div>
    <div class="stat" style="margin-top:.75rem"><span class="stat__k">increment decay</span><span class="stat__v">${a.decay ?? "—"}</span></div>
    <div class="stat"><span class="stat__k">next peak · decaying</span><span class="stat__v up">${fmt(a.next_peak)}</span></div>
    <div class="stat"><span class="stat__k">next peak · flat increment</span><span class="stat__v up">${fmt(a.flat_peak)}</span></div>
    <p class="caveat">Fitted on ${(a.log10_peaks || []).length} cycle peaks. Extrapolating three observations is a scenario, not a forecast.</p>`;

  const hp = an.high_pct || {}, lp = an.low_pct || {};
  const anaBody = `
    <div class="figure">
      ${rangeBar("fwd high", hp["10"] ?? 0, hp["90"] ?? 1, [hp["10"], hp["25"], hp["50"], hp["75"], hp["90"]].filter(Number.isFinite), "var(--up)",
        `+${Math.round((hp["25"] ?? 0) * 100)}% → +${Math.round((hp["50"] ?? 0) * 100)}%`)}
      ${rangeBar("fwd low", lp["90"] ?? 0, lp["10"] ?? -1, [lp["10"], lp["25"], lp["50"], lp["75"], lp["90"]].filter(Number.isFinite), "var(--down)",
        `${Math.round((lp["50"] ?? 0) * 100)}% → ${Math.round((lp["25"] ?? 0) * 100)}%`)}
    </div>
    <div class="stat" style="margin-top:.75rem"><span class="stat__k">independent episodes</span><span class="stat__v">${an.episodes ?? "—"}</span></div>
    <div class="stat"><span class="stat__k">closest match</span><span class="stat__v">${an.sample && an.sample[0] ? an.sample[0].date : "—"}</span></div>
    <p class="caveat">De-duplicated to episodes ≥120 days apart on Binance history only (2017→). Effectively three bear events: treat the tails as unusable.</p>`;

  $("pred-evidence").innerHTML =
    panel("Volatility bands", "No-drift random walk from the last close; markers are the 5/20/80/90/95th percentiles", bands,
      "Zero drift is a modelling choice, not a forecast of direction. Bands size dispersion only.") +
    panel("Cycle amplitude", "log10 of each cycle peak", ampBody) +
    panel("Technical analogs", "Forward 12-month outcome of the nearest historical states", anaBody);
}

function drawChart(d) {
  const s = d.history.series, h = 430;
  const label = `last ${fmt(d.prediction.price)}`;
  const gutter = Math.max(96, label.length * 7.2);
  const m = { t: 14, r: 14 + gutter, b: 26, l: 62 };
  const w = m.l + m.r + (1200 - 62 - 14);
  const X = (i) => m.l + (i / (s.length - 1)) * (w - m.l - m.r);
  const cs = s.map((r) => r.c), lo = Math.min(...cs), hi = Math.max(...cs);
  const idx = Object.fromEntries(s.map((r, i) => [r.d, i]));

  const markers = [];
  const cur = d.prediction.cycle;
  (d.history.halvings || []).forEach((hv) => markers.push({ date: hv.date, color: "var(--acc)", text: "halving" }));
  (d.history.strategy || []).forEach((c) => {
    markers.push({ date: c.first_buy, color: "var(--up)", text: "buy start" });
    // for the cycle still running, the newest marker is the last buy actually placed;
    // it only becomes "buy stop" once the whole buying window has closed
    const running = c.buy_halving === cur.halving && cur.buy_status !== "done";
    markers.push({ date: c.last_buy, color: "var(--up)", text: running ? "last buy" : "buy stop" });
    if (c.status === "closed") markers.push({ date: c.exit_date, color: "var(--down)", text: "sell" });
  });
  const placed = markers.filter((mk) => idx[mk.date] !== undefined)
    .map((mk) => {
      const text = `${mk.text} ${mk.date}`;
      return { ...mk, x: X(idx[mk.date]), text, w: text.length * 5.7 };
    })
    .sort((a, b) => a.x - b.x);

  // pack the dates into rows along the bottom axis so none collide
  const rows = [];
  placed.forEach((mk) => {
    let row = rows.findIndex((r) => r < mk.x - mk.w / 2);
    if (row === -1) { row = rows.length; rows.push(0); }
    rows[row] = mk.x + mk.w / 2;
    mk.row = row;
    mk.labelX = Math.min(Math.max(mk.x, mk.w / 2 + 2), w - mk.w / 2 - 2);
  });
  m.b = 10 + rows.length * 13 + 6;
  const axisY = h - m.b;
  const Y = (v) => m.t + (Math.log(hi) - Math.log(v)) / (Math.log(hi) - Math.log(lo)) * (axisY - m.t);

  let g = "";
  for (let k = 0; k <= 4; k++) {
    const v = Math.exp(Math.log(lo) + (k / 4) * (Math.log(hi) - Math.log(lo)));
    const y = Y(v);
    g += `<line x1="${m.l}" x2="${w - m.r}" y1="${y}" y2="${y}" stroke="var(--line)"/>` +
         `<text x="${m.l - 8}" y="${y + 4}" fill="var(--mut)" font-size="11" text-anchor="end">$${Math.round(v).toLocaleString()}</text>`;
  }
  g += `<line x1="${m.l}" x2="${w - m.r}" y1="${axisY}" y2="${axisY}" stroke="var(--line)"/>`;

  const lastI = s.length - 1;
  const lastY = Y(s[lastI].c);
  g += `<line x1="${m.l}" x2="${X(lastI)}" y1="${lastY}" y2="${lastY}" stroke="var(--txt)" stroke-width="1" stroke-dasharray="4 3" opacity=".6"/>`;
  g += `<circle cx="${X(lastI)}" cy="${lastY}" r="4" fill="var(--acc)"/>`;
  g += `<line x1="${X(lastI)}" x2="${X(lastI)}" y1="${m.t}" y2="${axisY}" stroke="var(--acc)" stroke-width="1" stroke-dasharray="4 3" opacity=".5"/>`;
  g += `<text x="${X(lastI) + 9}" y="${lastY - 5}" fill="var(--acc)" font-size="12" font-weight="600">${label}</text>`;
  g += `<text x="${X(lastI) + 9}" y="${lastY + 10}" fill="var(--mut)" font-size="11">${s[lastI].d}</text>`;

  g += `<polyline fill="none" stroke="var(--txt)" stroke-width="1.1" opacity=".85" points="${s.map((r, i) => `${X(i)},${Y(r.c)}`).join(" ")}"/>`;

  placed.forEach((mk) => {
    const dash = mk.text === "buy stop" ? ' stroke-dasharray="3 3"' : "";
    g += `<line x1="${mk.x}" x2="${mk.x}" y1="${m.t}" y2="${axisY}" stroke="${mk.color}" stroke-width="1" opacity=".6"${dash}/>` +
         `<line x1="${mk.labelX}" x2="${mk.x}" y1="${axisY + 2 + mk.row * 13 - 4}" y2="${axisY + 2}" stroke="${mk.color}" stroke-width="1" opacity=".4"/>` +
         `<text x="${mk.labelX}" y="${axisY + 15 + mk.row * 13}" fill="${mk.color}" font-size="10" text-anchor="middle">${mk.text}</text>`;
  });

  $("chart").innerHTML = `<svg viewBox="0 0 ${w} ${h}" role="img"
    aria-label="BTC daily close with halving, buy-window and sell markers, each dated along the bottom axis. Last close ${fmt(d.prediction.price)} on ${s[lastI].d}.">${g}</svg>`;
}

function renderTables(d) {
  $("halvings").innerHTML = `<thead><tr><th>event</th><th>block</th><th>date</th><th>subsidy BTC</th><th>days since prev</th><th>estimate</th></tr></thead><tbody>` +
    d.history.halvings.map((r) => `<tr><td>${r.event}</td><td>${r.block_height}</td><td>${r.date}</td><td>${r.new_subsidy_btc}</td><td>${r.days_since_prev || "—"}</td><td>${r.is_estimate === "no" ? "no" : "<span class='warn'>yes</span>"}</td></tr>`).join("") + "</tbody>";

  $("cycles").innerHTML = `<thead><tr><th>cycle</th><th>A</th><th>B</th><th>high</th><th>date</th><th>d A→high</th><th>low</th><th>date</th><th>d A→low</th></tr></thead><tbody>` +
    d.history.cycles.map((r) => `<tr><td>${r.cycle}</td><td>${r.halving_a}</td><td>${r.halving_b || "open"}</td>
      <td class="up">${fmt(r.high_close)}</td><td>${r.high_date}</td><td>${r.days_from_a_to_high}</td>
      <td class="down">${fmt(r.low_close)}</td><td>${r.low_date}</td><td>${r.days_from_a_to_low}</td></tr>`).join("") + "</tbody>";

  $("strategy").innerHTML = `<thead><tr><th>cycle</th><th>capital in</th><th>installment</th><th>buys</th><th>avg px</th><th>exit date</th><th>exit px</th><th>cash out</th><th>×</th></tr></thead><tbody>` +
    d.history.strategy.map((r) => `<tr><td>${r.cycle}</td><td>${fmt(r.capital_at_start, 0)}</td><td>${fmt(r.installment, 0)}</td>
      <td>${r.mondays}</td><td>${fmt(r.avg_buy_price)}</td><td>${r.exit_date}</td>
      <td>${typeof r.exit_price === "number" ? fmt(r.exit_price) : r.exit_price}</td>
      <td>${fmt(r.cash_out, 0)}</td><td>${r.value_multiple || "—"}</td></tr>`).join("") + "</tbody>";
}

const build = (document.currentScript && (document.currentScript.src.match(/v=([0-9a-f]+)/) || [])[1]) || "dev";
$("build").textContent = "build " + build;
$("interval").addEventListener("change", arm);
$("pred-retry").addEventListener("click", () => loadSnapshot(true).then(() => scheduleRetry()));
$("refresh-now").addEventListener("click", () => loadSnapshot(true).then(() => scheduleRetry()));
arm();
pollTick();