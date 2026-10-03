"""Live BTC dashboard engine: MTF state, prediction ranges, historical tables."""

from __future__ import annotations

import csv
import datetime as dt
import json
import os
import threading
import time
import urllib.request

import numpy as np

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(ROOT, "data")
BINANCE = "https://api.binance.com/api/v3/klines"

TF_MS = {"1d": 86_400_000, "1w": 604_800_000, "1M": 2_629_746_000}
PER_YEAR = {"1d": 365, "1w": 52, "1M": 12}
TF_MAS = {"1d": (20, 50, 200), "1w": (10, 20, 40), "1M": (6, 12)}

_lock = threading.Lock()
_cache: dict = {}


def _get(url: str, retries: int = 3) -> list:
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "btc-dash/1.0"})
            with urllib.request.urlopen(req, timeout=20) as resp:
                return json.load(resp)
        except Exception as exc:  # noqa: BLE001
            last = exc
            time.sleep(1.0 * (attempt + 1))
    raise RuntimeError(str(last))


TFS = ("1d", "1w", "1M")
GRACE_SECONDS = 60  # wait this long after a bar boundary before trusting the exchange


def candles(tf: str, ttl: int = 3600) -> list[dict]:
    """Live Binance klines for a timeframe.

    TTL is long by design: the series only changes when a bar closes, and a
    rollover is detected by probe_bars(), which invalidates this cache
    explicitly. See snapshot() for the day-gated recomputation.
    """
    now = time.time()
    with _lock:
        hit = _cache.get(("candles", tf))
        if hit and now - hit[0] < ttl:
            return hit[1]

    rows: list[dict] = []
    try:
        start, now_ms = 1_490_000_000_000, int(time.time() * 1000)
        seen: set[int] = set()
        while True:
            batch = _get(f"{BINANCE}?symbol=BTCUSDT&interval={tf}&startTime={start}&limit=1000")
            if not batch:
                break
            for k in batch:
                if k[0] in seen or k[6] >= now_ms:
                    continue
                seen.add(k[0])
                rows.append(
                    {
                        "t": k[0],
                        "d": time.strftime("%Y-%m" if tf == "1M" else "%Y-%m-%d", time.gmtime(k[0] / 1000)),
                        "o": float(k[1]), "h": float(k[2]), "l": float(k[3]), "c": float(k[4]),
                        "v": float(k[5]),
                    }
                )
            start = batch[-1][0] + TF_MS[tf]
            if len(batch) < 1000:
                break
            time.sleep(0.25)
        rows.sort(key=lambda r: r["t"])
        if len(rows) < 50:
            raise RuntimeError("too few bars")
    except Exception:  # noqa: BLE001
        path = os.path.join(DATA, f"binance_btcusdt_{tf}.csv")
        with open(path, newline="") as fh:
            rows = [
                {"t": 0, "d": r["date"], "o": float(r["open"]), "h": float(r["high"]),
                 "l": float(r["low"]), "c": float(r["close"]), "v": float(r["volume"])}
                for r in csv.DictReader(fh)
            ]
        rows = _with_ts(rows)

    rows = _with_ts(rows)
    with _lock:
        _cache[("candles", tf)] = (now, rows)
    return rows


def _with_ts(rows: list[dict]) -> list[dict]:
    out = []
    for r in rows:
        if r["t"]:
            out.append(r)
        else:
            d = dt.datetime.strptime(r["d"] + ("-01" if len(r["d"]) == 7 else ""), "%Y-%m-%d" if len(r["d"]) > 7 else "%Y-%m-%d")
            out.append({**r, "t": int(d.replace(tzinfo=dt.UTC).timestamp()) * 1000})
    out.sort(key=lambda r: r["t"])
    return out


def rsi(close: np.ndarray, n: int = 14) -> float:
    if len(close) < n + 1:
        return float("nan")
    d = np.diff(close[-(n + 1):])
    up, dn = d[d > 0].sum() / n, -d[d < 0].sum() / n
    if dn == 0:
        return 100.0
    return 100 - 100 / (1 + up / dn)


def atr(high: np.ndarray, low: np.ndarray, close: np.ndarray, n: int = 14) -> float:
    tr = np.maximum(high[-n:] - low[-n:], np.maximum(np.abs(high[-n:] - close[-n - 1:-1]), np.abs(low[-n:] - close[-n - 1:-1])))
    return float(tr.mean())


def ewma_vol(logret: np.ndarray, lam: float = 0.94) -> float:
    w = logret[-250:]
    var = float(w[0] ** 2)
    for r in w[1:]:
        var = lam * var + (1 - lam) * r * r
    return float(np.sqrt(var * 365))


def tf_state(tf: str) -> dict:
    rows = candles(tf)
    close = np.array([r["c"] for r in rows])
    high = np.array([r["h"] for r in rows])
    low = np.array([r["l"] for r in rows])
    logret = np.diff(np.log(close))
    last = float(close[-1])
    st = {
        "tf": tf, "bars": len(rows), "last_date": rows[-1]["d"], "last": round(last, 2),
        "high": round(float(high.max()), 2), "low": round(float(low.min()), 2),
        "rsi": round(float(rsi(close)), 1),
        "atr_pct": round(float(atr(high, low, close) / last) * 100, 2),
        "vol20": round(float(logret[-20:].std() * np.sqrt(PER_YEAR[tf])) * 100, 1) if len(logret) > 20 else None,
        "vol90": round(float(logret[-90:].std() * np.sqrt(PER_YEAR[tf])) * 100, 1) if len(logret) > 90 else None,
        "dd": round((last / high.max() - 1) * 100, 1),
        "mas": {},
    }
    for n in TF_MAS[tf]:
        if len(close) >= n:
            m = float(close[-n:].mean())
            st["mas"][str(n)] = {"ma": round(m, 2), "vs": round((last / m - 1) * 100, 1)}
    st["phase"] = phase(st)
    return st


def phase(s: dict) -> str:
    ref = s["mas"].get("200") or s["mas"].get("40") or s["mas"].get("12")
    v = ref["vs"] if ref else 0.0
    r = s["rsi"]
    if v > 15 and r > 50:
        return "UPTREND"
    if v > 0 and r <= 50:
        return "UPTREND / momentum cooling"
    if v < -15 and r < 50:
        return "DOWNTREND"
    if v < 0 and r > 50:
        return "RECOVERY / basing"
    return "RANGE"


def vol_bands(last: float, sigma: float, days: int) -> dict:
    s = sigma * np.sqrt(days / 365)
    z = {80: 0.842, 90: 1.282, 95: 1.645}
    out = {"horizon": days, "sigma_pct": round(s * 100, 1), "lows": {}, "highs": {}}
    for p, zz in z.items():
        out["lows"][str(p)] = round(last * np.exp(-zz * s))
        out["highs"][str(p)] = round(last * np.exp(+zz * s))
    return out


def analogs(close: np.ndarray, dates: list[dt.date], k: int = 40, min_sep: int = 120) -> dict:
    feats, idx = [], []
    for i in range(200, len(close)):
        px = close[i]
        ma200 = close[i - 200:i].mean()
        dd365 = px / close[max(0, i - 365):i + 1].max() - 1
        r60 = np.log(px / close[i - 60]) if i >= 60 else 0.0
        v20 = np.diff(np.log(close[i - 20:i])).std()
        v90 = np.diff(np.log(close[i - 90:i])).std()
        feats.append([px / ma200 - 1, dd365, r60, v20 / v90 if v90 > 0 else 1.0])
        idx.append(i)
    feats = np.array(feats)
    cur = feats[-1]
    scale = feats.std(axis=0)
    z = np.abs((feats[:-1] - cur) / scale).sum(axis=1)
    picked = []
    for j in np.argsort(z):
        if all(abs(dates[idx[j]] - dates[idx[q]]).days >= min_sep for q in picked):
            picked.append(j)
        if len(picked) >= k:
            break

    fwd_hi, fwd_lo, rows = [], [], []
    H = 365
    for j in picked:
        i = idx[j]
        if i + H >= len(close):
            continue
        path = close[i:i + H]
        base = close[i]
        fwd_hi.append(path.max() / base - 1)
        fwd_lo.append(path.min() / base - 1)
        rows.append({"date": str(dates[i]), "close": round(float(base)),
                     "high12m": round(float(path.max())), "low12m": round(float(path.min()))})
    if not fwd_hi:
        return {}
    fhi, flo = np.array(fwd_hi), np.array(fwd_lo)
    q = lambda a, p: round(float(np.percentile(a, p)), 4)  # noqa: E731
    return {
        "episodes": len(fwd_hi),
        "high_pct": {str(p): q(fhi, p) for p in (10, 25, 50, 75, 90)},
        "low_pct": {str(p): q(flo, p) for p in (10, 25, 50, 75, 90)},
        "sample": rows[:8],
    }


def cached_analogs(close: np.ndarray, dates: list[dt.date], ttl: int = 300) -> dict:
    now = time.time()
    with _lock:
        hit = _cache.get("analogs")
        if hit and now - hit[0] < ttl:
            return hit[1]
    res = analogs(close, dates)
    with _lock:
        _cache["analogs"] = (now, res)
    return res


def halvings() -> list[dict]:
    path = os.path.join(DATA, "bitcoin_halvings.csv")
    with open(path, newline="") as fh:
        return list(csv.DictReader(fh))


def csv_rows(name: str) -> list[dict]:
    path = os.path.join(DATA, name)
    if not os.path.exists(path):
        return []
    with open(path, newline="") as fh:
        return list(csv.DictReader(fh))


def prediction() -> dict:
    daily = candles("1d")
    close = np.array([r["c"] for r in daily])
    dates = [dt.date.fromtimestamp(r["t"] / 1000) for r in daily]
    last = float(close[-1])
    sigma = ewma_vol(np.diff(np.log(close)))

    hs = halvings()
    real = [dt.date.fromisoformat(h["date"]) for h in hs if h["is_estimate"] == "no"]
    cur_h = max(h for h in real if h <= dates[-1])
    next_h = dt.date.fromisoformat(hs[-1]["date"]) if hs[-1]["is_estimate"] != "no" else None
    day = (dates[-1] - cur_h).days

    buy_start, buy_end, sell = 718, 1082, 450
    today = dates[-1]
    win_start = cur_h + dt.timedelta(days=buy_start)
    win_end = cur_h + dt.timedelta(days=buy_end)
    buy_mondays = []
    x = win_start
    while x <= win_end:
        if x.weekday() == 0:
            buy_mondays.append(x)
        x += dt.timedelta(days=1)
    have = set(dates)
    buys_placed = sum(1 for d in buy_mondays if d in have and d <= today)
    if today < win_start:
        buy_status = "upcoming"
    elif today <= win_end:
        buy_status = "active"
    else:
        buy_status = "done"

    next_buy = None
    if next_h:
        cand = next_h + dt.timedelta(days=buy_start)
        next_buy = cand + dt.timedelta(days=(7 - cand.weekday()) % 7)
    if next_h:
        sell_date = next_h + dt.timedelta(days=sell)
        sell_status = "reached" if sell_date <= today else "scheduled"
    else:
        sell_date, sell_status = None, None

    peaks = []
    for i, a in enumerate(real):
        end = real[i + 1] if i + 1 < len(real) else dates[-1]
        m = np.array([a <= d < end for d in dates])
        if m.any():
            peaks.append(float(close[m].max()))

    amp = {}
    if len(peaks) >= 3:
        lp = np.log10(peaks)
        inc = np.diff(lp)
        ratios = inc[1:] / inc[:-1]
        r = float(np.clip(ratios.mean(), 0.35, 0.75))
        amp = {
            "log10_peaks": [round(v, 3) for v in lp],
            "increments": [round(v, 3) for v in inc],
            "decay": round(r, 2),
            "next_peak": round(10 ** (lp[-1] + inc[-1] * r)),
            "flat_peak": round(10 ** (lp[-1] + inc[-1])),
        }

    bands = [vol_bands(last, sigma, d) for d in (90, 180, 365)]
    ana = cached_analogs(close, dates)
    ath_i = int(np.argmax(close))
    ath = float(close[ath_i])

    bear = [0.85, 0.80, 0.75, 0.70, 0.60]
    return {
        "generated": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "price": round(last, 2),
        "price_date": str(dates[-1]),
        "ath": round(ath, 2),
        "ath_date": str(dates[ath_i]),
        "dd_from_ath_pct": round((last / ath - 1) * 100, 1),
        "ewma_vol_pct": round(sigma * 100, 1),
        "cycle": {
            "halving": str(cur_h),
            "days_since": day,
            "next_halving": str(next_h) if next_h else None,
            "next_halving_is_estimate": bool(next_h and next_h != max(real)),
            "buy_window_days": [buy_start, buy_end],
            "buy_window_start": str(win_start),
            "buy_window_end": str(win_end),
            "buy_status": buy_status,
            "buys_placed": buys_placed,
            "buys_total": len(buy_mondays),
            "first_buy": str(buy_mondays[0]) if buy_mondays else None,
            "last_buy": str(buy_mondays[-1]) if buy_mondays else None,
            "next_buy": str(next_buy) if next_buy else None,
            "sell_date": str(sell_date) if sell_date else None,
            "sell_status": sell_status,
        },
        "bands": bands,
        "amplitude": amp,
        "analogs": ana,
        "bear_scenarios": [{"drawdown_pct": int(b * 100), "price": round(ath * (1 - b))} for b in bear],
    }


def history() -> dict:
    price = csv_rows("btc_daily_merged.csv")
    series = [{"d": r["date"], "c": float(r["close_usd"]), "s": r["source"]} for r in price]
    return {
        "series": series,
        "halvings": halvings(),
        "cycles": csv_rows("cycle_high_low.csv"),
        "strategy": csv_rows("halving_dca_compound.csv"),
        "fixed": csv_rows("halving_dca_backtest.csv"),
    }


def _held() -> dict:
    """Open time of the most recent bar currently held per timeframe."""
    with _lock:
        return {
            tf: (_cache[("candles", tf)][1][-1]["t"] if _cache.get(("candles", tf)) else None)
            for tf in TFS
        }


def _sig(held: dict) -> tuple:
    return tuple(sorted((tf, held.get(tf)) for tf in TFS))


def _dates(held: dict) -> dict:
    return {
        tf: (dt.datetime.fromtimestamp(t / 1000, dt.UTC).strftime("%Y-%m-%d") if t else None)
        for tf, t in held.items()
    }


def probe_bars(ttl: int = 20) -> dict:
    """Fetch only the most recent bar per timeframe. Three tiny requests (~1 KB)
    instead of the ~250 KB a full series pull costs. This is what makes day-gated
    polling cheap: the client can ask 'has anything rolled over?' every 30 s."""
    now = time.time()
    with _lock:
        hit = _cache.get("probe")
        if hit and now - hit[0] < ttl:
            return hit[1]
    out: dict = {}
    now_ms = int(time.time() * 1000)
    for tf in TFS:
        try:
            rows = _get(f"{BINANCE}?symbol=BTCUSDT&interval={tf}&limit=2")
            # compare like with like: the series only stores COMPLETED bars, so the
            # probe must report the newest completed bar, not the in-progress one
            done = [k for k in rows if k[6] < now_ms]
            out[tf] = int(done[-1][0]) if done else None
        except Exception:  # noqa: BLE001
            out[tf] = None
    with _lock:
        _cache["probe"] = (now, out)
    return out


def _boundaries(now: dt.datetime) -> dict:
    midnight = dt.datetime(now.year, now.month, now.day, tzinfo=dt.UTC) + dt.timedelta(days=1)
    daily = midnight + dt.timedelta(seconds=GRACE_SECONDS)
    weekly = midnight
    while weekly.weekday() != 0:
        weekly += dt.timedelta(days=1)
    monthly = dt.datetime(now.year + 1, 1, 1, tzinfo=dt.UTC) if now.month == 12 else dt.datetime(now.year, now.month + 1, 1, tzinfo=dt.UTC)
    return {
        "1d": daily,
        "1w": weekly + dt.timedelta(seconds=GRACE_SECONDS),
        "1M": monthly + dt.timedelta(seconds=GRACE_SECONDS),
    }


def tick() -> dict:
    """Cheap status the browser polls: what data we hold, and when it next changes."""
    now = dt.datetime.now(dt.UTC)
    probe = probe_bars()
    with _lock:
        held = {tf: (_cache.get(("candles", tf))[1][-1]["t"] if _cache.get(("candles", tf)) else None)
                for tf in TFS}
        snap_sig = _cache.get("snapshot_sig")
        snap_date = _cache.get("snapshot_date")

    changed = {tf: bool(probe.get(tf) and held.get(tf) and probe[tf] != held[tf]) for tf in TFS}
    boundary = _boundaries(now)
    data_date = {tf: (dt.datetime.fromtimestamp(held[tf] / 1000, dt.UTC).strftime("%Y-%m-%d") if held.get(tf) else None) for tf in TFS}
    probe_date = {tf: (dt.datetime.fromtimestamp(probe[tf] / 1000, dt.UTC).strftime("%Y-%m-%d") if probe.get(tf) else None) for tf in TFS}
    any_changed = any(changed.values()) or snap_sig is None or snap_date != data_date

    return {
        "now": now.isoformat(timespec="seconds"),
        "data_date": data_date,
        "exchange_date": probe_date,
        "changed": any_changed,
        "stale_tf": [tf for tf, v in changed.items() if v],
        "next_close": {tf: b.isoformat(timespec="seconds") for tf, b in boundary.items()},
        "seconds_to_daily_close": int((boundary["1d"] - now).total_seconds()),
        "daily_date": data_date.get("1d"),
    }


def invalidate() -> None:
    with _lock:
        for key in [k for k in _cache if isinstance(k, tuple) and k[0] == "candles"]:
            _cache.pop(key, None)
        _cache.pop("analogs", None)


def snapshot(force: bool = False) -> dict:
    """Full computation, gated on the data actually changing.

    A daily-close series can only change once per day, so recomputing on every
    poll wastes both CPU and 250 KB of bandwidth. The snapshot is rebuilt only
    when a bar rolled over (detected by probe_bars) or force=True.
    """
    probe = probe_bars()
    held = _held()
    cached = _cache.get("snapshot")
    cached_sig = _cache.get("snapshot_sig")

    rolled = any(probe.get(tf) and held.get(tf) and probe[tf] != held.get(tf) for tf in TFS)
    if not (force or rolled or cached is None or cached_sig != _sig(held)):
        return cached

    if rolled or force:
        invalidate()
    data = {
        "states": [tf_state(tf) for tf in TFS],
        "prediction": prediction(),
        "history": history(),
    }
    fresh = _held()
    with _lock:
        _cache["snapshot"], _cache["snapshot_sig"] = data, _sig(fresh)
        _cache["snapshot_date"] = _dates(fresh)
    return data