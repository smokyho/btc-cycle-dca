#!/usr/bin/env python3
"""Merge the two daily close series into one continuous series with a source column.

Rule: Binance BTC/USDT spot is preferred wherever it exists (exchange-grade,
closes at 23:59:59 UTC). blockchain.info fills the long tail before Binance
listed (2017-08-17). Rows whose blockchain.info close is 0.00 are dropped --
that series has dates but no price for 2009-01-03 .. 2010-08-17.

Also annotates each row with days since the most recent halving, and the number
of halvings that have already occurred, which is usually the feature a halving
study actually needs.

Input:  data/btc_usdt_1d.csv, data/btc_usd_close_1d.csv, data/bitcoin_halvings.csv
Output: data/btc_daily_merged.csv
"""

import csv
import datetime as dt
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
BINANCE = os.path.join(DATA, "btc_usdt_1d.csv")
BLOCKCHAIN = os.path.join(DATA, "btc_usd_close_1d.csv")
HALVINGS = os.path.join(DATA, "bitcoin_halvings.csv")
OUT = os.path.join(DATA, "btc_daily_merged.csv")


def read(path: str) -> list[dict]:
    if not os.path.exists(path):
        sys.exit(f"missing input: {path}")
    with open(path, newline="") as fh:
        return list(csv.DictReader(fh))


def main() -> int:
    binance = {r["date"]: r for r in read(BINANCE)}
    chain = {r["date"]: r for r in read(BLOCKCHAIN)}

    halvings = sorted(
        (dt.date.fromisoformat(r["date"]), int(r["block_height"]), float(r["new_subsidy_btc"]))
        for r in read(HALVINGS)
        if r["is_estimate"] == "no"  # exclude the projected 5th
    )

    dates = sorted(set(binance) | {d for d, r in chain.items() if float(r["close_usd"]) > 0})
    if not dates:
        sys.exit("no rows to write")

    rows = []
    for date_str in dates:
        day = dt.date.fromisoformat(date_str)
        if date_str in binance:
            src, close, note = "binance_btcusdt", float(binance[date_str]["close"]), ""
        else:
            src, close = "blockchain_info", float(chain[date_str]["close_usd"])
            note = "pre-binance-listing; index price, not a single exchange"

        past = [h for h in halvings if h[0] <= day]
        last = past[-1] if past else None
        rows.append(
            {
                "date": date_str,
                "close_usd": round(close, 2),
                "source": src,
                "days_since_halving": (day - last[0]).days if last else "",
                "halvings_passed": len(past),
                "block_subsidy_btc": last[2] if last else "",
                "note": note,
            }
        )

    with open(OUT, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    days = [dt.date.fromisoformat(r["date"]) for r in rows]
    by_src = {}
    for r in rows:
        by_src[r["source"]] = by_src.get(r["source"], 0) + 1
    print(f"rows:  {len(rows)}")
    print(f"span:  {days[0]} -> {days[-1]}  ({(days[-1] - days[0]).days + 1} days)")
    print(f"gaps:  {sum(1 for i in range(1, len(days)) if (days[i] - days[i - 1]).days != 1)}")
    for src, n in sorted(by_src.items()):
        print(f"  {src:18} {n:>5} rows")
    print(f"wrote: {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())