#!/usr/bin/env python3
"""Exit 0 if DATE (default: today, local) is an A-share trading day, else 1.

Order: local exchange calendar data/trade_calendar.json (Sina via akshare,
auto-refreshed when stale / not covering DATE) → baostock query_trade_dates
(optional last fallback) → weekday heuristic is NOT used; if everything fails
we fall back to the old SQLite probe (a bar for DATE already in stock_daily),
else treat as non-trading so cron jobs skip safely.

Usage: is_trading_day.py [YYYY-MM-DD]   (date arg is for dry-runs)
"""

from __future__ import annotations

import sqlite3
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "sequoia_v2.db"
sys.path.insert(0, str(Path(__file__).resolve().parent))

import trade_calendar  # noqa: E402


def via_db_probe(day: str) -> bool | None:
    if not DB_PATH.exists():
        return None
    try:
        with sqlite3.connect(DB_PATH) as conn:
            row = conn.execute(
                "SELECT 1 FROM stock_daily WHERE date = ? LIMIT 1",
                (day,),
            ).fetchone()
        return bool(row)
    except sqlite3.Error:
        return None


def main(argv: list[str]) -> int:
    day = argv[0][:10] if argv else date.today().strftime("%Y-%m-%d")
    result, source = trade_calendar.is_trading_day(day)
    if result is None:
        result = via_db_probe(day)
        source = "db_probe"
    if result is None:
        print(f"[is_trading_day] {day}: unknown (calendar/API/DB failed) → skip", flush=True)
        return 1
    label = "trading" if result else "non-trading"
    print(f"[is_trading_day] {day}: {label} via {source}", flush=True)
    return 0 if result else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
