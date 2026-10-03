# AGENTS.md

Operating manual for anyone — human or agent — changing this repository.

The dashboard is small and has no framework, which makes most things easy and a
handful of things fragile. This file is mostly a list of **invariants**: things
that look like free variables but are load-bearing, where breaking them produces
a page that renders plausibly while being wrong.

Read this before changing `engine.py`, `web/`, or the test harnesses.

---

## Ground rules

1. **No secrets, ever.** Every data source is a public, keyless endpoint. Do not
   introduce an API key, token, webhook or account id. There is no `.env` and
   there must never be one. If a change would need a credential, it is the wrong
   change.
2. **Stdlib only outside `numpy` / `matplotlib`.** No web framework, no HTTP
   client library, no CSV library, no date library, no templating engine. The
   dependency tree is two packages, deliberately.
3. **No CDN, no build step, no bundler.** `web/` is three files served verbatim.
   Anything a browser can load must already be in the repo.
4. **Never serve a partial series.** If a fetch fails, fall back to whatever is
   in `data/`. A dashboard showing half a year of candles is worse than a stale one.
5. **Only completed bars.** A forming bar is not data. See invariant 1.
6. **No comments that restate the code.** The existing comments explain *why* a
   non-obvious choice was made. Keep that bar; do not lower it.

---

## Architecture

```
pipeline/*.py  ──writes──→  data/*.csv  ──read by──→  engine.py  ──JSON──→  web/app.js
      (13 scripts)          (gitignored)           (+ live Binance)      (vanilla JS)
```

`pipeline/` is the reproducible record: it is how every number in `data/` is
produced, in dependency order. `engine.py` reads those CSVs *and* fetches live
Binance candles, preferring live data and falling back to CSV. `server.py` is a
thin stdlib HTTP layer. `web/` is the whole client.

**`data/` and `charts/` are build output and are gitignored.** There is no
committed CSV. `make serve` runs `make refresh` first, so the dashboard is never
more stale than the clone that started it. Never edit a CSV by hand and never
commit one — change the script that writes it.

One consequence to keep in mind: a bare clone has no data at all, so any target
that reads `data/` must fail with a message telling the user to run
`make refresh`. `make analyze` guards for exactly this.

---

## Invariants

### 1. Completed bars only (`engine.py:candles`, `probe_bars`)

Binance returns the in-progress bar alongside closed ones. Filter on the bar's
**close time**, `k[6] >= now_ms` → skip.

Weekly and monthly bars are **not epoch-aligned**, so you cannot judge completion
by `open_ms % interval == 0`. `fetch_btc_daily.py` may do exactly that only
because it fetches the `1d` interval alone; `fetch_btc_mtf.py` must not.

Every fetcher filters on the bar's **close time** (`k[6]`), never its open time.
An open-time test only rejects bars in the future and happily stores the bar that
is forming *right now* — which then becomes the chart's "last close" while the
cards report the real, settled one. That bug shipped once in `fetch_btc_daily.py`
and is the reason both fetchers now hoist `now` and compare `k[6]`.

`probe_bars()` must report the newest **completed** bar, because the cached
series only stores completed ones. Comparing a completed held bar against an
in-progress probe bar makes every poll report `changed: true` forever.

### 2. Snapshot day-gating (`engine.py:snapshot`)

A daily series changes once a day. Recomputing on every poll burns CPU and
~250 KB of bandwidth. The snapshot is rebuilt only when:

- a bar rolled over (detected by `probe_bars`), **or**
- `force=True`, **or**
- no snapshot is cached, **or**
- the held-bar signature changed (`snapshot_sig`).

If you add a field to the snapshot, decide whether it can change without a
rollover. If it can, it does not belong in the cached snapshot, or the gating key
must include it. Keep `snapshot_date` in sync with `snapshot_sig` — `tick()`
reads it to decide `changed`.

### 2b. Startup freshness check (`server.py:sync_if_stale`)

`data/` is gitignored, so a clone can be arbitrarily old. Before the socket is
bound, `sync_if_stale()` compares the newest daily bar on disk against Binance's
and runs `make sync` if they differ.

Three rules that are easy to break:

- **Run it before `ThreadingHTTPServer(...)`, never after.** Serving first and
  repairing later means the page is briefly stale and then dies under the user.
  It also removes any need for a restart loop, which is what turns a transient
  network failure into a spin.
- **A failed probe is not evidence of staleness.** If `probe_bars()["1d"]` is
  `None`, serve what is on disk and say so. Treating "cannot reach" as "behind"
  is how a rate limit becomes an infinite refresh loop.
- **Resume, never append.** The resumable fetchers re-`startTime` from the last
  bar on disk and rewrite the file whole. There is no append/merge path, so there
  is no duplicate or partial-write failure mode. `fetch_btc_daily.py` once had
  `collect(start_ms)` with its argument immediately overwritten by `START_MS`,
  which silently turned every "sync" into a full refetch — the resume arithmetic
  is therefore worth unit-checking whenever it is touched.

`fetch_halvings.py` reuses cached dates only for halvings flagged
`is_estimate == no`. A mined block's timestamp cannot change; an *estimated* date
can, because it moves with the observed block rate.

### 3. Grace period (`engine.py:GRACE_SECONDS`)

Bar boundaries are 60 s in the future. Immediately after midnight UTC the
exchange may still report the previous bar as current. Never probe exactly at a
boundary.

### 4. Element IDs are a three-way contract

An `id` in `web/index.html` is referenced by `web/app.js` **and** allowlisted in
both test harnesses:

- `tests/test_e2e.js` → `ids[]`
- `tests/test_render.js` → `ids[]`

`test_render.js` throws `unknown element` on anything not in its list. When you
add an element to `index.html` that `app.js` reads, **add it to both lists** or
the test suite breaks in a way that looks unrelated to your change.

### 5. `[hidden]` must stay forced

`web/style.css` needs `[hidden] { display: none !important }`. Several class
rules set `display`, which would otherwise beat the browser default and leak the
error banner into the layout. `test_e2e.js` asserts this. Do not remove it.

### 6. Mobile-first, and exactly five scroll containers

Breakpoints are `min-width` only. `test_e2e.js` **resolves the cascade** at
320/375/560/768/1000/1024/1440px and fails if column count ever shrinks as the
viewport grows, if anything ≥320px wide sits outside a scroll container, or if a
`max-width` rule for `.cards` reappears.

One assertion is an exact count:

```js
check((htmlFile.match(/class="scroll-x"/g) || []).length === 5, ...)
```

Adding or removing a `.scroll-x` wrapper means updating that number. Do not
"fix" it by relaxing the check.

### 7. Asset cache-busting (`server.py:index_html`)

`index_html()` rewrites `/app.js` and `/style.css` in the HTML to
`?v=<sha256[:8]>`. The regex only matches those two names, optionally followed by
`?v=<hex>`. A third asset needs a new entry in the tuple in `index_html()`.

### 8. Tests run from the repository root

Both harnesses read `web/app.js` and `web/style.css` by relative path. Use
`make test`, not a direct `node tests/...` from elsewhere.

---

## Layout contract

`pipeline/` scripts are one level below the root, so they compute it as:

```python
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
```

`engine.py` and `server.py` are at the root, so they use a single `dirname`.
**If you add or move a script, fix its `ROOT` accordingly** — getting this wrong
writes a `data/` directory inside `pipeline/` and fails silently on the next run.

Never hardcode a path. Never rely on the working directory. Every script must
work when invoked from anywhere.

---

## Commands

```bash
make install     # numpy, matplotlib
make report      # re-run analysis on existing data/ — NO network
make refresh     # refetch everything + rebuild — network
make sync        # continue from data/, then rebuild — network
make serve       # refresh, then serve on :7070 (binds 0.0.0.0 by default)
make test        # node harnesses — needs a server already running
make help        # all targets
```

`make serve` implies `make refresh`, so the usual invocation touches the network.
`make report` is the offline inner loop and is the one to use when verifying a
logic change; it refuses to run if `data/` is missing rather than silently
succeeding on a partial tree. Use `make refresh` only when the change is about the
fetchers.

Run a single stage directly:

```bash
python3 pipeline/backtest_halving_dca_compound.py
```

---

## Verification

There is no unit-test framework. Before proposing a change:

1. `make report` — the analysis must run clean and the numbers must be sane.
2. `make serve &` then `make test` — every check must pass.
3. For a UI change, confirm `test_render.js` still reports
   `no NaN/undefined/Infinity in output` and `axis geometry clean`. A change that
   produces `NaN` in the DOM passes a visual check and fails a real one.
4. For an engine change, hit `/api/snapshot?force=1` and diff against
   `/api/tick`'s `changed` behaviour — a change that defeats day-gating shows up
   as a snapshot refetch on every poll.

If you change `data/` inputs, regenerate with `make report` rather than editing
CSVs. If you change a fetcher, the CSVs it owns are now stale — say so.
---

## House style

- Python: `from __future__ import annotations` at the top, module docstring that
  states the **method and its assumptions**, then `Input:` / `Output:` lines when
  the script reads or writes a file. `#!/usr/bin/env python3` on executables.
- Broad `except Exception` is deliberate at the network and HTTP boundaries —
  those are annotated `# noqa: BLE001`. Do not add one to pure computation.
- Numeric output is rounded at the boundary, never mid-calculation.
- JavaScript: plain ES2020, no bundler, `const`/`let`, no framework. Charts are
  hand-built SVG strings assigned to `innerHTML`. Match the existing formatting;
  the tests parse this markup with regexes, so attribute order and quoting
  matter more than usual.
- HTML ids are kebab-case; CSS classes are kebab-case; no CSS framework.

---

## Reporting to the user

This project makes financial claims, and the README is written to keep them
honest. When summarising a change:

- **State the limits you did not remove.** Three completed cycles, zero fees,
  index data before 2017, an unmined 5th halving. Do not report "the strategy
  returned x710" without the caveats attached.
- **Never describe a range as a prediction.** They are volatility scenarios and
  an amplitude extrapolation.
- **Do not present the backtest as an expected return.** It is three historical
  observations under zero-cost, zero-friction, pre-specified rules.
- If a fix makes a number look better, that is a signal to check the fix rather
  than to report the improvement.

---

## Files you should read before touching them

| Changing | Read first |
| --- | --- |
| indicators, prediction, caching | `engine.py` (whole — 491 lines, invariants 1–3 live here) |
| the page | `web/index.html`, then `web/app.js`, then `tests/test_e2e.js` |
| stylesheet | `web/style.css`, then the CSS-guard block at the end of `test_e2e.js` |
| a fetcher | its script, plus `build_merged.py` if the schema is consumed downstream |
| pipeline order | `Makefile`, then the `Input:` / `Output:` docstrings |

## Do not

- Add a dependency.
- Add a build step, bundler, or framework.
- Commit `.DS_Store`, `__pycache__`, a virtualenv, or anything under `data/` or
  `charts/` (`.gitignore` already covers these — if one slips through, fix
  `.gitignore`, do not delete the file alone).
- Widen the default `BIND` beyond `0.0.0.0`, or add authentication to the server
  and leave the default reachable.
- Present an estimate as an observation. `is_estimate` exists in the halving CSV
  precisely so this cannot happen silently — respect it.
- Reduce the `Limitations` section of the README without an explicit request.