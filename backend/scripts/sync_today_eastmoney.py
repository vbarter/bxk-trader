#!/usr/bin/env python3
"""Fill today's OHLCV via Eastmoney clist when baostock/tencent fail.

Spot prices are 不复权; used as coverage unblock + open overlay.
Prefer sync_today_tencent (fqkline) or akshare hfq when those work.
"""
from __future__ import annotations

import json
import sqlite3
import sys
import time
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "sequoia_v2.db"
TODAY = date.today().strftime("%Y-%m-%d")
MIN_ROWS = 4000

# A-share boards: SZ主板/创业板 + SH主板/科创板
FS = "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:13"
FIELDS = "f12,f14,f2,f3,f15,f16,f17,f18,f5,f6"


def fetch_page(pn: int, pz: int = 100) -> list[dict]:
    qs = urllib.parse.urlencode(
        {
            "pn": pn,
            "pz": pz,
            "po": 1,
            "np": 1,
            "fltt": 2,
            "invt": 2,
            "fid": "f12",
            "fs": FS,
            "fields": FIELDS,
        }
    )
    url = f"https://push2.eastmoney.com/api/qt/clist/get?{qs}"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://quote.eastmoney.com/",
        },
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    data = payload.get("data") or {}
    return list(data.get("diff") or []), int(data.get("total") or 0)


def to_row(item: dict) -> tuple | None:
    code = str(item.get("f12") or "").zfill(6)
    if not code.isdigit() or len(code) != 6:
        return None

    def num(v):
        if v in (None, "", "-"):
            return None
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    open_ = num(item.get("f17"))
    high = num(item.get("f15"))
    low = num(item.get("f16"))
    close = num(item.get("f2"))
    vol = num(item.get("f5"))
    amt = num(item.get("f6"))
    if close is None or close <= 0:
        return None
    if vol is not None and vol <= 0:
        return None
    # EM volume is 手; baostock/akshare hist often 股. Keep EM 手 for spot overlay
    # consistency with prior sync_watch_today spot path; strategies already ran.
    return (code, TODAY, open_, high, low, close, vol, amt)


def main() -> int:
    print(f"[sync_today_eastmoney] {TODAY}: fetching clist", flush=True)
    t0 = time.time()
    rows: list[tuple] = []
    seen: set[str] = set()
    pn = 1
    pz = 100
    total = None
    while True:
        try:
            page, total_n = fetch_page(pn, pz)
        except Exception as exc:
            print(f"[sync_today_eastmoney] page {pn} fail: {exc}", flush=True)
            if pn == 1:
                return 1
            break
        if total is None:
            total = total_n
            print(f"[sync_today_eastmoney] total reported={total}", flush=True)
        if not page:
            break
        for item in page:
            row = to_row(item)
            if row is None:
                continue
            if row[0] in seen:
                continue
            seen.add(row[0])
            rows.append(row)
        print(f"  page {pn} got={len(page)} cumulative_ok={len(rows)}", flush=True)
        if total is not None and pn * pz >= total:
            break
        if len(page) < pz:
            break
        pn += 1
        time.sleep(0.05)
    print(
        f"[sync_today_eastmoney] fetched ok={len(rows)} in {time.time()-t0:.1f}s",
        flush=True,
    )
    if len(rows) < MIN_ROWS:
        print(f"[sync_today_eastmoney] too few rows (<{MIN_ROWS}); abort", flush=True)
        return 1
    with sqlite3.connect(DB_PATH) as conn:
        conn.executemany(
            "INSERT INTO stock_daily (symbol, date, open, high, low, close, volume, turnover) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(symbol, date) DO UPDATE SET open=excluded.open, high=excluded.high, "
            "low=excluded.low, close=excluded.close, volume=excluded.volume, turnover=excluded.turnover",
            rows,
        )
        conn.commit()
        n = conn.execute(
            "SELECT COUNT(*) FROM stock_daily WHERE date = ?", (TODAY,)
        ).fetchone()[0]
        n_close = conn.execute(
            "SELECT COUNT(*) FROM stock_daily WHERE date = ? AND close IS NOT NULL AND close > 0",
            (TODAY,),
        ).fetchone()[0]
    print(
        f"[sync_today_eastmoney] wrote {n} rows for {TODAY} (close>0={n_close})",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
