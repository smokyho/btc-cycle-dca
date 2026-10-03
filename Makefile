# Bitcoin halving-cycle dashboard -- pipeline runner.
#
# There is no committed data. `data/` and `charts/` are built locally and are
# gitignored, so every clone regenerates them from the public APIs. `make serve`
# therefore implies a full refresh: the dashboard is never more stale than the
# clone that started it.
#
#   make serve    refresh everything, then run the dashboard  (network required)
#   make report   re-run the analysis on the data already in data/  (no network)
#   make test     node harnesses, against an already-running server

PY    ?= python3
NODE  ?= node
PORT  ?= 7070
BIND  ?= 0.0.0.0
BASE  ?= http://127.0.0.1:$(PORT)
PIPE  := pipeline
DATA  := data

.DEFAULT_GOAL := help
.PHONY: help install refresh sync analyze report serve test test-render test-e2e clean

help:
	@echo "make install    install python dependencies (numpy, matplotlib)"
	@echo "make serve      refresh all data, then serve on http://127.0.0.1:$(PORT)  [network]"
	@echo "make refresh    refetch everything and rebuild data/ + charts/                [network]"
	@echo "make sync       continue from the data already in data/, then rebuild          [network]"
	@echo "make report     re-run the analysis on existing data/                          [no network]"
	@echo "make test       run the node test harnesses (needs `make serve` running)"
	@echo "make clean      remove data/ and charts/"

install:
	$(PY) -m pip install -r requirements.txt

# --- 1. acquisition (network) -------------------------------------------------
# One request per script. Each paginates at 1000 bars and sleeps between pages.
# Two of the four are resumable: closed klines are immutable, so continuing from
# the newest bar on disk is safe and turns any drift into a single request.

fetch:
	@echo ">> blockstream.info  halving dates"
	$(PY) $(PIPE)/fetch_halvings.py
	@echo ">> blockchain.info   long-tail daily index"
	$(PY) $(PIPE)/fetch_btc_close.py
	@echo ">> Binance           BTC/USDT daily spot"
	$(PY) $(PIPE)/fetch_btc_daily.py
	@echo ">> Binance           BTC/USDT daily / weekly / monthly"
	$(PY) $(PIPE)/fetch_btc_mtf.py

# Halvings and the index tail are single-request endpoints and the projected 5th
# halving is re-derived from the current tip height, so they are always refetched.
sync:
	$(PY) $(PIPE)/fetch_halvings.py --resume
	$(PY) $(PIPE)/fetch_btc_close.py
	$(PY) $(PIPE)/fetch_btc_daily.py --resume
	$(PY) $(PIPE)/fetch_btc_mtf.py --resume
	@$(MAKE) --no-print-directory analyze

# --- 2. analysis (offline) ----------------------------------------------------
# Reads only what is already in data/. Never touches the network, so it is the fast
# inner loop for verifying a logic change.

analyze:
	@for f in bitcoin_halvings btc_usd_close_1d btc_usdt_1d \
	          binance_btcusdt_1d binance_btcusdt_1w binance_btcusdt_1M; do \
	  test -f $(DATA)/$$f.csv || { \
	    echo "missing $(DATA)/$$f.csv -- run 'make refresh' first"; exit 1; }; \
	done
	$(PY) $(PIPE)/build_merged.py
	$(PY) $(PIPE)/analyze_halvings.py
	$(PY) $(PIPE)/cycle_high_low.py
	$(PY) $(PIPE)/backtest_halving_dca.py
	$(PY) $(PIPE)/backtest_halving_dca_compound.py
	$(PY) $(PIPE)/plot_halving_dca.py
	@echo
	$(PY) $(PIPE)/analyze_mtf.py
	@echo
	$(PY) $(PIPE)/forecast_next_cycle.py

report: analyze

refresh: fetch analyze

# --- 3. serve -----------------------------------------------------------------
# refresh is a real prerequisite: a clone with no data/ cannot serve, and a clone
# with yesterday's data/ would quietly show yesterday's analysis.

serve: refresh
	BTC_DASH_PORT=$(PORT) BTC_DASH_BIND=$(BIND) $(PY) server.py

# --- 4. test ------------------------------------------------------------------
# Both harnesses read web/ relative to the working directory, so they must run
# from the repository root. They need a server that is already up.

test-render:
	@curl -fsS "$(BASE)/api/snapshot" -o /tmp/btc-snapshot.json
	$(NODE) tests/test_render.js /tmp/btc-snapshot.json

test-e2e:
	$(NODE) tests/test_e2e.js $(BASE)

test: test-render test-e2e

clean:
	rm -rf $(DATA) charts
