#!/usr/bin/env python3
"""Halving-cycle DCA backtest.

Rules (as specified):
  - Buy $100 of BTC on EVERY Monday from halving_day + 718 to halving_day + 1082
    (26 weeks each side of the day-900 pivot = one 52-week DCA window).
  - Sell the entire position at halving_day + 450 of the FOLLOWING cycle.
  - $100 per buy is fixed; proceeds roll into the next cycle, so the growth is
    compounding through carried cash rather than through a scaling notional.

Execution assumption: every trade fills at that day's daily close. No fees,
slippage or taxes.

Initial cash is $5,200 = exactly one full 52-buy window, so cycle 1 is fully
funded and every later cycle's surplus cash compounds forward.

Input:  data/btc_daily_merged.csv, data/bitcoin_halvings.csv
Output: data/halving_dca_backtest.csv
"""

import csv
import datetime as dt
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
PRICES = os.path.join(DATA, "btc_daily_merged.csv")
HALVINGS = os.path.join(DATA, "bitcoin_halvings.csv")
OUT = os.path.join(DATA, "halving_dca_backtest.csv")

BUY_NOTIONAL = 100.0
BUY_OFFSETS = 718, 1082  # 26 weeks before/after the day-900 pivot
SELL_OFFSET = 450  # days after the NEXT halving
INITIAL_CASH = 5200.0

FIELDS = (
    "cycle",
    "buy_halving",
    "first_buy", "last_buy", "mondays",
    "avg_buy_price",
    "exit_halving", "exit_date", "exit_price",
    "cash_in", "cash_out", "cash_carried",
    "cycle_return_pct",
    "btc_units",
)


def read(path: str) -> list[dict]:
    if not os.path.exists(path):
        sys.exit(f"missing input: {path}")
    with open(path, newline="") as fh:
        return list(csv.DictReader(fh))


def main() -> int:
    bars = sorted((dt.date.fromisoformat(r["date"]), float(r["close_usd"])) for r in read(PRICES))
    prices = dict(bars)
    halvings = sorted(dt.date.fromisoformat(r["date"]) for r in read(HALVINGS) if r["is_estimate"] == "no")
    data_end = bars[-1][0]

    rows, cash = [], INITIAL_CASH
    for i in range(len(halvings)):
        buy_h = halvings[i]
        next_h = halvings[i + 1] if i + 1 < len(halvings) else None
        first, last = buy_h + dt.timedelta(days=BUY_OFFSETS[0]), buy_h + dt.timedelta(days=BUY_OFFSETS[1])

        buys = []
        d = first
        while d <= last:
            if d.weekday() == 0 and d in prices:  # Monday with a candle
                buys.append((d, prices[d]))
            d += dt.timedelta(days=1)
        if not buys:
            sys.exit(f"no Monday bars for cycle {i + 1}")

        exit_date = (next_h + dt.timedelta(days=SELL_OFFSET)) if next_h else None
        if exit_date is None or exit_date > data_end:
            rows.append(pending(i + 1, buy_h, next_h, buys, exit_date, data_end, prices))
            continue

        units, cash_spent = 0.0, 0.0
        for day, price in buys:
            amount = min(BUY_NOTIONAL, cash - cash_spent)
            if amount < 1e-9:
                break
            units += amount / price
            cash_spent += amount
        exit_price = prices[exit_date]
        cash_out = units * exit_price
        cash = cash - cash_spent + cash_out

        rows.append(
            {
                "cycle": i + 1,
                "buy_halving": buy_h.isoformat(),
                "first_buy": buys[0][0].isoformat(),
                "last_buy": buys[-1][0].isoformat(),
                "mondays": len(buys),
                "avg_buy_price": round(sum(c for _, c in buys) / len(buys), 2),
                "exit_halving": next_h.isoformat(),
                "exit_date": exit_date.isoformat(),
                "exit_price": round(exit_price, 2),
                "cash_in": round(cash_spent, 2),
                "cash_out": round(cash_out, 2),
                "cash_carried": round(cash, 2),
                "cycle_return_pct": round((cash_out - cash_spent) / cash_spent * 100, 1) if cash_spent else "",
                "btc_units": round(units, 6),
            }
        )

    with open(OUT, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(FIELDS))
        writer.writeheader()
        writer.writerows(rows)

    report(rows, INITIAL_CASH)
    print(f"\nwrote: {OUT}")
    return 0


def pending(n, buy_h, next_h, buys, exit_date, data_end, prices) -> dict:
    last_px = prices[data_end]
    return {
        "cycle": n,
        "buy_halving": buy_h.isoformat(),
        "first_buy": buys[0][0].isoformat(),
        "last_buy": buys[-1][0].isoformat(),
        "mondays": len(buys),
        "avg_buy_price": round(sum(c for _, c in buys) / len(buys), 2),
        "exit_halving": next_h.isoformat() if next_h else "",
        "exit_date": exit_date.isoformat() if exit_date else "beyond data",
        "exit_price": f"mark {last_px}",
        "cash_in": len(buys) * BUY_NOTIONAL,
        "cash_out": "",
        "cash_carried": "",
        "cycle_return_pct": "open",
        "btc_units": "",
    }


def report(rows: list[dict], initial: float) -> None:
    hdr = (
        f"{'cyc':>3} {'buys':>5} {'avg buy':>10} {'exit date':11} {'exit px':>11} "
        f"{'spent':>8} {'returned':>10} {'ret%':>7} {'cash after':>11}"
    )
    print(hdr)
    print("-" * len(hdr))
    for r in rows:
        ret = f"{r['cycle_return_pct']}" if r["cycle_return_pct"] != "open" else "open"
        print(
            f"{r['cycle']:>3} {r['mondays']:>5} {r['avg_buy_price']:>10.2f} {r['exit_date']:11} "
            f"{str(r['exit_price']):>11} {r['cash_in']:>8.2f} {str(r['cash_out']):>10} "
            f"{str(ret):>7} {str(r['cash_carried']):>11}"
        )
    closed = [r for r in rows if r["cycle_return_pct"] != "open"]
    if closed:
        final = closed[-1]["cash_carried"]
        print(
            f"\nclosed cycles: {len(closed)}   start ${initial:,.0f} -> ${final:,.2f}   "
            f"total {(final / initial - 1) * 100:,.1f}%   x{final / initial:.3f}"
        )
        print(f"CAGR over {len(closed)} cycles: {((final / initial) ** (1 / len(closed)) - 1) * 100:,.1f}% per cycle")


if __name__ == "__main__":
    sys.exit(main())