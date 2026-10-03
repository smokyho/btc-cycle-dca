#!/usr/bin/env python3
"""Chart the halving-cycle DCA strategy on BTC daily closes.

Price panel: daily close (log scale) from the first buy of cycle 1 to the end of
the series, annotated per cycle with the halving date, the first and last Monday
buy, and the exit date.

Equity panel: the compounding strategy's portfolio value, marked at each exit.

Output: charts/halving_dca.png
"""

import csv
import datetime as dt
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
CHARTS = os.path.join(ROOT, "charts")
PRICES = os.path.join(DATA, "btc_daily_merged.csv")
HALVINGS = os.path.join(DATA, "bitcoin_halvings.csv")
TRADES = os.path.join(DATA, "halving_dca_compound.csv")
OUT = os.path.join(CHARTS, "halving_dca.png")

C_HALVING = "#1f77b4"
C_BUY = "#2ca02c"
C_EXIT = "#d62728"
C_AVG = "#ff7f0e"

plt.rcParams.update({"font.size": 9, "axes.grid": True, "grid.alpha": 0.25})


def read(path: str) -> list[dict]:
    if not os.path.exists(path):
        sys.exit(f"missing input: {path}")
    with open(path, newline="") as fh:
        return list(csv.DictReader(fh))


def main() -> int:
    series = [(dt.date.fromisoformat(r["date"]), float(r["close_usd"])) for r in read(PRICES)]
    halvings = sorted(
        dt.date.fromisoformat(r["date"]) for r in read(HALVINGS) if r["is_estimate"] == "no"
    )
    cycles = read(TRADES)

    start = dt.date.fromisoformat(cycles[0]["first_buy"]) - dt.timedelta(days=200)
    end = series[-1][0]
    xs = [d for d, _ in series if start <= d <= end]
    ys = [c for d, c in series if start <= d <= end]

    fig, ax = plt.subplots(figsize=(16, 8.5))

    ax.plot(xs, ys, color="#333333", lw=0.9, zorder=3, label="BTC daily close (log)")
    ax.set_yscale("log")
    ax.set_ylabel("price (USD, log scale)")

    for c in cycles:
        n = int(c["cycle"])
        halving = dt.date.fromisoformat(c["buy_halving"])
        first = dt.date.fromisoformat(c["first_buy"])
        last = dt.date.fromisoformat(c["last_buy"])
        closed = c["status"] == "closed"
        exit_d = dt.date.fromisoformat(c["exit_date"]) if closed else None

        ax.axvspan(first, last, color=C_BUY, alpha=0.13, zorder=1)
        ax.axvline(halving, color=C_HALVING, lw=1.3, ls="-", zorder=2)
        ax.axvline(first, color=C_BUY, lw=1.0, zorder=2)
        ax.axvline(last, color=C_BUY, lw=1.0, ls=":", zorder=2)
        if exit_d:
            ax.axvline(exit_d, color=C_EXIT, lw=1.3, zorder=2)

        avg = float(c["avg_buy_price"])
        ax.hlines(avg, first, last, color=C_AVG, lw=1.4, ls="--", zorder=4)
        ax.annotate(
            f"avg ${avg:,.0f}",
            xy=(last, avg),
            xytext=(6, 0),
            textcoords="offset points",
            fontsize=7.5,
            color=C_AVG,
            fontweight="bold",
            va="center",
        )

        if closed:
            exit_px = float(c["exit_price"])
            ax.scatter([exit_d], [exit_px], color=C_EXIT, s=32, marker="D", zorder=5)
            ax.annotate(
                f"sell ${exit_px:,.0f}",
                xy=(exit_d, exit_px),
                xytext=(-8, 9),
                textcoords="offset points",
                fontsize=7.5,
                color=C_EXIT,
                fontweight="bold",
                ha="right",
            )
            ax.annotate(
                f"{exit_px / avg:,.1f}x avg",
                xy=(exit_d, (exit_px + avg) / 2),
                xytext=(-8, 0),
                textcoords="offset points",
                fontsize=7,
                color=C_EXIT,
                ha="right",
            )

        ax.annotate(
            f"Cycle {n}  (avg ${avg:,.0f})\nhalving {halving:%Y-%m-%d}\nbuy {first:%Y-%m-%d} → {last:%Y-%m-%d}\n"
            + (f"sell {exit_d:%Y-%m-%d} @ ${float(c['exit_price']):,.0f}" if exit_d else "sell not reached"),
            xy=(first, ys[0]),
            xytext=(first, ys[0] * (4.2 if n % 2 else 1.35)),
            fontsize=7.5,
            color="#333333",
            bbox=dict(boxstyle="round,pad=0.35", fc="white", ec="#bbbbbb", lw=0.6),
            arrowprops=dict(arrowstyle="-", lw=0.6, color="#999999"),
        )

    ax.set_title("Bitcoin halving-cycle DCA (compounding)", fontsize=12, pad=14)
    handles = [
        plt.Line2D([], [], color=C_HALVING, lw=1.5, label="halving date"),
        plt.Line2D([], [], color=C_BUY, lw=1.5, label="buying starts / stops (Mondays)"),
        plt.Line2D([], [], color=C_EXIT, lw=1.5, marker="D", label="sell (exit) at exit price"),
        plt.Line2D([], [], color=C_AVG, lw=1.4, ls="--", label="cycle average buy price"),
    ]
    ax.legend(handles=handles, loc="upper left", framealpha=0.9)
    ax.annotate(
        "prices before 2017-08-17 are the blockchain.info index (not a single exchange)",
        xy=(0.99, 0.02), xycoords="axes fraction", ha="right", fontsize=7, color="#777777",
    )

    ax.set_xlabel("date")
    ax.xaxis.set_major_locator(mdates.YearLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))

    fig.text(
        0.5, 0.035,
        "STRATEGY:  after each halving, buy 1/52 of the portfolio on every Monday from day +718 "
        "to day +1082 (26 weeks either side of the day +900 pivot),\n"
        "then sell the entire position at day +450 after the NEXT halving. "
        "Exit proceeds become the next cycle's capital.",
        ha="center", va="bottom", fontsize=10.5, fontweight="bold", color="#222222",
    )

    os.makedirs(CHARTS, exist_ok=True)
    fig.tight_layout(rect=(0, 0.075, 1, 1))
    fig.savefig(OUT, dpi=140)
    print(f"wrote: {OUT}")
    return 0


START = 5200.0

if __name__ == "__main__":
    sys.exit(main())