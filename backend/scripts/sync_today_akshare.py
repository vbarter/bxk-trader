#!/usr/bin/env python3
"""Fill one day stock_daily via akshare hfq (matches baostock adjustflag=1)."""
from __future__ import annotations

import sqlite3
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import akshare as ak

DB = Path("/root/dev/Sequoia-X/data/sequoia_v2.db")
WORKERS = 16
MIN_OK = 4000


def fetch_symbol(symbol: str, day: str) -> tuple | None:
    s = day.replace("-", "")
    try:
        df = ak.stock_zh_a_hist(
            symbol=symbol,
            period="daily",
            start_date=s,
            end_date=s,
            adjust="hfq",
        )
    except Exception:
        return None
    if df is None or df.empty:
        return None
    r = df.iloc[0]
    try:
        d = str(r["日期"])[:10]
        if hasattr(r["日期"], "strftime"):
            d = r["日期"].strftime("%Y-%m-%d")
        open_ = float(r["开盘"])
        close = float(r["收盘"])
        high = float(r["最高"])
        low = float(r["最低"])
        vol = float(r["成交量"])
        amt = float(r["成交额"]) if r.get("成交额") == r.get("成交额") else None
        if vol <= 0 or close <= 0:
            return None
        return (symbol, d, open_, high, low, close, vol, amt)
    except Exception:
        return None


def main() -> int:
    day = sys.argv[1] if len(sys.argv) > 1 else time.strftime("%Y-%m-%d")
    with sqlite3.connect(DB) as conn:
        symbols = [r[0] for r in conn.execute("SELECT DISTINCT symbol FROM stock_daily ORDER BY 1")]
    print(f"[ak_today] {day} symbols={len(symbols)} workers={WORKERS}", flush=True)
    rows: list[tuple] = []
    fail = 0
    done = 0
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = {ex.submit(fetch_symbol, s, day): s for s in symbols}
        for fut in as_completed(futs):
            row = fut.result()
            done += 1
            if row is None:
                fail += 1
            else:
                rows.append(row)
            if done % 200 == 0:
                print(
                    f"  progress {done}/{len(symbols)} ok={len(rows)} fail={fail} "
                    f"{time.time()-t0:.0f}s",
                    flush=True,
                )
    print(f"[ak_today] fetched ok={len(rows)} fail={fail} in {time.time()-t0:.1f}s", flush=True)
    if len(rows) < MIN_OK:
        print(f"[ak_today] too few (<{MIN_OK}); abort", flush=True)
        return 1
    with sqlite3.connect(DB) as conn:
        conn.executemany(
            "INSERT INTO stock_daily (symbol, date, open, high, low, close, volume, turnover) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(symbol, date) DO UPDATE SET open=excluded.open, high=excluded.high, "
            "low=excluded.low, close=excluded.close, volume=excluded.volume, turnover=excluded.turnover",
            rows,
        )
        conn.commit()
        n = conn.execute("SELECT COUNT(*) FROM stock_daily WHERE date=?", (day,)).fetchone()[0]
        n_close = conn.execute(
            "SELECT COUNT(*) FROM stock_daily WHERE date=? AND close>0", (day,)
        ).fetchone()[0]
    print(f"[ak_today] wrote {n} rows close>0={n_close} for {day}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
