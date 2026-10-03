# BTC Halving-Cycle Dashboard

An always-on dashboard and reproducible analysis pipeline for Bitcoin's halving cycle.
It measures what actually happened in each completed cycle, backtests a fixed
"52 Monday buys, one sell" strategy against the real price history, and recomputes
a forward price range from live exchange data.

**No API keys. No accounts. No database.** Every data source is a public endpoint.

```
┌─ analysis ──────────────────┐   ┌─ live ──────────────────┐   ┌─ dashboard ──┐
│ 13 stdlib Python scripts    │ → │ engine.py fetches       │ → │ web/         │
│ pipeline/  data/*.csv       │   │ Binance klines on roll  │   │ stdlib HTTP  │
└─────────────────────────────┘   └─────────────────────────┘   └──────────────┘
```

---

## Quick start

```bash
python3 -m pip install -r requirements.txt   # numpy + matplotlib
make serve                                   # → http://127.0.0.1:7070
```

`make serve` is `make refresh` plus the server. **There is no committed data** —
`data/` and `charts/` are gitignored and are rebuilt from the public APIs on every
run, so the dashboard is never more stale than the clone that started it. A cold
start takes about 20 seconds and needs network access on first run.

```bash
make refresh     # refetch + rebuild data/ and charts/           [network]
make sync        # continue from data/ + rebuild                 [network]
make report      # re-run the analysis on the data already there  [no network]
make test        # node test harnesses (against an already-running `make serve`)
make clean       # remove data/ and charts/
```

`make help` lists every target.

### Staying fresh

A clone made 100 days ago has 100-day-old `data/`, so `server.py` checks the
newest daily bar against Binance's before it opens the port:

```
data is 100 day(s) behind the exchange (2026-06-24 vs 2026-10-02) -- syncing
```

If they match it starts immediately. If they don't it updates the data **before**
binding — so the page is never served stale, and a failed sync exits instead of
restarting in a loop. `make sync` continues from the newest bar already on disk
rather than re-downloading nine years: closed klines are immutable, so appending
is safe. 100 days of drift costs about 9s instead of 18s.

Two escape hatches, so this can never trap you offline:

```bash
BTC_DASH_SKIP_SYNC=1 python server.py             # ignore the check, serve data/ as-is
BTC_DASH_MAX_STALENESS_DAYS=1 python server.py    # accept up to a day-old data/
```

If the exchange can't be reached, the check reports that and serves the data on
disk rather than assuming it is stale — a rate limit must not trigger a refresh loop.

---

## What the dashboard shows

| Panel | What it answers |
| --- | --- |
| **Price with cycle markers** | Daily closes with halvings, buy-window boundaries and the sell marked |
| **Quick read** cards | Last settled close, ATH, drawdown, EWMA vol, days since halving, buy-window status, next sell date |
| **Current condition** | Daily / weekly / monthly RSI, position vs moving averages, ATR%, realised vol, drawdown, trend phase |
| **Prediction** | Where price sits against two independent forward ranges — volatility bands and the cycle-amplitude decay model |
| **Halvings & historical cycles** | Per-cycle high and low, and how many days after the halving each printed |
| **Strategy backtest** | Per-cycle capital, average buy price, units, exit and realised return |

Two design choices are worth calling out:

**The page recomputes on daily closes, not on wall-clock time.** A daily-close
series only changes once a day, so the browser polls a cheap `/api/tick` every
30s and only refetches the 250 KB `/api/snapshot` when a bar has actually rolled
over on the exchange. A full snapshot refresh costs roughly 100× more than a tick.

**Numbers are never silently wrong.** If a fetch fails the engine falls back to
whatever is in `data/`, and the UI always shows the settled close date so a stale
page is visibly stale. Only completed bars are ever stored — a forming bar is
judged by its own close time, never by its open time.

---

## The strategy

Fixed rules, chosen in advance:

1. **Buy** 1/52 of the portfolio on **every Monday** from `halving + 718 days` to
   `halving + 1082 days` — 26 weeks either side of the day-900 pivot.
2. **Sell** the entire position at `next_halving + 450 days`.
3. Exit proceeds become the next cycle's capital.

Every trade fills at that day's daily close. **Fees, slippage and taxes are all
set to zero.**

### Backtested result — compounding

| Cycle | Halving | Capital in | Avg buy | Exit | Exit px | Cash out | Return |
| --- | --- | ---: | ---: | --- | ---: | ---: | ---: |
| 1 | 2012-11-28 | $5,200 | $267 | 2017-10-02 | $4,380 | $87,487 | +1582% |
| 2 | 2016-07-09 | $87,487 | $5,739 | 2021-08-04 | $39,723 | $669,448 | +665% |
| 3 | 2020-05-11 | $669,448 | $22,625 | 2025-07-14 | $119,841 | $3,693,296 | +452% |
| 4 | 2024-04-20 | $3,693,296 | $72,043 | open | — | — | 25/52 buys placed |

**$5,200 → $3,693,296 over three closed cycles.**

### Backtested result — fixed $100 notional

The same buy/sell rules with a flat $100 per Monday and idle cash carried forward:
$5,200 → $145,565, plus an open cycle-4 position. Growth comes from carried cash
rather than from a scaling notional.

**Read these as a description of what happened three times, not as an expected
return.** Three closed cycles is not a sample. The exit rule was fixed in advance
rather than selected from alternatives, and zero fees flatters every result. See
[Limitations](#limitations).

---

## Repository layout

```
btc-cycle-dca/
├── Makefile              # pipeline runner — `make help`
├── requirements.txt      # numpy, matplotlib (everything else is stdlib)
├── engine.py             # live data, indicators, prediction ranges, snapshot cache
├── server.py             # stdlib ThreadingHTTPServer + JSON API
├── pipeline/             # 13 data & analysis scripts, numbered by dependency
│   ├── fetch_halvings.py              # blockstream.info  → halving dates
│   ├── fetch_btc_close.py             # blockchain.info  → 2010→ deep history
│   ├── fetch_btc_daily.py             # Binance 1d       → spot candles
│   ├── fetch_btc_mtf.py               # Binance 1d/1w/1M → MTF candles
│   ├── build_merged.py                # merge + halving-relative annotations
│   ├── analyze_halvings.py            # peak/trough timing per cycle
│   ├── cycle_high_low.py              # per-cycle high/low table
│   ├── backtest_halving_dca.py        # fixed-notional backtest
│   ├── backtest_halving_dca_compound.py # compounding backtest
│   ├── plot_halving_dca.py            # charts/halving_dca.png
│   ├── analyze_mtf.py                 # MTF state + vol bands + analogs (report)
│   └── forecast_next_cycle.py         # amplitude decay + bootstrap (report)
├── web/                 # index.html, app.js, style.css — no framework, no CDN
├── tests/               # node harnesses (tests/test_render.js, test_e2e.js)
├── data/                # generated — gitignored
└── charts/              # generated — gitignored
```

The dashboard entry points (`server.py`, `engine.py`) sit at the root because they
are the app. Everything one-shot lives in `pipeline/`.

`data/` and `charts/` are build output, not source. They are regenerated on every
`make serve`, so a clone is always current and a fork never diverges on a stale
CSV. The only tracked state is code, `Makefile`, and the docs.

### HTTP API

| Endpoint | Returns |
| --- | --- |
| `GET /` | the dashboard (assets re-versioned by content hash) |
| `GET /api/snapshot` | full computation: MTF states, prediction, history (`?force=1` recomputes) |
| `GET /api/tick` | ~1 KB status: held vs exchange bar dates, `changed`, next close countdown |
| `GET /api/ping` | liveness |

---

## Pipeline

`make refresh` runs the stages in dependency order. Each writes a CSV and each
reads the ones before it. The first four need the network; everything after them
is offline and is also what `make report` runs.

```
fetch_halvings ─┐
fetch_btc_close ─┼→ build_merged ─┬→ analyze_halvings    → halving_cycles.csv
fetch_btc_daily ─┤                ├→ cycle_high_low     → cycle_high_low.csv
                 │                ├→ backtest_…dca      → halving_dca_backtest.csv
fetch_btc_mtf   ─┘                └→ backtest_…compound → halving_dca_compound.csv
                                                │
                                                └→ plot_halving_dca → charts/halving_dca.png
```

`analyze_mtf.py` and `forecast_next_cycle.py` print reports and write nothing.

### `data/` contents (generated, not tracked)

| File | Rows | Source |
| --- | ---: | --- |
| `bitcoin_halvings.csv` | 5 | blockstream.info block heights 210k–1.05M |
| `btc_usd_close_1d.csv` | 6,482 | blockchain.info daily index |
| `btc_usdt_1d.csv` | 3,334 | Binance BTC/USDT spot |
| `binance_btcusdt_{1d,1w,1M}.csv` | 3,334 / 476 / 110 | Binance spot, all timeframes |
| `btc_daily_merged.csv` | 5,890 | Binance preferred, index for pre-2017-08-17 |
| `halving_cycles.csv`, `cycle_high_low.csv` | 12 / 4 | derived |
| `halving_dca_backtest.csv`, `halving_dca_compound.csv` | 4 / 4 | derived |

`build_merged.py` prefers Binance wherever it exists and falls back to the
blockchain.info index before the 2017-08-17 spot listing, annotating every row
with days since the last halving. Pre-listing rows are index prices, not a single
exchange, and are labelled as such in the `note` column.

---

## Methodology

**Volatility bands.** RiskMetrics-style EWMA of daily log returns (λ = 0.94),
annualised, projected forward over 90/180/365 days at the 80/90/95 percentiles.
**Drift is deliberately set to zero** — a drift assumption would dominate the
answer, and none of these methods can say *when* anything happens.

**Cycle-amplitude decay.** `log10` of each cycle's peak, with increments
regressed under geometric decay. The mean observed increment ratio is clipped to
[0.35, 0.75] and used to project the next peak. The dashboard shows the range
spanned by the decaying and flat-increment models.

**Historical analogs.** The nearest historical days to today's standardised
feature vector (distance vs MA200, 365-day drawdown, 60-day return, vol20/vol90
ratio), with a 120-day minimum separation so 60 days of one bear episode are not
counted as 60 independent samples. Then: what actually happened over the
following 365 days from each of them.

**Stationary bootstrap.** 4,000 resampled paths of daily log returns with 30-day
blocks, which assumes no halving structure at all — a useful sanity check on the
other two.

---

## Limitations

Stated plainly, because they bound every number above:

- **Three completed cycles.** Bitcoin has had four halvings. This is a record, not a pattern.
- **Zero fees, slippage and taxes** in every backtest.
- **Pre-2017 prices are a multi-exchange index**, not one exchange's book.
- **The exit rule was fixed in advance**, not chosen by testing alternatives against each other.
- **The 5th halving (block 1,050,000) has not been mined.** Its date is projected from the observed block rate and is flagged `is_estimate` everywhere it appears.
- **The dashboard shows completed daily closes**, not a live tick. It is right by construction at the daily close and explicitly stale in between.
- **Ranges are scenarios, not predictions.** They bound a planning band, not a target.

---

## Data sources

All public, keyless, no registration:

- **Binance** `api.binance.com/api/v3/klines` — BTC/USDT spot, 1d / 1w / 1M
- **blockchain.info** charts — long-tail daily index price
- **blockstream.info** API — canonical block timestamps at halving heights

Respect the rate limits; the fetchers paginate at 1000 bars per request and sleep
between pages.

---

## Testing

Two Node harnesses, no npm dependencies — they stub a DOM and drive `web/app.js`
directly through `node:vm`.

```bash
make serve &      # test-e2e needs a live server
make test
```
`test_render.js` renders a captured snapshot and checks card values, SVG geometry
(text inside the canvas, no degenerate bars, no overlapping labels) and the
accessible axis table. `test_e2e.js` adds endpoint contracts, day-gating
behaviour, error-path messaging, and CSS guards — it resolves the responsive
cascade at 320–1440px and fails if any element wider than a phone escapes its
scroll container.

---

## Configuration

| Setting | Where | Default |
| --- | --- | --- |
| Server port | `BTC_DASH_PORT` env var, or `PORT=` on `make serve` | `7070` |
| Bind address | `BTC_DASH_BIND` env var, or `BIND=` on `make serve` | `0.0.0.0` (LAN). Use `127.0.0.1` to keep it local |
| Data freshness | `BTC_DASH_MAX_STALENESS_DAYS` | `0` (always current) |
| Skip freshness check | `BTC_DASH_SKIP_SYNC=1` | off |
| Candle TTL | `engine.py` → `candles(ttl=)` | `3600` s, invalidated on rollover |
| Poll interval | dashboard header dropdown | 30 s |
| Buy window | `engine.py` → `buy_start, buy_end, sell` | 718 / 1082 / 450 days |

> `BIND = "0.0.0.0"` serves your whole LAN with no authentication. Set it to
> `127.0.0.1` unless you intend that.

---

## Disclaimer

Educational analysis of public market data. **Not investment advice.** Nothing
here predicts the price of Bitcoin or anything else.

## License

**No license file is committed yet.** Until one is added, the repository carries
no license grant and is not open source by default. Pick a license (MIT is the
usual choice for a project like this) and add `LICENSE` before publishing.