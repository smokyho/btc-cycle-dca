#!/usr/bin/env python3
"""Download the longest free daily BTC/USD close series.

Primary source: blockchain.info charts market-price, timespan=all, sampled=false
-> one point per day, 2009-01-03 onward, no gaps, no API key.

CoinGecko is NOT used: the public (keyless) tier hard-caps historical range to the
past 365 days (error_code 10012), so it cannot supply deep history.
"""

import csv
import json
import os
import sys
import time
import urllib.request

URL = "https://api.blockchain.info/charts/market-price?timespan=all&format=json&sampled=false"
OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
OUT_CSV = os.path.join(OUT_DIR, "btc_usd_close_1d.csv")


def fetch(url: str, retries: int = 5) -> dict:
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "btc-close-fetch/1.0"})
            with urllib.request.urlopen(req, timeout=45) as resp:
                return json.load(resp)
        except Exception as exc:  # noqa: BLE001
            last = exc
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"failed after {retries} attempts: {url}: {last}")


def main() -> int:
    payload = fetch(URL)
    values = payload.get("values") or []
    if not values:
        print(f"no values returned: {str(payload)[:200]}", file=sys.stderr)
        return 1

    rows = [
        {
            "date": time.strftime("%Y-%m-%d", time.gmtime(v["x"])),
            "close_usd": round(float(v["y"]), 2),
        }
        for v in values
    ]
    rows.sort(key=lambda r: r["date"])

    today = time.strftime("%Y-%m-%d", time.gmtime())
    rows = [r for r in rows if r["date"] < today]

    os.makedirs(OUT_DIR, exist_ok=True)
    with open(OUT_CSV, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["date", "close_usd"])
        writer.writeheader()
        writer.writerows(rows)

    print(f"rows:  {len(rows)}")
    print(f"first: {rows[0]['date']} @ {rows[0]['close_usd']}")
    print(f"last:  {rows[-1]['date']} @ {rows[-1]['close_usd']}")
    print(f"wrote: {OUT_CSV}")
    return 0


if __name__ == "__main__":
    sys.exit(main())