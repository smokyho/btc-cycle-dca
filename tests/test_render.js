const fs = require("fs");
const vm = require("vm");

const snap = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const store = {};
const ids = ["stamp", "live", "cards", "states", "axis", "axis-table", "pred-tiles", "pred-evidence",
  "pred-error", "pred-error-msg", "pred-retry", "pred-panel", "chart", "halvings", "cycles",
  "strategy", "interval", "countdown", "generated", "refresh-now", "build"];

const sandbox = {
  console,
  setInterval: () => 0,
  clearInterval: () => {},
  setTimeout: () => 0,
  clearTimeout: () => {},
  fetch: async () => ({ ok: true, status: 200, json: async () => snap }),
  document: {
    currentScript: null,
    getElementById: (id) => {
      if (!ids.includes(id)) throw new Error("unknown element: " + id);
      if (!store[id]) store[id] = { innerHTML: "", hidden: false, value: "60", attrs: {},
        classList: { add() {}, remove() {} },
        setAttribute(k, v) { this.attrs[k] = v; },
        addEventListener() {} };
      return store[id];
    },
  },
};

vm.createContext(sandbox);
vm.runInContext(fs.readFileSync("web/app.js", "utf8"), sandbox);

try {
  sandbox.render(snap);
} catch (e) {
  console.log("RENDER ERROR:", e.message);
  console.log(e.stack.split("\n").slice(0, 4).join("\n"));
  process.exit(1);
}

setTimeout(() => {
  const html = store.cards.innerHTML;
  const cards = [...html.matchAll(/<div class="k">([^<]*)<\/div><div class="v ([^"]*)">([^<]*)<\/div><div class="k">([^<]*)<\/div>/g)];
  console.log("cards rendered:", cards.length);
  for (const [, k, cls, v, s] of cards) {
    console.log(`  ${String(k).padEnd(20)} ${String(v).padEnd(12)} [${cls || "-"}]  ${s}`);
  }
  const junk = cards.filter(([, k, , v]) => String(k).length <= 1 || String(v).length === 0);
  console.log(junk.length ? "FAIL: junk cards present: " + JSON.stringify(junk) : "OK: no malformed cards");
  let bad = [];
  for (const id of ["states", "axis", "axis-table", "pred-tiles", "pred-evidence", "chart", "halvings", "cycles", "strategy"]) {
    const html = store[id].innerHTML || "";
    console.log(`  ${id.padEnd(13)} ${html.length > 0 ? "rendered" : "EMPTY"} (${html.length} bytes)`);
    if (/NaN|undefined|Infinity/.test(html)) bad.push(id);
  }
  console.log(bad.length ? "FAIL: NaN/undefined in: " + bad.join(", ") : "OK: no NaN/undefined/Infinity in output");
  const svg = (store["axis"].innerHTML.match(/<svg[\s\S]*<\/svg>/) || [""])[0];
  const coords = [...svg.matchAll(/[xc](?=" )?="(-?[\d.]+)"/g)].map((m) => Number(m[1]));
  console.log("axis viewBox:", (svg.match(/viewBox="([^"]+)"/) || [])[1]);
  console.log("axis aria-label:", ((svg.match(/aria-label="([^"]+)"/) || [])[1] || "").slice(0, 120));

  const vb = (svg.match(/viewBox="0 0 ([\d.]+) ([\d.]+)"/) || []).slice(1).map(Number);
  const [VW, VH] = vb;
  const probs = [];
  const num = (t, a) => [...svg.matchAll(new RegExp(t + '="' + a + '"', "g"))].map((m) => Number(m[1]));
  for (const attr of ["x", "x1", "x2", "cx"]) {
    for (const v of num(attr, "([-\\d.]+)")) if (v < -1 || v > VW + 1) probs.push(`${attr}=${v.toFixed(1)} outside 0..${VW}`);
  }
  for (const attr of ["y", "y1", "y2", "cy"]) {
    for (const v of num(attr, "([-\\d.]+)")) if (v < -1 || v > VH + 1) probs.push(`${attr}=${v.toFixed(1)} outside 0..${VH}`);
  }
  const rects = [...svg.matchAll(/<rect x="([-\d.]+)" y="([-\d.]+)" width="([-\d.]+)"/g)].map((m) => ({ x: +m[1], w: +m[3] }));
  rects.filter((r) => r.w < 3).forEach((r) => probs.push(`rect too thin: ${r.w}px`));
  const texts = [...svg.matchAll(/<text x="([-\d.]+)" y="([-\d.]+)"[^>]*text-anchor="(start|middle|end)"[^>]*>([^<]*)<\/text>/g)]
    .map((m) => ({ x: +m[1], y: +m[2], anchor: m[3], text: m[4] }));
  const approxW = (t) => t.length * 6.6;
  for (const t of texts) {
    const x0 = t.anchor === "end" ? t.x - approxW(t.text) : t.anchor === "middle" ? t.x - approxW(t.text) / 2 : t.x;
    const x1 = x0 + approxW(t.text);
    if (x0 < -1) probs.push(`text overflows left (x0=${x0.toFixed(0)}): "${t.text}"`);
    if (x1 > VW + 1) probs.push(`text overflows right (x1=${x1.toFixed(0)}): "${t.text}"`);
    if (t.y > VH) probs.push(`text below canvas: "${t.text}"`);
  }
  const legend = texts.filter((t) => t.y >= 100);
  const lanes = texts.filter((t) => t.y < 100);
  for (let i = 0; i < lanes.length; i++) {
    for (let j = i + 1; j < lanes.length; j++) {
      const a0 = lanes[i].anchor === "end" ? lanes[i].x - approxW(lanes[i].text) : lanes[i].x;
      const b0 = lanes[j].anchor === "end" ? lanes[j].x - approxW(lanes[j].text) : lanes[j].x;
      const overlap = a0 < b0 + approxW(lanes[j].text) && b0 < a0 + approxW(lanes[i].text) &&
        Math.abs(lanes[i].y - lanes[j].y) < 10;
      if (overlap) probs.push(`lane label overlap: "${lanes[i].text}" / "${lanes[j].text}"`);
    }
  }
  console.log(`axis geometry: ${rects.length} bars, ${texts.length} labels (${legend.length} in legend), viewBox ${VW}x${VH}`);
  console.log(probs.length ? "FAIL:\n  " + probs.join("\n  ") : "OK: axis geometry clean (no overflow, no overlap)");
}, 500);