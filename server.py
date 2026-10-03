"""LAN dashboard for the BTC halving-cycle analysis. Stdlib only."""

from __future__ import annotations

import csv
import datetime as dt
import errno
import hashlib
import json
import os
import re
import socket
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import engine  # noqa: E402

# the startup diagnostics below are the only feedback during a (possibly slow)
# data sync, so they must not sit in a buffer when stdout is a pipe or a file
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(line_buffering=True)

ROOT = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.join(ROOT, "web")
DATA = os.path.join(ROOT, "data")
PORT = int(os.environ.get("BTC_DASH_PORT", "7070"))
BIND = os.environ.get("BTC_DASH_BIND", "0.0.0.0")
MAX_STALENESS_DAYS = int(os.environ.get("BTC_DASH_MAX_STALENESS_DAYS", "0"))
SKIP_SYNC = os.environ.get("BTC_DASH_SKIP_SYNC") == "1"
QUIET_PATHS = ("/api/tick",)  # polled every 30s by every open tab; 2xx replies are not news
DAY_MS = 86_400_000

MIME = {".html": "text/html; charset=utf-8", ".js": "application/javascript; charset=utf-8",
        ".css": "text/css; charset=utf-8", ".json": "application/json; charset=utf-8"}


def _read(name: str) -> bytes:
    with open(os.path.join(WEB, name), "rb") as fh:
        return fh.read()


def build_hash(name: str) -> str:
    return hashlib.sha256(_read(name)).hexdigest()[:8]


def index_html() -> bytes:
    """Inject a content hash into asset URLs so a stale cached script or
    stylesheet can never be paired with a newer page."""
    html = _read("index.html").decode()
    for name in ("app.js", "style.css"):
        html = re.sub(rf'/{re.escape(name)}(\?v=[0-9a-f]+)?', f"/{name}?v={build_hash(name)}", html)
    return html.encode()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?")[0]
        try:
            if path in ("/", "/index.html"):
                self._send(200, index_html(), MIME[".html"])
            elif path == "/app.js":
                self._send(200, _read("app.js"), MIME[".js"])
            elif path == "/style.css":
                self._send(200, _read("style.css"), MIME[".css"])
            elif path == "/api/snapshot":
                force = "force=1" in self.path
                payload = json.dumps(engine.snapshot(force=force), default=str).encode()
                self._send(200, payload, MIME[".json"])
            elif path == "/api/tick":
                self._send(200, json.dumps(engine.tick(), default=str).encode(), MIME[".json"])
            elif path == "/api/ping":
                self._send(200, json.dumps({"ok": True, "port": PORT}).encode(), MIME[".json"])
            else:
                self._send(404, b"not found", "text/plain; charset=utf-8")
        except BrokenPipeError:
            pass
        except Exception as exc:  # noqa: BLE001
            self._send(500, json.dumps({"error": str(exc)}).encode(), MIME[".json"])

    def log_message(self, fmt: str, *args) -> None:
        msg = fmt % args
        # routine polls are noise; only surface failures for them
        if any(q in msg for q in QUIET_PATHS) and '" 200 ' in msg:
            return
        sys.stderr.write("%s %s\n" % (self.address_string(), msg))


def lan_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:  # noqa: BLE001
        return "127.0.0.1"
    finally:
        s.close()


def port_holder(port: int) -> str:
    """Best-effort lookup of what is already listening on the port."""
    try:
        out = subprocess.run(["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN"],
                             capture_output=True, text=True, timeout=5).stdout
        lines = [l for l in out.splitlines()[1:] if l.strip()]
        if not lines:
            return "unknown process"
        parts = lines[0].split()
        return f"pid {parts[1]} ({parts[0]})"
    except Exception:  # noqa: BLE001
        return "unknown process"


def _local_last_daily_ms() -> int | None:
    """Open time of the newest daily bar on disk, or None if there is no usable file.

    This is the bar that feeds the merged price series, so it is the one number
    that decides whether the chart and the historical tables are behind.
    """
    try:
        with open(os.path.join(DATA, "btc_usdt_1d.csv"), newline="") as fh:
            rows = list(csv.DictReader(fh))
        if not rows:
            return None
        day = dt.datetime.fromisoformat(rows[-1]["date"]).replace(tzinfo=dt.UTC)
        return int(day.timestamp() * 1000)
    except (OSError, ValueError, KeyError):
        return None


def _run_make(target: str) -> bool:
    try:
        return subprocess.run(["make", target], cwd=ROOT, check=True).returncode == 0
    except FileNotFoundError:
        print("`make` is not on PATH; run `make refresh` by hand and start again", file=sys.stderr)
        return False
    except subprocess.CalledProcessError:
        return False


def sync_if_stale() -> bool:
    """Bring data/ up to date before the socket opens. Returns False to abort startup.

    The dashboard's live panels already read Binance directly and are never stale;
    this only governs data/, which drives the price chart, the historical tables
    and the PNG. Running it here rather than after binding means the page is never
    served stale, and a failed sync exits instead of looping.
    """
    if SKIP_SYNC:
        print("data sync skipped (BTC_DASH_SKIP_SYNC=1)")
        return True

    probe = engine.probe_bars().get("1d")
    if probe is None:
        # a failed probe is not evidence of staleness -- do not trigger a refresh
        # loop because the exchange is rate-limiting or the network is down
        print("exchange unreachable; serving the data already in data/", file=sys.stderr)
        return True

    local = _local_last_daily_ms()
    if local is not None:
        behind = round((probe - local) / DAY_MS)
        if behind <= MAX_STALENESS_DAYS:
            print(f"data is current: last daily close {_iso(local)}")
            return True
        print(f"data is {behind} day(s) behind the exchange "
              f"({_iso(local)} vs {_iso(probe)}) -- syncing")
    else:
        print("no data/ on disk -- full refresh")

    if _run_make("sync") or (local is None and _run_make("refresh")):
        return True

    print("could not update data/. Re-run `make refresh` once the network is back.", file=sys.stderr)
    return False


def _iso(ms: int) -> str:
    return dt.datetime.fromtimestamp(ms / 1000, dt.UTC).strftime("%Y-%m-%d")


def main() -> int:
    if not sync_if_stale():
        return 1
    threading.Thread(target=_warm, daemon=True).start()
    try:
        srv = ThreadingHTTPServer((BIND, PORT), Handler)
    except OSError as exc:
        if exc.errno == errno.EADDRINUSE:
            print(f"port {PORT} is already in use by {port_holder(PORT)}", file=sys.stderr)
            print(f"stop it first, or run with a different PORT (currently {PORT})", file=sys.stderr)
            return 1
        raise
    print(f"serving on http://{BIND}:{PORT}   LAN: http://{lan_ip()}:{PORT}")
    print("press ctrl-c to stop")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nstopping")
    finally:
        srv.server_close()
    return 0


def _warm() -> None:
    try:
        engine.snapshot()
    except Exception as exc:  # noqa: BLE001
        print("warmup failed:", exc, file=sys.stderr)


if __name__ == "__main__":
    sys.exit(main())