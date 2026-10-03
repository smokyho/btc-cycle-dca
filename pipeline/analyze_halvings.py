#!/usr/bin/env python3
"""Measure how long after each halving BTC reached its cycle high and cycle low.

Three windows are produced, because they answer different questions:

  bounded    - halving date -> next halving (or end of data for the unfinished
               cycle). The classic "performance of the halving cycle" number.
               A trough here can only be 0..N days AFTER the halving.
  lookback   - LOOKBACK_DAYS before the halving -> next halving. This is the
               window that actually contains the post-bear-market bottom, so
               days_halving_to_trough goes NEGATIVE when the real low printed
               before the halving.
  openended  - halving date -> end of the available series, so the current
               cycle is not clipped at 2024-04-20.

Days-to-peak / days-to-trough are always signed offsets from the halving date.

Input:  data/btc_daily_merged.csv, data/bitcoin_halvings.csv
Output: data/halving_cycles.csv
"""

import csv
import datetime as dt
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
PRICES = os.path.join(DATA, "btc_daily_merged.csv")
HALVINGS = os.path.join(DATA, "bitcoin_halvings.csv")
OUT = os.path.join(DATA, "halving_cycles.csv")

LOOKBACK_DAYS = 365

FIELDS = (
    "window",
    "event",
    "halving_date",
    "window_start",
    "window_end",
    "window_days",
    "close_at_halving",
    "peak_close",
    "peak_date",
    "days_halving_to_peak",
    "peak_gain_pct",
    "trough_close",
    "trough_date",
    "days_halving_to_trough",
    "trough_change_pct",
    "trough_vs_window_open_pct",
    "close_at_window_end",
    "end_change_pct",
)


def read(path: str) -> list[dict]:
    if not os.path.exists(path):
        sys.exit(f"missing input: {path}")
    with open(path, newline="") as fh:
        return list(csv.DictReader(fh))


def pct(a: float, b: float) -> float:
    return round((b - a) / a * 100, 1) if a else ""


def analyze(
    label: str,
    event: str,
    anchor: dt.date,
    start: dt.date,
    end: dt.date,
    bars: list[tuple[dt.date, float]],
) -> dict:
    window = [(d, c) for d, c in bars if start <= d <= end]
    if not window:
        return {}
    at_anchor = next((c for d, c in bars if d == anchor), window[0][1])
    peak_date, peak_close = max(window, key=lambda x: x[1])
    trough_date, trough_close = min(window, key=lambda x: x[1])
    first_date, first_close = window[0]
    last_date, last_close = window[-1]
    return {
        "window": label,
        "event": event,
        "halving_date": anchor.isoformat(),
        "window_start": first_date.isoformat(),
        "window_end": last_date.isoformat(),
        "window_days": (last_date - first_date).days,
        "close_at_halving": round(at_anchor, 2),
        "peak_close": round(peak_close, 2),
        "peak_date": peak_date.isoformat(),
        "days_halving_to_peak": (peak_date - anchor).days,
        "peak_gain_pct": pct(at_anchor, peak_close),
        "trough_close": round(trough_close, 2),
        "trough_date": trough_date.isoformat(),
        "days_halving_to_trough": (trough_date - anchor).days,
        "trough_change_pct": pct(at_anchor, trough_close),
        "trough_vs_window_open_pct": pct(first_close, trough_close),
        "close_at_window_end": round(last_close, 2),
        "end_change_pct": pct(at_anchor, last_close),
    }


def main() -> int:
    bars = [(dt.date.fromisoformat(r["date"]), float(r["close_usd"])) for r in read(PRICES)]
    data_start, data_end = min(d for d, _ in bars), max(d for d, _ in bars)
    halvings = [r for r in read(HALVINGS) if r["is_estimate"] == "no"]

    rows = []
    for i, h in enumerate(halvings):
        anchor = dt.date.fromisoformat(h["date"])
        if anchor > data_end:
            continue
        next_h = dt.date.fromisoformat(halvings[i + 1]["date"]) if i + 1 < len(halvings) else data_end
        cycle_end = min(next_h, data_end)
        rows.append(analyze("bounded", h["event"], anchor, anchor, cycle_end, bars))
        lookback_start = max(anchor - dt.timedelta(days=LOOKBACK_DAYS), data_start)
        rows.append(analyze("lookback", h["event"], anchor, lookback_start, cycle_end, bars))
        rows.append(analyze("openended", h["event"], anchor, anchor, data_end, bars))

    rows = [r for r in rows if r]
    with open(OUT, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(FIELDS))
        writer.writeheader()
        writer.writerows(rows)

    for label in ("bounded", "lookback"):
        hdr = f"\n[{label}]  {'halving':11} {'peak':>9} {'d->peak':>8} {'trough':>9} {'troughdate':11} {'d->trough':>9}"
        print(hdr)
        print("-" * len(hdr))
        for r in rows:
            if r["window"] != label:
                continue
            print(
                f"{'':10} {r['halving_date']:11} {r['peak_close']:>9.0f} {r['days_halving_to_peak']:>8} "
                f"{r['trough_close']:>9.2f} {r['trough_date']:11} {r['days_halving_to_trough']:>9}"
            )

    print(f"\nwrote: {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())