#!/usr/bin/env python3
"""Halving-cycle DCA backtest, compounding variant.

Rule: at the start of each cycle the ENTIRE portfolio is deployed, split into 52
equal weekly installments. The exit proceeds become the next cycle's capital, so
the position size scales every cycle:

    weekly_instalment = cash_at_cycle_start / 52
    cash_at_next_start = units * exit_price

No idle cash is carried between cycles. Every trade fills at that day's daily
close; no fees, slippage or taxes.

Input:  data/btc_daily_merged.csv, data/bitcoin_halvings.csv
Output: data/halving_dca_compound.csv
"""

import csv
import datetime as dt
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
PRICES = os.path.join(DATA, "btc_daily_merged.csv")
HALVINGS = os.path.join(DATA, "bitcoin_halvings.csv")
OUT = os.path.join(DATA, "halving_dca_compound.csv")

N_INSTALLMENTS = 52
BUY_OFFSETS = 718, 1082
SELL_OFFSET = 450
START_CASH = 5200.0  # = 52 x $100, so cycle 1 matches the fixed-notional run

FIELDS = (
    "cycle",
    "buy_halving",
    "capital_at_start",
    "installment",
    "mondays",
    "first_buy", "last_buy",
    "avg_buy_price",
    "cash_deployed",
    "btc_units",
    "exit_halving", "exit_date", "exit_price",
    "cash_out",
    "cycle_return_pct",
    "value_multiple",
    "status",
)


def read(path: str) -> list[dict]:
    if not os.path.exists(path):
        sys.exit(f"missing input: {path}")
    with open(path, newline="") as fh:
        return list(csv.DictReader(fh))


def monday_prices(anchor: dt.date, prices: dict, first: dt.date, last: dt.date) -> list[tuple[dt.date, float]]:
    out = []
    d = first
    while d <= last:
        if d.weekday() == 0 and d.isoformat() in prices:
            out.append((d, prices[d.isoformat()]))
        d += dt.timedelta(days=1)
    return out


def main() -> int:
    prices = {r["date"]: float(r["close_usd"]) for r in read(PRICES)}
    data_end = max(dt.date.fromisoformat(k) for k in prices)
    halvings = sorted(
        dt.date.fromisoformat(r["date"]) for r in read(HALVINGS) if r["is_estimate"] == "no"
    )

    rows = []
    cash = START_CASH
    for i, buy_h in enumerate(halvings):
        buys = monday_prices(buy_h, prices, buy_h + dt.timedelta(days=BUY_OFFSETS[0]), buy_h + dt.timedelta(days=BUY_OFFSETS[1]))
        if not buys:
            sys.exit(f"no Monday bars for cycle {i + 1}")

        installment = cash / N_INSTALLMENTS
        units = sum(installment / p for _, p in buys)
        deployed = installment * len(buys)
        next_h = halvings[i + 1] if i + 1 < len(halvings) else None
        exit_date = next_h + dt.timedelta(days=SELL_OFFSET) if next_h else None
        closed = exit_date is not None and exit_date <= data_end and len(buys) == N_INSTALLMENTS

        if closed:
            exit_px = prices[exit_date.isoformat()]
            cash_out = units * exit_px
            ret = (cash_out - deployed) / deployed * 100
        else:
            exit_px = None
            cash_out = None
            ret = None

        rows.append(
            {
                "cycle": i + 1,
                "buy_halving": buy_h.isoformat(),
                "capital_at_start": round(cash, 2),
                "installment": round(installment, 2),
                "mondays": len(buys),
                "first_buy": buys[0][0].isoformat(),
                "last_buy": buys[-1][0].isoformat(),
                "avg_buy_price": round(sum(p for _, p in buys) / len(buys), 2),
                "cash_deployed": round(deployed, 2),
                "btc_units": round(units, 8),
                "exit_halving": next_h.isoformat() if next_h else "",
                "exit_date": exit_date.isoformat() if exit_date else "beyond data",
                "exit_price": round(exit_px, 2) if closed else "not reached",
                "cash_out": round(cash_out, 2) if closed else "",
                "cycle_return_pct": round(ret, 1) if closed else "",
                "value_multiple": round(cash_out / deployed, 3) if closed else "",
                "status": "closed" if closed else f"open ({len(buys)}/{N_INSTALLMENTS} buys, exit unreachable)",
            }
        )

        if not closed:
            break
        cash = cash_out

    with open(OUT, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(FIELDS))
        writer.writeheader()
        writer.writerows(rows)

    hdr = (
        f"{'cyc':>3} {'capital in':>12} {'instal':>9} {'buys':>5} {'avg px':>11} "
        f"{'units':>12} {'exit date':11} {'exit px':>12} {'cash out':>13} {'x':>7} {'ret%':>8}"
    )
    print(hdr)
    print("-" * len(hdr))
    for r in rows:
        print(
            f"{r['cycle']:>3} {r['capital_at_start']:>12,.2f} {r['installment']:>9,.2f} {r['mondays']:>5} "
            f"{r['avg_buy_price']:>11,.2f} {r['btc_units']:>12.6f} {r['exit_date']:11} "
            f"{str(r['exit_price']):>12} {str(r['cash_out'] if r['cash_out'] != '' else '-'):>13} "
            f"{str(r['value_multiple'] if r['value_multiple'] != '' else '-'):>7} "
            f"{str(r['cycle_return_pct'] if r['cycle_return_pct'] != '' else '-'):>8}"
        )
    closed = [r for r in rows if r["status"] == "closed"]
    if closed:
        final = closed[-1]["cash_out"]
        n = len(closed)
        print(
            f"\n{n} closed cycles: {START_CASH:,.2f} -> {final:,.2f}   "
            f"total {(final / START_CASH - 1) * 100:,.1f}%   x{final / START_CASH:.3f}"
        )
        print(f"CAGR per cycle: {((final / START_CASH) ** (1 / n) - 1) * 100:,.1f}%")
    print(f"\nwrote: {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())