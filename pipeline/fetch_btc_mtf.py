#!/usr/bin/env python3
"""Fetch Binance BTC/USDT spot candles across timeframes: daily, weekly, monthly.

Public REST API, no key. Each timeframe is paginated at 1000 bars per request.

--resume continues each timeframe from the newest bar already in its file, which
turns a 100-day drift into one request per timeframe. Closed klines are immutable,
so appending is safe; each file is rewritten whole so a half-finished run can never
leave duplicates behind.

Output: data/binance_btcusdt_1d.csv, data/binance_btcusdt_1w.csv, data/binance_btcusdt_1M.csv
"""

import csv
import datetime as dt
import json
import os
import sys
import time
import urllib.request

SYMBOL = "BTCUSDT"
BASE = "https://api.binance.com/api/v3/klines"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
PAGE = 1000
MS = {"1d": 86_400_000, "1w": 604_800_000, "1M": 2_629_746_000}
MIN_ROWS = 20  # fewer than this is not a history worth resuming from


def out_csv(interval: str) -> str:
    return os.path.join(DATA, f"binance_btcusdt_{interval}.csv")


def existing(interval: str) -> list[dict]:
    """Rows already on disk, or [] when there is nothing usable to resume from."""
    path = out_csv(interval)
    if not os.path.exists(path):
        return []
    try:
        with open(path, newline="") as fh:
            rows = list(csv.DictReader(fh))
    except (OSError, csv.Error):
        return []
    return rows if len(rows) >= MIN_ROWS else []


def resume_start_ms(interval: str, stored: str) -> int:
    """Open time of the bar after `stored`, which is the newest bar on disk.

    Weekly and monthly opens are NOT epoch-aligned, so this cannot be derived by
    adding an interval length -- it has to go through the calendar. Monthly rows
    are stored as YYYY-MM, hence the separate branch.
    """
    if interval == "1M":
        year, month = (int(x) for x in stored.split("-"))
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
        nxt = dt.datetime(year, month, 1, tzinfo=dt.UTC)
    else:
        step = 7 if interval == "1w" else 1
        nxt = dt.datetime.fromisoformat(stored).replace(tzinfo=dt.UTC) + dt.timedelta(days=step)
    return int(nxt.timestamp() * 1000)


def fetch(url: str, retries: int = 5) -> list:
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "btc-mtf/1.0"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.load(resp)
        except Exception as exc:  # noqa: BLE001
            last = exc
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"failed: {url}: {last}")


def collect(interval: str, start: int) -> list[dict]:
    now = int(time.time() * 1000)
    rows, seen = [], set()
    while True:
        batch = fetch(f"{BASE}?symbol={SYMBOL}&interval={interval}&startTime={start}&limit={PAGE}")
        if not batch:
            break
        for k in batch:
            open_ms, close_ms = k[0], k[6]
            # weekly/monthly opens are not epoch-aligned, so completion is judged
            # by the bar's own close time rather than by open-time alignment
            if open_ms in seen or close_ms >= now:
                continue  # duplicate or still-forming bar
            seen.add(open_ms)
            fmt = "%Y-%m" if interval == "1M" else "%Y-%m-%d"
            rows.append(
                {
                    "date": time.strftime(fmt, time.gmtime(open_ms / 1000)),
                    "open": k[1], "high": k[2], "low": k[3], "close": k[4],
                    "volume": k[5], "trades": k[8],
                }
            )
        start = batch[-1][0] + MS[interval]
        if len(batch) < PAGE:
            break
        time.sleep(0.4)
    rows.sort(key=lambda r: r["date"])
    return rows


def main() -> int:
    resume = "--resume" in sys.argv[1:]
    os.makedirs(DATA, exist_ok=True)
    for interval in ("1d", "1w", "1M"):
        old = existing(interval) if resume else []
        start = resume_start_ms(interval, old[-1]["date"]) if old else 1490000000000
        new = collect(interval, start)
        if old and not new:
            print(f"{interval:>3}: up to date: {old[-1]['date']} ({len(old)} bars)")
            continue
        rows = old + new
        if not rows:
            print(f"{interval}: no bars", file=sys.stderr)
            continue
        path = out_csv(interval)
        with open(path, "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
        print(f"{interval:>3}: {len(rows):>5} bars ({len(new)} appended)  {rows[0]['date']} -> {rows[-1]['date']}  -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())