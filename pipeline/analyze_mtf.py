#!/usr/bin/env python3
"""Multi-timeframe (daily/weekly/monthly) state read on Binance BTC/USDT, plus a
technical-state-conditional forecast of the next top and bottom.

Three parts:

 1. STATE  - per timeframe: position vs moving averages, RSI(14), realised and
    ATR volatility, drawdown from the timeframe high, and a phase label.

 2. VOL BANDS - a no-drift random-walk projection from the last close using an
    EWMA volatility estimate. Drift is deliberately set to zero because a drift
    assumption, not the volatility estimate, would dominate the answer.

 3. ANALOGS - the nearest historical days to today's multi-timeframe state
    (standardised feature vector), and what actually happened over the following
    365 days from each of them. This conditions on market structure instead of
    on the halving calendar, and is the main evidence for the ranges.

Output: printed report.
"""

import csv
import datetime as dt
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
HORIZON = 365


def load(tf: str) -> list[dict]:
    path = os.path.join(DATA, f"binance_btcusdt_{tf}.csv")
    with open(path, newline="") as fh:
        return list(csv.DictReader(fh))


def sma(x: np.ndarray, n: int) -> float:
    return float(x[-n:].mean()) if len(x) >= n else float("nan")


def rsi(close: np.ndarray, n: int = 14) -> float:
    if len(close) < n + 1:
        return float("nan")
    d = np.diff(close[-(n + 1):])
    up, dn = d[d > 0].sum() / n, -d[d < 0].sum() / n
    if dn == 0:
        return 100.0
    rs = up / dn
    return 100 - 100 / (1 + rs)


def atr(high: np.ndarray, low: np.ndarray, close: np.ndarray, n: int = 14) -> float:
    tr = np.maximum(high[-n:] - low[-n:], np.maximum(np.abs(high[-n:] - close[-n - 1:-1]), np.abs(low[-n:] - close[-n - 1:-1])))
    return float(tr.mean())


def state_table(tf: str, mas: tuple[int, ...]) -> dict:
    rows = load(tf)
    close = np.array([float(r["close"]) for r in rows])
    high = np.array([float(r["high"]) for r in rows])
    low = np.array([float(r["low"]) for r in rows])
    last = close[-1]
    out = {
        "tf": tf, "bars": len(rows), "last_date": rows[-1]["date"], "last": last,
        "high": high.max(), "low": low.min(),
        "rsi": rsi(close), "atr_pct": atr(high, low, close) / last,
        "dd": last / high.max() - 1,
    }
    for n in mas:
        m = sma(close, n)
        out[f"ma{n}"] = m
        out[f"vs_ma{n}"] = last / m - 1 if m == m else float("nan")
    logret = np.diff(np.log(close))
    per_year = {"1d": 365, "1w": 52, "1M": 12}[tf]
    out["vol20"] = float(logret[-20:].std() * np.sqrt(per_year)) if len(logret) > 20 else float("nan")
    out["vol90"] = float(logret[-90:].std() * np.sqrt(per_year)) if len(logret) > 90 else float("nan")
    return out


def phase(s: dict) -> str:
    r, v1 = s["rsi"], s["vs_ma200"] if "vs_ma200" in s else s.get("vs_ma50", 0)
    if v1 > 0.15 and r > 50:
        return "UPTREND"
    if v1 > 0 and r <= 50:
        return "UPTREND / momentum cooling"
    if v1 < -0.15 and r < 50:
        return "DOWNTREND"
    if v1 < 0 and r > 50:
        return "RECOVERY / basing"
    return "RANGE"


def ewma_vol(logret: np.ndarray, lam: float = 0.94) -> float:
    """RiskMetrics-style EWMA: iterate FORWARD in time so the newest return
    carries weight (1 - lam) relative to the accumulated variance."""
    window = logret[-250:]
    var = float(window[0] ** 2)
    for r in window[1:]:
        var = lam * var + (1 - lam) * r * r
    return float(np.sqrt(var * 365))


def vol_bands(last: float, sigma: float, days: int) -> dict:
    s = sigma * np.sqrt(days / 365)  # sigma is ANNUALISED; scale to the horizon
    z = {50: 0.674, 80: 0.842, 90: 1.282, 95: 1.645}
    out = {}
    for p, zz in z.items():
        out[f"p{p}"] = (last * np.exp(-zz * s), last * np.exp(+zz * s))
    return out


def main() -> int:
    states = [state_table("1d", (20, 50, 200)), state_table("1w", (10, 20, 40)), state_table("1M", (6, 12))]

    print("=" * 88)
    print("1. MULTI-TIMEFRAME STATE (Binance BTC/USDT spot, completed bars only)")
    print("=" * 88)
    for s in states:
        mas = [k for k in s if k.startswith("vs_ma")]
        print(f"\n  {s['tf']:>3}  last close ${s['last']:>11,.2f} ({s['last_date']}, {s['bars']} bars)")
        print(f"       range ${s['low']:,.2f} - ${s['high']:,.2f}   drawdown from high {s['dd']*100:,.1f}%   phase: {phase(s)}")
        print("       " + "   ".join(f"{k[3:]} {s[k]*100:+,.1f}%" for k in sorted(mas)))
        print(f"       RSI(14) {s['rsi']:,.1f}   ATR% {s['atr_pct']*100:,.2f}   "
              f"vol20 {s['vol20']*100:,.0f}%  vol90 {s['vol90']*100:,.0f}%")

    daily = load("1d")
    close = np.array([float(r["close"]) for r in daily])
    dates = [dt.date.fromisoformat(r["date"]) for r in daily]
    logret = np.diff(np.log(close))
    sigma = ewma_vol(logret)
    last = close[-1]
    print(f"\n  EWMA daily vol (lambda 0.94): {sigma*100:,.1f}% annualised")

    print("\n" + "=" * 88)
    print("2. NO-DRIFT RANDOM-WALK BANDS FROM THE LAST CLOSE")
    print("=" * 88)
    print(f"  {'horizon':>10}  {'sigma_H':>8}  {'5% low':>13} {'20% low':>13} {'50% low':>13}   "
          f"{'50% high':>13} {'80% high':>13} {'95% high':>13}")
    for days in (90, 180, HORIZON):
        b = vol_bands(last, sigma, days)
        sH = sigma * np.sqrt(days / 365)
        g = lambda v: f"${v:>12,.0f}"
        print(f"  {days:>7}d  {sH*100:>7.0f}%  {g(b['p95'][0])} {g(b['p90'][0])} {g(b['p80'][0])}   "
              f"{g(b['p80'][1])} {g(b['p90'][1])} {g(b['p95'][1])}")

    print("\n" + "=" * 88)
    print("3. ANALOGS: nearest historical days to today's technical state")
    print("=" * 88)
    feats = []
    c100 = np.concatenate([np.full(200, close[0]), close])
    for i in range(200, len(close)):
        px = c100[i]
        ma200 = c100[i - 200:i].mean()
        dd365 = px / c100[max(0, i - 365):i + 1].max() - 1
        r60 = np.log(px / c100[i - 60]) if i >= 60 else 0.0
        v20 = np.diff(np.log(c100[i - 20:i])).std()
        v90 = np.diff(np.log(c100[i - 90:i])).std()
        vr = v20 / v90 if v90 > 0 else 1.0
        feats.append([px / ma200 - 1, dd365, r60, vr])
    feats = np.array(feats)
    cur = feats[-1]
    scale = feats.std(axis=0)
    z = np.abs((feats[:-1] - cur) / scale).sum(axis=1)
    # de-duplicate: analogs from one bear episode are not 60 independent samples,
    # so keep only those at least MIN_SEP days apart
    MIN_SEP = 120
    ranked = np.argsort(z)
    picked = []
    for i in ranked:
        j = i + 200
        if all(abs(dates[j] - dates[q + 200]).days >= MIN_SEP for q in picked):
            picked.append(i)
        if len(picked) >= 40:
            break
    order = np.array(picked)
    k = len(order)
    print(f"  feature vector today: ma200 {cur[0]*100:+.1f}%  dd365 {cur[1]*100:+.1f}%  "
          f"r60 {cur[2]*100:+.1f}%  vol20/vol90 {cur[3]:.2f}")
    print(f"  {k} nearest independent episodes, >= {MIN_SEP} days apart "
          f"({len(feats)-200} candidate days on Binance history)\n")

    hi12, lo12, fut_hi, fut_lo = [], [], [], []
    for i in order:
        j = i + 200
        if j + HORIZON >= len(close):
            continue
        base = close[j]
        path = close[j:j + HORIZON]
        hi12.append(path.max() / base - 1)
        lo12.append(path.min() / base - 1)
        fut_hi.append(path.max())
        fut_lo.append(path.min())
    hi12, lo12 = np.array(hi12), np.array(lo12)
    fut_hi, fut_lo = np.array(fut_hi), np.array(fut_lo)
    print(f"  forward 365d from those days, as a return from the day's close:")
    for q in (10, 25, 50, 75, 90):
        print(f"     {q:>2}th pct:  high {np.percentile(hi12, q)*100:+,.0f}%   low {np.percentile(lo12, q)*100:+,.0f}%")
    print(f"\n  same, as absolute price levels if today's ${last:,.0f} repeats the analog's level:")
    rel_hi = np.array([p / c for p, c in zip(fut_hi, [close[i + 200] for i in order])])
    rel_lo = np.array([p / c for p, c in zip(fut_lo, [close[i + 200] for i in order])])
    print(f"     high  10/50/90 pct: ${last*np.percentile(rel_hi,10):,.0f} / "
          f"${last*np.percentile(rel_hi,50):,.0f} / ${last*np.percentile(rel_hi,90):,.0f}")
    print(f"     low   10/50/90 pct: ${last*np.percentile(rel_lo,10):,.0f} / "
          f"${last*np.percentile(rel_lo,50):,.0f} / ${last*np.percentile(rel_lo,90):,.0f}")
    med_i = order[int(len(order) * 0.25)]
    print(f"\n  example analogs (date, forward 12m high/low):")
    for i in list(order[:5]):
        j = i + 200
        if j + HORIZON < len(close):
            p = close[j:j + HORIZON]
            print(f"     {dates[j]}  close ${close[j]:>10,.0f} -> high ${p.max():>10,.0f}  low ${p.min():>9,.0f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())