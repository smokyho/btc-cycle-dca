#!/usr/bin/env python3
"""For each halving cycle [halving A, halving B): highest and lowest daily close,
the date each occurred, and how many days after halving A that was.

Cycle 1 = 2012-11-28 -> 2016-07-09, cycle 2 = 2016-07-09 -> 2020-05-11,
cycle 3 = 2020-05-11 -> 2024-04-20, cycle 4 = 2024-04-20 -> last bar.

Output: data/cycle_high_low.csv and a printed table.
"""

import csv
import datetime as dt
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
PRICES = os.path.join(DATA, "btc_daily_merged.csv")
HALVINGS = os.path.join(DATA, "bitcoin_halvings.csv")
OUT = os.path.join(DATA, "cycle_high_low.csv")

FIELDS = (
    "cycle",
    "halving_a",
    "halving_b",
    "high_close",
    "high_date",
    "days_from_a_to_high",
    "low_after_high_close",
    "low_after_high_date",
    "days_from_a_to_low_after_high",
    "days_from_high_to_low_after_high",
    "drawdown_pct",
    "low_close",
    "low_date",
    "days_from_a_to_low",
    "close_at_a",
    "close_at_b_minus1",
    "bars",
)


def read(path: str) -> list[dict]:
    if not os.path.exists(path):
        sys.exit(f"missing input: {path}")
    with open(path, newline="") as fh:
        return list(csv.DictReader(fh))


def main() -> int:
    bars = sorted((dt.date.fromisoformat(r["date"]), float(r["close_usd"])) for r in read(PRICES))
    halvings = sorted(dt.date.fromisoformat(r["date"]) for r in read(HALVINGS) if r["is_estimate"] == "no")
    data_start, data_end = bars[0][0], bars[-1][0]

    rows = []
    for i in range(len(halvings) - 1):
        a, b = halvings[i], halvings[i + 1]
        rows.append(one(i + 1, a, b, bars, data_start, data_end))
    rows.append(one(len(halvings), halvings[-1], None, bars, data_start, data_end))

    with open(OUT, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(FIELDS))
        writer.writeheader()
        writer.writerows(rows)

    print(
        f"{'cycle':6} {'A':11} {'B':20} {'HIGH':>10} {'high date':11} {'dA->':>5} "
        f"{'LOW after high':>15} {'date':11} {'dA->':>5} {'peak->low':>10} {'dd%':>7}"
    )
    print("-" * 122)
    for r in rows:
        b_label = r["halving_b"] or f"{data_end} (last)"
        print(
            f"{r['cycle']:<6} {r['halving_a']:11} {b_label:20} "
            f"{r['high_close']:>10.2f} {r['high_date']:11} {r['days_from_a_to_high']:>5} "
            f"{r['low_after_high_close']:>15.2f} {r['low_after_high_date']:11} "
            f"{r['days_from_a_to_low_after_high']:>5} {r['days_from_high_to_low_after_high']:>10} {r['drawdown_pct']:>7}"
        )
    print(f"\nwrote: {OUT}")
    return 0


def one(n: int, a: dt.date, b: dt.date | None, bars, data_start: dt.date, data_end: dt.date) -> dict:
    end = b if b is not None else data_end
    window = [(d, c) for d, c in bars if a <= d <= end]
    if not window:
        sys.exit(f"no bars for cycle starting {a}")
    high_date, high = max(window, key=lambda x: x[1])
    low_date, low = min(window, key=lambda x: x[1])
    # lowest close that occurs strictly AFTER the cycle high
    after = [(d, c) for d, c in window if d > high_date]
    if after:
        lah_date, lah = min(after, key=lambda x: x[1])
    else:
        lah_date, lah = high_date, high
    return {
        "cycle": n,
        "halving_a": a.isoformat(),
        "halving_b": b.isoformat() if b else "",
        "high_close": round(high, 2),
        "high_date": high_date.isoformat(),
        "days_from_a_to_high": (high_date - a).days,
        "low_after_high_close": round(lah, 2),
        "low_after_high_date": lah_date.isoformat(),
        "days_from_a_to_low_after_high": (lah_date - a).days,
        "days_from_high_to_low_after_high": (lah_date - high_date).days,
        "drawdown_pct": round((lah - high) / high * 100, 1),
        "low_close": round(low, 2),
        "low_date": low_date.isoformat(),
        "days_from_a_to_low": (low_date - a).days,
        "close_at_a": round(window[0][1], 2),
        "close_at_b_minus1": round(window[-1][1], 2),
        "bars": len(window),
    }


if __name__ == "__main__":
    sys.exit(main())