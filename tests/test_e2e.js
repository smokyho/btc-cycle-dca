const fs = require("fs");
const vm = require("vm");

const BASE = process.argv[2] || "http://127.0.0.1:7070";
const ids = ["stamp", "live", "cards", "states", "axis", "axis-table", "pred-tiles", "pred-evidence",
  "pred-error", "pred-error-msg", "pred-retry", "pred-panel", "chart", "halvings", "cycles",
  "strategy", "interval", "countdown", "generated", "refresh-now", "build"];
const store = {};

const sandbox = {
  console,
  setInterval: () => 0,
  clearInterval: () => {},
  setTimeout: () => 0,
  clearTimeout: () => {},
  fetch: (u, o) => fetch(String(u).startsWith("http") ? u : BASE + u, o),
  document: {
    currentScript: null,
    getElementById: (id) => {
      if (!store[id]) store[id] = {
        innerHTML: "", textContent: "", hidden: false, value: "30", dataset: {},
        classList: { _s: new Set(), add(c) { this._s.add(c); }, remove(c) { this._s.delete(c); }, toggle(c, f) { f ? this._s.add(c) : this._s.delete(c); }, contains(c) { return this._s.has(c); } },
        setAttribute() {}, addEventListener() {},
      };
      return store[id];
    },
  },
};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync("web/app.js", "utf8"), sandbox);

let fails = 0;
const check = (ok, msg) => { console.log((ok ? "OK:   " : "FAIL: ") + msg); if (!ok) fails += 1; };

function svgCheck(id) {
  const svg = (store[id].innerHTML.match(/<svg[\s\S]*<\/svg>/) || [""])[0];
  const vb = (svg.match(/viewBox="0 0 ([\d.]+) ([\d.]+)"/) || []).slice(1).map(Number);
  const [W, H] = vb;
  const texts = [...svg.matchAll(/<text x="([-\d.]+)" y="([-\d.]+)"[^>]*text-anchor="(start|middle|end)"[^>]*>([^<]*)<\/text>/g)]
    .map((m) => ({ x: +m[1], y: +m[2], anchor: m[3], text: m[4] }));
  const wOf = (t) => t.length * 6.4;
  const bad = [];
  for (const t of texts) {
    const x0 = t.anchor === "end" ? t.x - wOf(t.text) : t.anchor === "middle" ? t.x - wOf(t.text) / 2 : t.x;
    if (x0 < -1) bad.push(`left overflow "${t.text}"`);
    if (x0 + wOf(t.text) > W + 1) bad.push(`right overflow "${t.text}"`);
    if (t.y > H) bad.push(`below canvas "${t.text}"`);
  }
  const rects = [...svg.matchAll(/<rect x="[-\d.]+" y="[-\d.]+" width="([\d.]+)"/g)].map((m) => +m[1]);
  return { W, H, texts: texts.length, bad, thinBars: rects.filter((w) => w < 3).length, svg };
}

(async () => {
  console.log("=== live endpoints ===");
  const res = await fetch(BASE + "/api/snapshot", { cache: "no-store" });
  const tickRes = await fetch(BASE + "/api/tick", { cache: "no-store" });
  const raw = await res.text();
  const tickRaw = await tickRes.text();
  const data = JSON.parse(raw);
  const tk = JSON.parse(tickRaw);
  console.log(`snapshot ${res.status} ${raw.length} bytes | tick ${tickRes.status} ${tickRaw.length} bytes`);
  check(res.ok && tickRes.ok, "both endpoints 200");
  check(tickRaw.length * 100 < raw.length, `tick is >100x smaller (${Math.round(raw.length / tickRaw.length)}x)`);
  check(tk.daily_date === data.prediction.price_date, `tick data_date matches snapshot price_date (${tk.daily_date})`);
  check(tk.changed === false, "changed=false while the exchange has not rolled over");
  check(tk.exchange_date["1d"] === tk.data_date["1d"], "held daily bar equals latest COMPLETED exchange bar");
  check(tk.seconds_to_daily_close > 0 && tk.seconds_to_daily_close < 86400, `seconds_to_daily_close sane (${tk.seconds_to_daily_close})`);

  console.log("\n=== render ===");
  try {
    sandbox.render(data);
    console.log("render(): OK");
  } catch (e) {
    check(false, "render() threw -> " + e.message);
  }
  for (const id of ["cards", "states", "axis", "axis-table", "pred-tiles", "pred-evidence", "chart", "halvings", "cycles", "strategy"]) {
    const len = (store[id].innerHTML || "").length;
    if (!len) check(false, `${id} rendered EMPTY`);
  }
  console.log("all panels rendered");
  const all = [...ids].map((i) => store[i] && store[i].innerHTML).join("");
  check(!/NaN|undefined|Infinity/.test(all), "no NaN/undefined/Infinity in output");

  console.log("\n=== svg geometry ===");
  for (const id of ["axis", "chart"]) {
    const r = svgCheck(id);
    console.log(`${id}: viewBox ${r.W}x${r.H}, ${r.texts} labels, ${r.thinBars} thin bars`);
    check(r.bad.length === 0, `${id} text inside canvas${r.bad.length ? " -> " + r.bad.join("; ") : ""}`);
    check(r.thinBars === 0, `${id} has no degenerate bars`);
  }
  check(/last \$/.test(store["chart"].innerHTML), "chart carries the last-price pointer");

  const chartSvg = store["chart"].innerHTML;
  const cH = Number((chartSvg.match(/viewBox="0 0 [\d.]+ ([\d.]+)"/) || [])[1]);
  const dates = [...chartSvg.matchAll(/<text x="([-\d.]+)" y="([\d.]+)"[^>]*font-size="10"[^>]*>([^<]+)<\/text>/g)]
    .map((m) => ({ x: +m[1], y: +m[2], d: m[3], w: m[3].length * 5.7 }));
  const rowsOf = {};
  dates.forEach((t) => { (rowsOf[t.y] = rowsOf[t.y] || []).push(t); });
  let overlaps = 0;
  for (const y of Object.keys(rowsOf)) {
    const row = rowsOf[y].sort((a, b) => a.x - b.x);
    for (let i = 1; i < row.length; i++) if (row[i].x - row[i].w / 2 < row[i - 1].x + row[i - 1].w / 2) overlaps++;
  }
  console.log(`marker labels on bottom axis: ${dates.length} in ${Object.keys(rowsOf).length} rows, y=${Object.keys(rowsOf).sort((a,b)=>a-b).join("/")} (viewBox h=${cH})`);
  check(overlaps === 0, `no marker dates overlap (${overlaps})`);
  check(dates.every((t) => t.y > cH * 0.85), "marker labels sit in the bottom axis band");

  // the open cycle's newest buy marker must read "last buy" until the window closes
  const lastBuys = dates.filter((t) => t.d.startsWith("last buy"));
  const buyStops = dates.filter((t) => t.d.startsWith("buy stop"));
  const cyc = data.prediction.cycle;
  console.log(`marker kinds: ${lastBuys.length} "last buy", ${buyStops.length} "buy stop", window ${cyc.buy_status}`);
  check(cyc.buy_status === "done" ? lastBuys.length === 0 : lastBuys.length === 1,
    `open window shows exactly one "last buy" (${lastBuys.length}) and no false "buy stop"`);
  const curStrategy = (data.history.strategy || []).find((c) => c.buy_halving === cyc.halving);
  check(lastBuys.length === 1 && lastBuys[0].d === `last buy ${curStrategy.last_buy}`,
    `the last-buy marker is the current cycle's latest placed buy (${lastBuys[0] && lastBuys[0].d})`);
  check(dates.every((t) => /20\d\d-\d\d-\d\d$/.test(t.d)), "every marker label keeps its description and date");
  check(["halving", "buy start", "buy stop", "sell"].every((k) => dates.some((t) => t.d.startsWith(k))), "all four marker kinds are labelled");

  console.log("\n=== header state ===");
  console.log(`stamp="${store["stamp"].textContent}" countdown="${store["countdown"].textContent}"`);
  check(/close$/.test(store["stamp"].textContent), "stamp states the settled close date");

  console.log("\n=== day gating (client) ===");
  const calls = [];
  sandbox.fetch = async (u) => {
    calls.push(String(u));
    if (String(u).startsWith("/api/tick")) return { ok: true, json: async () => ({ ...tk, changed: false }) };
    return { ok: true, json: async () => data };
  };
  calls.length = 0;
  await sandbox.pollTick();
  check(!calls.some((c) => c.includes("/api/snapshot")), "unchanged tick -> no snapshot refetch");

  sandbox.fetch = async (u) => {
    calls.push(String(u));
    if (String(u).startsWith("/api/tick")) return { ok: true, json: async () => ({ ...tk, changed: true }) };
    return { ok: true, json: async () => data };
  };
  calls.length = 0;
  await sandbox.pollTick();
  check(calls.filter((c) => c.includes("/api/snapshot")).length === 1, "changed tick -> exactly one snapshot fetch");

  sandbox.fetch = async (u) => {
    calls.push(String(u));
    return { ok: false, status: 500, json: async () => ({}) };
  };
  await sandbox.loadSnapshot(true);
  check(store["pred-error"].hidden === false, "failed snapshot shows the notice");
  check(/HTTP 500/.test(store["pred-error-msg"].textContent), "failure message names the real cause: " + store["pred-error-msg"].textContent);

  sandbox.fetch = async () => { throw new TypeError("Failed to fetch"); };
  await sandbox.loadSnapshot(false);
  check(/Failed to fetch/.test(store["pred-error-msg"].textContent), "network error names the real cause: " + store["pred-error-msg"].textContent);

  console.log("\n=== css guard ===");
  const css = fs.readFileSync("web/style.css", "utf8");
  const guard = /\[hidden\]\s*\{[^}]*display:\s*none\s*!important/.test(css);
  check(guard, "[hidden] forced to display:none (banner cannot leak)");
  const htmlFile = fs.readFileSync("web/index.html", "utf8");
  check(/\.cards\s*\{[^}]*grid-template-columns:\s*minmax\(0,1fr\)/.test(css), "cards are single column at the base (mobile-first)");
  check(/@media \(min-width:1000px\)\{\s+\.cards\{grid-template-columns:repeat\(4,/.test(css), "cards reach 4 columns at 1000px");
  check(!/@media \(max-width:[^)]*\)\{\.cards/.test(css), "no desktop-first max-width rule left for .cards");
  check((htmlFile.match(/class="scroll-x"/g) || []).length === 5, "wide charts and tables sit in scroll containers (5)");
  check(/@media \(min-width:560px\)/.test(css) && /@media \(min-width:820px\)/.test(css), "enhancement breakpoints are min-width (mobile-first)");
  check(/min-width:520px/.test(css) && /min-width:680px/.test(css), "tables and the chart keep a legible min-width on a phone");

  // resolve the cascade the way a browser would, at the widths we claim to support
  const blocks = [...css.matchAll(/@media \(min-width:(\d+)px\)\{([\s\S]*?)\n\}/g)]
    .map((m) => [Number(m[1]), m[2]]).sort((a, b) => a[0] - b[0]);
  const colsAt = (width) => {
    const baseRule = (css.match(/^\.cards\{([^}]*)\}/m) || [])[1] || "";
    let spec = baseRule;
    for (const [bp, body] of blocks) {
      if (width >= bp) {
        const m2 = body.match(/\.cards\{([^}]*)\}/);
        if (m2) spec = m2[1];
      }
    }
    if (!/repeat\(/.test(spec)) return 1;
    return Number((spec.match(/repeat\((\d+)/) || [])[1] || 1);
  };
  const targets = [320, 375, 560, 768, 1000, 1024, 1440];
  const cols = targets.map(colsAt);
  console.log(`cascade: ${targets.map((w, i) => `${w}px=${cols[i]}`).join(" ")}`);
  check(cols.every((c, i) => i === 0 || c >= cols[i - 1]), "card columns never shrink as the viewport grows");
  check(cols[0] === 1 && cols.at(-1) === 4, `1 column at 320px and 4 at 1440px (got ${cols[0]} / ${cols.at(-1)})`);
  check(targets.filter((w, i) => w >= 1000 && cols[i] === 4).length === targets.filter((w) => w >= 1000).length, "every width >= 1000px gets 4 columns");

  // every element with a fixed width wider than a phone must be in a scroll container
  const wrappedIds = new Set([...htmlFile.matchAll(/<div class="scroll-x">\s*<\w+[^>]*id="([\w-]+)"/g)].map((m) => m[1]));
  const bare = css.replace(/\/\*[\s\S]*?\*\//g, "");
  const wide = [];
  for (const m2 of bare.matchAll(/(?:^|\}|\n)\s*([^{}@\/][^{}]*?)\{([^}]*)\}/g)) {
    const sel = m2[1].trim().replace(/\s+/g, " ");
    if (sel.includes("@")) continue;
    const w2 = (sel + " " + m2[2]).match(/(?:-min-)?width:(\d+)px/);
    if (!w2 || Number(w2[1]) <= 320) continue;
    const ids = [...sel.matchAll(/#([\w-]+)/g)].map((x) => x[1]);
    if (!ids.some((id) => wrappedIds.has(id)) && sel !== "table") wide.push(sel);
  }
  check(wide.length === 0, `no element wider than a phone sits outside a scroll container${wide.length ? " -> " + wide.join(", ") : ""}`);
  const html = htmlFile;
  const explains = [...html.matchAll(/class="explain"/g)].length;
  const groups = [...html.matchAll(/<(?:section|div)[^>]*id="(?:cards|states|pred-tiles|pred-evidence|chart|halvings|cycles|strategy)"/g)].length;
  check(explains >= groups, `plain-English description under every group (${explains} descriptions / ${groups} data groups)`);
  const risky = ["notice"].filter((c) => new RegExp(`\\.${c}\\s*\\{[^}]*display:`).test(css));
  check(guard || !risky.length, `author display rules on hidden elements: ${risky.join(",") || "none"}`);

  console.log(fails ? `\n${fails} CHECK(S) FAILED` : "\nall checks passed");
  process.exitCode = fails ? 1 : 0;
})();