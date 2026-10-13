"""baostock must not block the settle path when the peer never answers.

The incident socket was ESTAB to :10030 and stuck in recv. These tests
accept the TCP handshake and then send nothing.
"""

from __future__ import annotations

import signal
import socket
import sys
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from sequoia_x.data.baostock_guard import install, reset  # noqa: E402


class _Hang(AssertionError):
    pass


@pytest.fixture
def blackhole():
    """TCP peer that accepts and never sends a byte."""
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    srv.listen(16)
    srv.settimeout(0.2)
    port = srv.getsockname()[1]
    stop = threading.Event()
    held: list[socket.socket] = []

    def loop() -> None:
        while not stop.is_set():
            try:
                conn, _addr = srv.accept()
            except TimeoutError:
                continue
            except OSError:
                break
            held.append(conn)

    thread = threading.Thread(target=loop, daemon=True)
    thread.start()

    import baostock.common.contants as cons

    old_ip = cons.BAOSTOCK_SERVER_IP
    old_vip = cons.BAOSTOCK_VIP_SERVER_IP
    old_port = cons.BAOSTOCK_SERVER_PORT
    old_default = socket.getdefaulttimeout()
    cons.BAOSTOCK_SERVER_IP = "127.0.0.1"
    cons.BAOSTOCK_VIP_SERVER_IP = "127.0.0.1"
    cons.BAOSTOCK_SERVER_PORT = port
    reset()
    install(timeout=0.4)
    try:
        yield port
    finally:
        cons.BAOSTOCK_SERVER_IP = old_ip
        cons.BAOSTOCK_VIP_SERVER_IP = old_vip
        cons.BAOSTOCK_SERVER_PORT = old_port
        socket.setdefaulttimeout(old_default)
        reset()
        stop.set()
        srv.close()
        for conn in held:
            try:
                conn.close()
            except OSError:
                pass


def _arm_deadline(seconds: int = 5) -> None:
    def _boom(_signum, _frame):
        raise _Hang(f"baostock call still blocked after {seconds}s")

    signal.signal(signal.SIGALRM, _boom)
    signal.alarm(seconds)


def test_login_against_silent_socket_returns(blackhole) -> None:
    import baostock as bs

    _arm_deadline()
    try:
        started = time.monotonic()
        result = bs.login()
        elapsed = time.monotonic() - started
    finally:
        signal.alarm(0)
    assert elapsed < 3.0, elapsed
    assert result is None or getattr(result, "error_code", "0") != "0"
    # Circuit is open: a second call must not sit in recv again.
    started = time.monotonic()
    again = bs.login()
    assert time.monotonic() - started < 1.0
    assert again is None or getattr(again, "error_code", "0") != "0"


def test_sync_watch_today_falls_through_when_socket_is_silent(blackhole) -> None:
    import sync_watch_today

    _arm_deadline()
    try:
        started = time.monotonic()
        rows = sync_watch_today.fetch_baostock("2026-10-13", ["000001", "600519"])
        elapsed = time.monotonic() - started
    finally:
        signal.alarm(0)
    assert rows == []
    assert elapsed < 3.0, elapsed


def test_export_query_fails_fast_and_local_bars_win(blackhole, tmp_path, monkeypatch) -> None:
    import json
    import sqlite3

    import export_watch_calendar as exp

    details = tmp_path / "details"
    details.mkdir()
    (details / "000001.json").write_text(
        json.dumps(
            {
                "price_basis": "不复权",
                "ohlcv_60d": [
                    {
                        "date": "2026-10-10",
                        "open": 9.5,
                        "high": 9.8,
                        "low": 9.4,
                        "close": 9.6,
                        "volume": 100,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    spot = tmp_path / "watch_spot_opens.json"
    spot.write_text(
        json.dumps(
            {
                "date": "2026-10-13",
                "price_basis": "不复权",
                "opens": {"000001": {"open": 10.25, "prev_close": 9.6}},
            }
        ),
        encoding="utf-8",
    )
    db = tmp_path / "sequoia_v2.db"
    with sqlite3.connect(db) as conn:
        conn.execute(
            """
            CREATE TABLE stock_daily (
                symbol TEXT, date TEXT, open REAL, high REAL, low REAL,
                close REAL, volume REAL, turnover REAL
            )
            """
        )
        # Raw spot row sync_watch_today writes when WATCH_WRITE_STOCK_DAILY=1.
        conn.execute(
            "INSERT INTO stock_daily VALUES "
            "('600519','2026-10-13', 1400.0, NULL, NULL, NULL, NULL, NULL)"
        )
        # Full bar — 后复权, must not be treated as a raw open.
        conn.execute(
            "INSERT INTO stock_daily VALUES ('000001','2026-10-13', 50.0, 51, 49, 50.5, 10, 1)"
        )
    monkeypatch.setattr(exp, "DETAILS_DIR", details)
    monkeypatch.setattr(exp, "SPOT_PATH", spot)
    monkeypatch.setattr(exp, "DB_PATH", db)

    _arm_deadline()
    try:
        started = time.monotonic()
        remote, remote_ok = exp.load_bars_from_baostock("000001", "2026-10-13")
        elapsed = time.monotonic() - started
    finally:
        signal.alarm(0)
    assert remote == []
    assert remote_ok is False
    assert elapsed < 3.0, elapsed

    opens = exp.spot_open_map("2026-10-13")
    assert opens["000001"] == 10.25  # spot file beats the hfq-looking db row
    assert opens["600519"] == 1400.0  # open-only db row
    local = exp.local_raw_bars("000001", "2026-10-13", opens)
    chosen, source = exp.select_settle_bars(remote, remote_ok, local, "2026-10-13")
    assert source == "local"
    by_date = {bar["date"]: bar["open"] for bar in chosen}
    assert by_date["2026-10-10"] == 9.5
    assert by_date["2026-10-13"] == 10.25


def test_successful_baostock_rows_stay_authoritative(monkeypatch) -> None:
    import baostock as bs
    import export_watch_calendar as exp

    reset()

    class _Result:
        error_code = "0"
        error_msg = "success"
        fields = ["date", "open", "high", "low", "close", "volume"]

        def __init__(self) -> None:
            self._rows = [["2026-10-10", "11.5", "12", "11", "11.8", "1000"]]
            self._i = 0

        def next(self) -> bool:
            return self._i < len(self._rows)

        def get_row_data(self) -> list[str]:
            row = self._rows[self._i]
            self._i += 1
            return row

    monkeypatch.setattr(bs, "query_history_k_data_plus", lambda *_a, **_k: _Result())
    bars, ok = exp.load_bars_from_baostock("000001", "2026-10-13")
    assert ok is True
    assert bars[0]["open"] == 11.5
    local = [{"date": "2026-10-10", "open": 1.0}, {"date": "2026-10-09", "open": 1.0}]
    chosen, source = exp.select_settle_bars(bars, ok, local, "2026-10-13")
    assert source == "baostock"
    assert chosen[0]["open"] == 11.5
    # Successful empty reply is not a transport failure: do not prefer local.
    empty, empty_src = exp.select_settle_bars([], True, local, "2026-10-13")
    assert empty == [] and empty_src == "miss"


def test_scan_batch_returns_when_socket_is_silent(blackhole) -> None:
    from sequoia_x.data.engine import _bs_fetch_batch

    _arm_deadline()
    try:
        started = time.monotonic()
        rows = _bs_fetch_batch([("000001", "sz.000001", "2026-10-13", "2026-10-13")])
        elapsed = time.monotonic() - started
    finally:
        signal.alarm(0)
    assert rows == []
    assert elapsed < 3.0, elapsed
