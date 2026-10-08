#!/usr/bin/env python3
"""Light probe: upsert today's bars for watch-calendar symbols into SQLite.

Used by settle-AM cron (open+5min) so:
  - buy opens for buy_date=today (yesterday's picks) are available
  - sell opens for sell_date=today (day-before-yesterday's picks) can settle

Open-only spot bars are enough for open→open settle (export uses sell_open).

Universe: unique codes from recent data/daily_picks/*.json (last ~10 files),
falling back to Theo Top5 when no picks files exist.

Prices: baostock adjustflag=3 不复权; Sina/EM spot stays raw (no 后复权 factor).
"""

from __future__ import annotations

import json
import sqlite3
import os
import sys
import urllib.request
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "sequoia_v2.db"
PICKS_DIR = ROOT / "data" / "daily_picks"
SPOT_PATH = ROOT / "data" / "watch_spot_opens.json"

THEO_TOP5 = ["000626", "301072", "000700", "002868", "605088"]
# Same probe symbols as export_watch_calendar — needed so AM spot sync
# can put *today* on the trading calendar when baostock lags.
CALENDAR_PROBE = ["000001", "600519", "000002"]
ADJUST_FLAG = "3"  # 不复权
# stock_daily is 后复权 (hfq, DB scale) since 2026-09-27; settle reads raw opens
# from watch_spot_opens.json / baostock / tencent — never from stock_daily.
# Writing raw bars here would mix conventions, so it is off unless forced.
WRITE_STOCK_DAILY = os.environ.get("WATCH_WRITE_STOCK_DAILY", "0") == "1"


def _model_dirs() -> list[Path]:
    """gpt = PICKS_DIR (legacy); other models under PICKS_DIR/<key>/ (2026-09-29+)."""
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from pick_models import all_archive_dirs, all_picks_dirs

        # Archived live batches still get bought/sold at the open (e.g. real 09-24 gpt batch).
        dirs = [*all_picks_dirs(PICKS_DIR).values(), *all_archive_dirs(PICKS_DIR).values()]
        return [d for d in dirs if d.exists()]
    except Exception:  # noqa: BLE001
        return [PICKS_DIR]


def load_watch_codes() -> list[str]:
    codes: list[str] = []
    if PICKS_DIR.exists():
        # Only R-2 (sell today) and R-1 (buy today) matter at 09:35, by the
        # exchange calendar. A paused day's file has no symbols -> nothing bought.
        # multi_hit (_shadow/) is never included.
        paths = []
        try:
            import trade_calendar  # scripts/trade_calendar.py

            today = date.today().isoformat()
            r1 = trade_calendar.prev_trading_day(today)
            r2 = trade_calendar.prev_trading_day(r1) if r1 else None
            if r1 and r2:
                # Every model's batches (gpt legacy dir + daily_picks/<model>/).
                paths = [pdir / f"{d}.json" for pdir in _model_dirs() for d in (r2, r1)]
                paths = [p for p in paths if p.exists()]
            else:
                raise RuntimeError("calendar gap")
        except Exception as exc:  # noqa: BLE001
            print(f"[warn] trade calendar unavailable ({exc}); using 2 latest picks files per model", file=sys.stderr)
            paths = [p for pdir in _model_dirs() for p in sorted(pdir.glob("*.json"))[-2:]]
        for path in paths:
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if payload.get("paused") or payload.get("pick_status") == "paused":
                print(f"[sync_watch_today] {path.stem}: pick paused -> nothing to buy/sell", flush=True)
                continue
            for item in payload.get("symbols") or []:
                if isinstance(item, str):
                    code = item.zfill(6)
                elif isinstance(item, dict):
                    code = str(item.get("code") or "").zfill(6)
                else:
                    continue
                if code.isdigit() and len(code) == 6 and code not in codes:
                    codes.append(code)
    for code in CALENDAR_PROBE:
        if code not in codes:
            codes.append(code)
    return codes


def to_bs_code(symbol: str) -> str:
    prefix = "sh" if symbol.startswith(("6", "9")) else "sz"
    return f"{prefix}.{symbol}"


def to_sina_code(symbol: str) -> str:
    return ("sh" if symbol.startswith(("6", "9")) else "sz") + symbol


def to_em_secid(symbol: str) -> str:
    mkt = "1" if symbol.startswith(("6", "9")) else "0"
    return f"{mkt}.{symbol}"


def ensure_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS stock_daily (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol   TEXT    NOT NULL,
            date     TEXT    NOT NULL,
            open     REAL,
            high     REAL,
            low      REAL,
            close    REAL,
            volume   REAL,
            turnover REAL,
            UNIQUE (symbol, date)
        )
        """
    )


def upsert_bar(
    conn: sqlite3.Connection,
    code: str,
    day: str,
    open_: float | None,
    high: float | None,
    low: float | None,
    close: float | None,
    volume: float | None = None,
    turnover: float | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO stock_daily (symbol, date, open, high, low, close, volume, turnover)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(symbol, date) DO UPDATE SET
            open=excluded.open,
            high=excluded.high,
            low=excluded.low,
            close=excluded.close,
            volume=COALESCE(excluded.volume, stock_daily.volume),
            turnover=COALESCE(excluded.turnover, stock_daily.turnover)
        """,
        (code, day, open_, high, low, close, volume, turnover),
    )


def fetch_baostock(day: str, codes: list[str]) -> list[tuple]:
    import baostock as bs

    lg = bs.login()
    if lg.error_code != "0":
        print(f"[warn] baostock login failed: {lg.error_msg}", file=sys.stderr)
        return []
    rows: list[tuple] = []
    try:
        for code in codes:
            rs = bs.query_history_k_data_plus(
                to_bs_code(code),
                "date,open,high,low,close,volume,amount",
                start_date=day,
                end_date=day,
                frequency="d",
                adjustflag=ADJUST_FLAG,
            )
            if rs.error_code != "0":
                print(f"[warn] {code}: baostock query failed {rs.error_msg}", file=sys.stderr)
                continue
            while rs.next():
                data = rs.get_row_data()
                rows.append((code, *data))
    finally:
        bs.logout()
    return rows


def fetch_spot_opens(codes: list[str]) -> dict[str, tuple[float, float]]:
    """Return {code: (open, prev_close)} from Eastmoney, fallback Sina — raw 不复权."""
    out: dict[str, tuple[float, float]] = {}
    if not codes:
        return out
    # Tencent qt first (raw 不复权 open/prev_close; reachable from this box when
    # EM push2 502s and Sina 403s). Only accept quotes stamped today.
    today = date.today().strftime("%Y%m%d")
    for i in range(0, len(codes), 60):
        chunk = codes[i : i + 60]
        q = ",".join(to_sina_code(c) for c in chunk)
        try:
            req = urllib.request.Request(
                f"https://qt.gtimg.cn/q={q}", headers={"User-Agent": "Mozilla/5.0"}
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                raw = resp.read().decode("gbk", errors="replace")
            for line in raw.split(";"):
                if '="' not in line:
                    continue
                f = line.split('="', 1)[1].split("~")
                if len(f) < 31 or f[2] not in chunk or not f[30].startswith(today):
                    continue
                try:
                    open_, prev = float(f[5]), float(f[4])
                except ValueError:
                    continue
                if open_ > 0 and prev > 0:
                    out[f[2]] = (open_, prev)
        except Exception as exc:  # noqa: BLE001
            print(f"[warn] tencent qt spot failed: {exc}", file=sys.stderr)
    codes = [c for c in codes if c not in out]
    if not codes:
        return out
    secids = ",".join(to_em_secid(c) for c in codes)
    em_url = (
        "https://push2.eastmoney.com/api/qt/ulist.np/get"
        f"?fltt=2&fields=f12,f14,f17,f15,f16,f2,f18&secids={secids}"
    )
    req = urllib.request.Request(
        em_url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://quote.eastmoney.com/",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        for item in (payload.get("data") or {}).get("diff") or []:
            code = str(item.get("f12", "")).zfill(6)
            open_ = item.get("f17")
            prev = item.get("f18")
            if code in codes and open_ not in (None, "-", "") and prev not in (None, "-", "", 0):
                if float(open_) > 0:  # 0 = suspended / not opened: leave missing
                    out[code] = (float(open_), float(prev))
    except Exception as exc:
        print(f"[warn] eastmoney spot failed: {exc}", file=sys.stderr)

    missing = [c for c in codes if c not in out]
    if not missing:
        return out

    sina_list = ",".join(to_sina_code(c) for c in missing)
    sina_url = f"https://hq.sinajs.cn/list={sina_list}"
    req = urllib.request.Request(
        sina_url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://finance.sina.com.cn",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode("gbk", errors="replace")
        for line in raw.splitlines():
            if '="' not in line:
                continue
            left, right = line.split('="', 1)
            code = left[-6:]
            fields = right.rstrip('";').split(",")
            if len(fields) < 3 or code not in codes:
                continue
            # only today's quote; never a stale one
            if len(fields) > 30 and fields[30] and fields[30] != date.today().isoformat():
                continue
            try:
                open_ = float(fields[1])
                prev = float(fields[2])
            except ValueError:
                continue
            if prev == 0 or open_ <= 0:  # no real open -> leave missing (pending)
                continue
            out[code] = (open_, prev)
    except Exception as exc:
        print(f"[warn] sina spot failed: {exc}", file=sys.stderr)
    return out


def _num(x: object) -> float | None:
    if x in ("", None):
        return None
    try:
        return float(x)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def apply_baostock_rows(conn: sqlite3.Connection, rows: list[tuple]) -> int:
    n = 0
    for code, d, o, h, l, c, v, amt in rows:
        upsert_bar(
            conn,
            code,
            str(d)[:10],
            _num(o),
            _num(h),
            _num(l),
            _num(c),
            _num(v),
            _num(amt),
        )
        n += 1
    return n


def apply_spot_raw(
    conn: sqlite3.Connection, day: str, spot: dict[str, tuple[float, float]]
) -> int:
    """Write raw Sina/EM opens as-is (不复权). Do not scale by 后复权 factor."""
    n = 0
    snapshot: dict[str, dict[str, float]] = {}
    for code, (spot_open, spot_prev) in spot.items():
        if WRITE_STOCK_DAILY:
            upsert_bar(conn, code, day, spot_open, None, None, None)
        snapshot[code] = {"open": spot_open, "prev_close": spot_prev}
        n += 1
        print(
            f"[sync_watch_today] {code}: raw spot open={spot_open} prev={spot_prev} "
            f"(不复权, no factor)",
            flush=True,
        )
    write_spot_snapshot(day, {c: (v["open"], v["prev_close"]) for c, v in snapshot.items()})
    return n


def write_spot_snapshot(day: str, spot: dict) -> None:
    snapshot = {c: {"open": o, "prev_close": p} for c, (o, p) in spot.items()}
    SPOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    SPOT_PATH.write_text(
        json.dumps(
            {"date": day, "price_basis": "不复权", "opens": snapshot},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def main() -> int:
    day = date.today().strftime("%Y-%m-%d")
    codes = load_watch_codes()
    print(f"[sync_watch_today] universe={codes} adjustflag={ADJUST_FLAG}", flush=True)
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    rows = fetch_baostock(day, codes)
    with sqlite3.connect(DB_PATH) as conn:
        ensure_table(conn)
        if rows:
            if WRITE_STOCK_DAILY:
                n = apply_baostock_rows(conn, rows)
                conn.commit()
            # Always record raw opens in the spot snapshot (what settle reads).
            snap = {}
            for code, d, o, h, l, c, v, amt in rows:
                if str(d)[:10] == day and _num(o) is not None:
                    snap[code] = (_num(o), None)
            if snap:
                write_spot_snapshot(day, snap)
            print(f"[sync_watch_today] {day}: {len(rows)} baostock 不复权 bars "
                  f"(stock_daily write={'on' if WRITE_STOCK_DAILY else 'off'})", flush=True)
            return 0

        print(f"[sync_watch_today] {day}: baostock empty -> spot open fallback (raw)", flush=True)
        spot = fetch_spot_opens(codes)
        if not spot:
            print(f"[sync_watch_today] {day}: no bars from baostock or spot", flush=True)
            return 2
        n = apply_spot_raw(conn, day, spot)
        conn.commit()
        if n == 0:
            print(f"[sync_watch_today] {day}: spot fetched but none written", flush=True)
            return 2
        print(f"[sync_watch_today] {day}: upserted {n} raw spot opens", flush=True)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
