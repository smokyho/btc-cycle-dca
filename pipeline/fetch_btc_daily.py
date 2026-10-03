#!/usr/bin/env python3
"""Download full daily BTC/USDT spot candles from Binance's public REST API.

No API key required. Binance serves 1000 klines per request, so the range is
paginated forward from the market's first available day until caught up.

--resume continues from the last bar already in the output file instead of
starting at 2017, which turns a 100-day drift into a single request. Closed
klines are immutable, so appending is safe; the file is always rewritten whole so
a half-finished run can never leave duplicates behind.

Output: data/btc_usdt_1d.csv  (date,open,high,low,close,volume,quote_volume,trades)
"""

import csv
import datetime as dt
import json
import os
import sys
import time
import urllib.request

SYMBOL = "BTCUSDT"
INTERVAL = "1d"
BASE = "https://api.binance.com/api/v3/klines"
START_MS = 1500000000000  # 2017-07-14, before Binance spot BTC/USDT listing
DAY_MS = 86_400_000
PAGE = 1000
MIN_ROWS = 100  # fewer than this is not a history worth resuming from

OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
OUT_CSV = os.path.join(OUT_DIR, "btc_usdt_1d.csv")

FIELDS = ("date", "open", "high", "low", "close", "volume", "quote_volume", "trades")


def fetch(url: str, retries: int = 5) -> list:
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "btc-daily-fetch/1.0"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.load(resp)
        except Exception as exc:  # noqa: BLE001
            last = exc
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"failed after {retries} attempts: {url}: {last}")


def existing() -> list[dict]:
    """Rows already on disk, or [] when there is nothing usable to resume from."""
    if not os.path.exists(OUT_CSV):
        return []
    try:
        with open(OUT_CSV, newline="") as fh:
            rows = list(csv.DictReader(fh))
    except (OSError, csv.Error):
        return []
    return rows if len(rows) >= MIN_ROWS else []


def resume_start_ms(rows: list[dict]) -> int:
    """Open time of the bar after the newest one on disk."""
    last = dt.datetime.strptime(rows[-1]["date"], "%Y-%m-%d").replace(tzinfo=dt.UTC)
    return int(last.timestamp() * 1000) + DAY_MS


def collect(start_ms: int) -> list:
    rows = []
    start = start_ms
    now = int(time.time() * 1000)
    while True:
        batch = fetch(f"{BASE}?symbol={SYMBOL}&interval={INTERVAL}&startTime={start}&limit={PAGE}")
        if not batch:
            break
        for k in batch:
            open_ms, close_ms = k[0], k[6]
            # completion is judged by the bar's own CLOSE time: an open-time test only
            # rejects future bars, so it would keep the day that is still forming
            if open_ms % DAY_MS != 0 or close_ms >= now:
                continue  # misaligned bar, or the in-progress day
            rows.append(
                {
                    "date": time.strftime("%Y-%m-%d", time.gmtime(open_ms / 1000)),
                    "open": k[1],
                    "high": k[2],
                    "low": k[3],
                    "close": k[4],
                    "volume": k[5],
                    "quote_volume": k[7],
                    "trades": k[8],
                }
            )
        start = batch[-1][0] + DAY_MS
        if len(batch) < PAGE:
            break
        time.sleep(0.4)  # stay well inside Binance's weight limits
    return rows


def main() -> int:
    resume = "--resume" in sys.argv[1:]
    old = existing() if resume else []
    start = resume_start_ms(old) if old else START_MS
    new = collect(start)
    if old and not new:
        print(f"up to date: {old[-1]['date']} ({len(old)} rows, nothing appended)")
        return 0

    rows = old + new
    if not rows:
        print("no candles returned", file=sys.stderr)
        return 1

    os.makedirs(OUT_DIR, exist_ok=True)
    with open(OUT_CSV, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(FIELDS))
        writer.writeheader()
        writer.writerows(rows)

    print(f"rows:  {len(rows)}  ({len(new)} appended)")
    print(f"first: {rows[0]['date']}")
    print(f"last:  {rows[-1]['date']}")
    print(f"wrote: {OUT_CSV}")
    return 0


if __name__ == "__main__":
    sys.exit(main())