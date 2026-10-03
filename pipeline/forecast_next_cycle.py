#!/usr/bin/env python3
"""Estimate a price RANGE for the next halving cycle's peak and the following bottom.

Method (three independent estimators, deliberately kept separate):

 1. Amplitude decay model  - log10 of the cycle peak level, regressed on cycle
    number with a geometrically decaying increment. Fitted on the observed peaks.
 2. Historical bear drawdown distribution - every halving-cycle top-to-bottom
    decline in the sample, plus the largest drawdowns available, giving an
    empirical distribution of peak->bottom declines.
 3. Bootstrap path simulation - stationary bootstrap of daily log returns from
    BTC, simulating price paths forward from the last close. This supplies a
    range that does NOT assume any halving structure at all, which makes it a
    useful sanity check on 1 and 2.

Output: printed report only (no CSV; these are forward-looking estimates).
"""

import csv
import datetime as dt
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")


def read(path: str) -> list[dict]:
    with open(path, newline="") as fh:
        return list(csv.DictReader(fh))


def pct(x: float) -> str:
    return f"{x * 100:,.0f}%"


def main() -> int:
    series = read(os.path.join(DATA, "btc_daily_merged.csv"))
    dates = [dt.date.fromisoformat(r["date"]) for r in series]
    close = np.array([float(r["close_usd"]) for r in series])
    ret = np.diff(np.log(close))

    halvings = [dt.date.fromisoformat(r["date"]) for r in read(os.path.join(DATA, "bitcoin_halvings.csv")) if r["is_estimate"] == "no"]
    cycles = read(os.path.join(DATA, "halving_dca_compound.csv"))

    print("=" * 78)
    print("1. OBSERVED CYCLES")
    print("=" * 78)
    peaks, troughs = [], []
    for i, c in enumerate(cycles):
        h = dt.date.fromisoformat(c["buy_halving"])
        nxt = halvings[i + 1] if i + 1 < len(halvings) else None
        end = min(nxt, dates[-1]) if nxt else dates[-1]
        m = (np.array([h <= d < end for d in dates]))
        seg_hi, seg_lo = close[m].max(), close[m].min()
        hi_d, lo_d = dates[int(np.argmax(np.where(m, close, -np.inf)))], dates[int(np.argmin(np.where(m, close, np.inf)))]
        peaks.append((int(c["cycle"]), seg_hi, hi_d))
        troughs.append((int(c["cycle"]), seg_lo, lo_d))
        print(f"  cycle {c['cycle']}: avg ${float(c['avg_buy_price']):>10,.0f} | cycle high ${seg_hi:>10,.0f} {hi_d} "
              f"| cycle low ${seg_lo:>9,.2f} {lo_d}")

    last_close = close[-1]
    ath = close.max()
    ath_d = dates[int(np.argmax(close))]
    print(f"\n  last close ${last_close:,.2f} ({dates[-1]})   all-time high ${ath:,.0f} ({ath_d})   "
          f"drawdown from ATH {pct(last_close / ath - 1)}")

    print("\n" + "=" * 78)
    print("2. AMPLITUDE DECAY MODEL  (log10 of cycle peak)")
    print("=" * 78)
    lp = np.log10([p[1] for p in peaks])
    inc = np.diff(lp)
    print(f"  log10 peaks:  {[f'{v:.3f}' for v in lp]}")
    print(f"  increments:   {[f'{v:.3f}' for v in inc]}")
    if len(inc) >= 2:
        ratios = inc[1:] / inc[:-1]
        print(f"  increment decay ratios: {[f'{v:.2f}' for v in ratios]}  (mean {ratios.mean():.2f})")
        r = float(np.clip(ratios.mean(), 0.35, 0.75))
        next_inc = inc[-1] * r
        decay_peak = 10 ** (lp[-1] + next_inc)
        flat_peak = 10 ** (lp[-1] + inc[-1])
        print(f"\n  decaying model (r={r:.2f}): next peak ~ ${decay_peak:,.0f}")
        print(f"  flat-increment model:      next peak ~ ${flat_peak:,.0f}")
        peak_lo, peak_hi = sorted([decay_peak, flat_peak])
        print(f"  => peak range ${peak_lo:,.0f} - ${peak_hi:,.0f}")

    print("\n" + "=" * 78)
    print("3. BEAR DRAWDOWN DISTRIBUTION (peak -> subsequent bottom)")
    print("=" * 78)
    dd = []
    for (_, hi, _), (_, lo, _) in zip(peaks, troughs):
        if lo < hi:
            dd.append(lo / hi - 1)
    print(f"  within-cycle peak->low: {[f'{v*100:,.0f}%' for v in dd]}  (median {np.median(dd)*100:,.0f}%)")

    running_max = np.maximum.accumulate(close)
    mdd = close / running_max - 1
    big = [mdd[i] for i in range(1, len(mdd)) if dates[i] > dates[-1] - dt.timedelta(days=365 * 4)]
    print(f"  worst 4y max-drawdowns:  {[f'{v*100:,.0f}%' for v in sorted(big)[:5]]}")

    for lo_m in (0.10, 0.15, 0.20, 0.25):
        print(f"    if next bear is -{1-lo_m:.0%}:  bottom = peak x {lo_m:.2f}")

    print("\n" + "=" * 78)
    print("4. BOOTSTRAP PATH SIMULATION (stationary bootstrap of daily log returns)")
    print("=" * 78)
    horizon = 900  # ~ one halving cycle
    n_paths = 4000
    sample = ret[-1440:]  # last ~4 years of daily returns
    block = 30
    rng = np.random.default_rng(7)
    starts = rng.integers(0, len(sample) - block, size=(n_paths, horizon // block + 2))
    offsets = rng.integers(0, block, size=(n_paths, horizon // block + 2))
    idx = (starts[:, :, None] + offsets[:, None, :]).reshape(n_paths, -1)[:, :horizon]
    paths = last_close * np.exp(sample[idx].cumsum(axis=1))

    hi = paths.max(axis=1)
    hi_i = paths.argmax(axis=1)
    post = np.where(np.arange(horizon)[None, :] > hi_i[:, None], paths, np.inf)
    lo_after = post.min(axis=1)
    lo_all = paths.min(axis=1)

    print(f"  {n_paths:,} paths x {horizon} days from ${last_close:,.0f}")
    print("  upside extreme over the horizon (any day):")
    for q in (50, 75, 90, 95):
        print(f"     {q:>2}th pct: ${np.percentile(hi, q):>12,.0f}")
    print("  worst trough over the horizon (any day):")
    for q in (50, 25, 10, 5):
        print(f"     {q:>2}th pct: ${np.percentile(lo_all, q):>12,.0f}")
    print("  low AFTER the path's own high (the 'bottom after the next peak'):")
    for q in (50, 25, 10, 5):
        print(f"     {q:>2}th pct: ${np.percentile(lo_after, q):>12,.0f}")
    ann_vol = ret.std() * np.sqrt(365)
    print(f"\n  annualised log vol (full sample): {ann_vol:.1%}   (last 4y: {sample.std()*np.sqrt(365):.1%})")
    return 0


if __name__ == "__main__":
    sys.exit(main())