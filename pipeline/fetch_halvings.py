#!/usr/bin/env python3
"""Halving dates for Bitcoin, verified against block data from blockstream.info.

The subsidy schedule is a protocol constant (50 BTC -> halving every 210,000
blocks), so only the DATE of each halving block has to be looked up. Each date
below is read from the canonical block timestamp at the halving height.

The next unmined halving's date is an ESTIMATE projected from the observed block
rate since the last halving, and is flagged as such.

--resume reuses the dates already in the output file for halvings that are still
mined, because a mined block's timestamp can never change. That turns ten requests
into one. Which heights are still unmined is decided from the live tip height, so
halving 5 is promoted from an estimate to a real date the moment it is mined, and
halving 6 becomes the new estimate.

Output: data/bitcoin_halvings.csv
"""

import csv
import datetime as dt
import os
import sys
import time
import urllib.request

API = "https://blockstream.info/api"
HALVING_HEIGHTS = (210_000, 420_000, 630_000, 840_000)
# beyond the current tip, so there is always one projected halving to report
FUTURE_HEIGHTS = (1_050_000, 1_260_000, 1_470_000)
ALL_HEIGHTS = HALVING_HEIGHTS + FUTURE_HEIGHTS
OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
OUT_CSV = os.path.join(OUT_DIR, "bitcoin_halvings.csv")


def cached_dates() -> dict[int, str]:
    """height -> date for halvings already recorded as mined (is_estimate == no).

    Only mined halvings are reusable: an estimated date is re-derived every run
    because it moves with the observed block rate.
    """
    if not os.path.exists(OUT_CSV):
        return {}
    try:
        with open(OUT_CSV, newline="") as fh:
            rows = list(csv.DictReader(fh))
    except (OSError, csv.Error):
        return {}
    return {
        int(r["block_height"]): r["date"]
        for r in rows
        if r.get("is_estimate") == "no" and r.get("block_height")
    }


def get(path: str, retries: int = 4) -> str:
    url = f"{API}/{path}"
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "btc-halving-fetch/1.0"})
            with urllib.request.urlopen(req, timeout=25) as resp:
                return resp.read().decode().strip().strip('"')
        except Exception as exc:  # noqa: BLE001
            last = exc
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"failed: {url}: {last}")


def block_date(height: int) -> tuple[str, int]:
    block_hash = get(f"block-height/{height}")
    ts = int(get(f"block/{block_hash}").split('"timestamp":')[1].split(",")[0])
    return time.strftime("%Y-%m-%d", time.gmtime(ts)), ts


def main() -> int:
    resume = "--resume" in sys.argv[1:]
    cached = cached_dates() if resume else {}

    tip_height = int(get("blocks/tip/height"))
    mined = [h for h in ALL_HEIGHTS if h <= tip_height]
    pending = [h for h in ALL_HEIGHTS if h > tip_height]
    if not mined or not pending:
        sys.exit(f"tip height {tip_height} is outside the expected halving schedule")

    rows = []
    prev = None
    for i, height in enumerate(mined, start=1):
        hit = cached.get(height)
        if hit:
            date, ts = hit, None
        else:
            date, ts = block_date(height)
        rows.append(
            {
                "event": f"halving_{i}",
                "block_height": height,
                "date": date,
                "new_subsidy_btc": 50 / (2**i),
                "days_since_prev": _since(prev, date),
                "is_estimate": "no",
            }
        )
        prev = (date, ts, height)

    # the last mined halving's timestamp anchors the block rate; a cached date has
    # no timestamp, so re-read just that one block
    last_date, last_ts, last_h = prev
    if last_ts is None:
        _, last_ts = block_date(last_h)

    now_ts = int(time.time())
    blocks_per_day = (tip_height - last_h) / max((now_ts - last_ts) / 86400, 1)
    next_h = pending[0]
    eta_days = (next_h - tip_height) / blocks_per_day
    eta = time.strftime("%Y-%m-%d", time.gmtime(now_ts + eta_days * 86400))
    rows.append(
        {
            "event": f"halving_{len(rows) + 1}",
            "block_height": next_h,
            "date": eta,
            "new_subsidy_btc": 50 / (2 ** (len(rows) + 1)),
            "days_since_prev": int(round(eta_days)),
            "is_estimate": "yes (projected from observed block rate)",
        }
    )

    os.makedirs(OUT_DIR, exist_ok=True)
    with open(OUT_CSV, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    reused = sum(1 for h in mined if h in cached)
    print(f"tip height: {tip_height}  ({blocks_per_day:.1f} blocks/day)  [{reused} date(s) reused]")
    for r in rows:
        flag = "  (estimate)" if r["is_estimate"] != "no" else ""
        print(f"{r['event']:12} block {r['block_height']:>9}  {r['date']}  -> {r['new_subsidy_btc']} BTC{flag}")
    print(f"wrote: {OUT_CSV}")
    return 0


def _since(prev: tuple[str, int, int] | None, date: str) -> int | str:
    if not prev:
        return ""
    a = dt.datetime.strptime(prev[0], "%Y-%m-%d").replace(tzinfo=dt.UTC)
    b = dt.datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=dt.UTC)
    return (b - a).days


if __name__ == "__main__":
    sys.exit(main())