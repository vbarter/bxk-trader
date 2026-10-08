#!/usr/bin/env python3
"""Fill today OHLCV via Tencent fqkline — now **hfq**, rescaled to the DB hfq base.

2026-09-27: previously wrote 不复权 (raw) prices + date-wide DELETE, which mixed raw
bars into the hfq stock_daily history. Delegates to scripts/stock_daily_hfq.py
(per-symbol calibration against the last DB rows, idempotent per-row UPSERT).
Old version: sync_today_tencent.py.bak.pre_upsert_20260927
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import stock_daily_hfq  # noqa: E402

if __name__ == "__main__":
    today = date.today().isoformat()
    sys.exit(stock_daily_hfq.run([today], today, workers=4, dry_run=False, min_write=1000))
