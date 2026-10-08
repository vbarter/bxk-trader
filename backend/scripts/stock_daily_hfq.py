#!/usr/bin/env python3
"""Fill stock_daily from Tencent fqkline **hfq**, rescaled to this DB's own hfq base.

Why: baostock (the canonical hfq source, adjustflag=1) is blacklisted on this host
(10001011). Tencent hfq uses a different base for some symbols (e.g. 600519 DB/Tencent
≈0.892), so we calibrate per symbol against the symbol's last DB rows (anchors):

    k_sym   = median(db_close / tencent_hfq_close)  over anchor dates
    vol_sym = 10^round(log10(median(db_volume / tencent_volume)))   (DB volume unit = 手)
    row     = tencent_hfq_{open,high,low,close} * k_sym,  volume * vol_sym
    turnover (成交额, 元) = exact from Tencent qt for the latest day, else
                            volume_shares * raw typical price (estimate)

Symbols with no DB history before the target (new listings) use k=1 (hfq == raw
until the first dividend, same as baostock).

Writes are idempotent per-(symbol,date) UPSERTs — never a date-wide DELETE.

CLI:
  scripts/stock_daily_hfq.py --dates 2026-09-21,2026-09-22 [--anchor-before 2026-09-18] [--dry-run]
  scripts/stock_daily_hfq.py --today            # close_pm fallback for today's bars
"""
from __future__ import annotations

import argparse
import json
import math
import sqlite3
import statistics
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "sequoia_v2.db"
UA = {"User-Agent": "Mozilla/5.0"}
# web.ifzq.gtimg.cn WAF-blocks bulk pulls (501 after ~3k req); rotate over equivalent hosts.
HOSTS = [
    "https://proxy.finance.qq.com/ifzqgtimg/appstock/app/newfqkline/get",
    "https://ifzq.gtimg.cn/appstock/app/fqkline/get",
]
_HOST_I = 0
N_ANCHORS = 3
K_SPREAD_WARN = 0.003  # 0.3%


def log(msg: str) -> None:
    print(f"[stock_daily_hfq] {msg}", flush=True)


def tencent_symbol(code: str) -> str:
    if code.startswith(("92", "4", "8")):
        return "bj" + code
    if code.startswith(("6", "9")):
        return "sh" + code
    return "sz" + code


def _get(url: str, timeout: float = 12.0) -> dict:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_symbol(code: str, start: str, end: str) -> dict | None:
    """One request per symbol: {'hfq': {date: [o,c,h,l,vol]}, 'qt': [date, raw_price, amount] | None}."""
    sym = tencent_symbol(code)
    n = (date.fromisoformat(end) - date.fromisoformat(start)).days + 5
    global _HOST_I
    _HOST_I += 1
    host = HOSTS[_HOST_I % len(HOSTS)]
    payload = _get(f"{host}?param={sym},day,{start},{end},{n},hfq")
    node = (payload.get("data") or {}).get(sym) or {}
    out: dict = {"hfq": {}, "qt": None}
    for r in node.get("hfqday") or node.get("day") or []:
        try:
            amt = None
            if len(r) > 8 and r[8] not in ("", None):
                try:
                    amt = float(r[8]) * 1e4  # newfqkline: 成交额 in 万元
                except (TypeError, ValueError):
                    amt = None
            out["hfq"][str(r[0])[:10]] = [float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5]), amt]
        except (TypeError, ValueError, IndexError):
            continue
    qt = (node.get("qt") or {}).get(sym)
    if isinstance(qt, list) and len(qt) > 35:
        try:
            dt = str(qt[30])[:8]
            out["qt"] = [f"{dt[:4]}-{dt[4:6]}-{dt[6:8]}", float(qt[3]), float(str(qt[35]).split("/")[2])]
        except (ValueError, IndexError):
            pass
    return out if out["hfq"] else None


def load_cache(path: str | None, start: str, end: str) -> dict[str, dict]:
    if not path or not Path(path).is_file():
        return {}
    obj = json.loads(Path(path).read_text(encoding="utf-8"))
    if obj.get("start") != start or obj.get("end") != end:
        log(f"cache {path} range {obj.get('start')}..{obj.get('end')} != {start}..{end}; ignoring")
        return {}
    return obj.get("data") or {}


def save_cache(path: str | None, start: str, end: str, got: dict) -> None:
    if not path:
        return
    tmp = Path(path + ".tmp")
    tmp.write_text(json.dumps({"start": start, "end": end, "data": got}, separators=(",", ":")), encoding="utf-8")
    tmp.replace(path)


def fetch_all(codes: list[str], start: str, end: str, workers: int, rounds: int = 5,
              cache: str | None = None, pause: float = 0.15) -> dict[str, dict]:
    got: dict[str, dict] = load_cache(cache, start, end)
    if got:
        log(f"cache hit {len(got)} symbols")
    remaining = [c for c in codes if c not in got]
    w = workers
    for rnd in range(1, rounds + 1):
        if not remaining:
            break
        log(f"round {rnd}/{rounds}: n={len(remaining)} workers={w}")
        failed: list[str] = []
        t0 = time.time()
        with ThreadPoolExecutor(max_workers=w) as ex:
            futs = {ex.submit(_safe_fetch, c, start, end, pause): c for c in remaining}
            for i, fut in enumerate(as_completed(futs), 1):
                c = futs[fut]
                res = fut.result()
                if res is None:
                    failed.append(c)
                else:
                    got[c] = res
                if i % 250 == 0:
                    save_cache(cache, start, end, got)
                if i % 500 == 0:
                    log(f"  progress {i}/{len(remaining)} ok={len(got)} fail={len(failed)} {time.time()-t0:.0f}s")
        log(f"round {rnd} ok_total={len(got)} fail={len(failed)} in {time.time()-t0:.0f}s")
        save_cache(cache, start, end, got)
        if len(failed) == len(remaining) and len(remaining) > 20:
            log("whole round failed (likely WAF rate-limit); stop retrying")
            break
        remaining = failed
        if remaining:
            w = max(1, w // 2)
            time.sleep(3.0 * rnd)
    return got


def _safe_fetch(code: str, start: str, end: str, pause: float = 0.15) -> dict | None:
    try:
        time.sleep(pause)
        return fetch_symbol(code, start, end)
    except Exception:
        return None


def load_anchors(conn: sqlite3.Connection, codes: list[str], before: str) -> dict[str, list[tuple]]:
    out: dict[str, list[tuple]] = {}
    for c in codes:
        rows = conn.execute(
            "SELECT date, close, volume FROM stock_daily WHERE symbol=? AND date<? AND close>0 "
            "ORDER BY date DESC LIMIT ?", (c, before, N_ANCHORS)).fetchall()
        out[c] = rows
    return out


def calibrate(code: str, anchors: list[tuple], hfq: dict) -> tuple[float, float, str]:
    ks, vs = [], []
    for d, close, vol in anchors:
        t = hfq.get(d)
        if not t or t[1] <= 0:
            continue
        ks.append(close / t[1])
        if vol and t[4] > 0:
            vs.append(vol / t[4])
    default_v = 0.01 if code.startswith(("688", "689")) else 1.0
    if not ks:
        return 1.0, default_v, "no_anchor"
    k = statistics.median(ks)
    spread = (max(ks) - min(ks)) / k if k else 0
    v = default_v
    if vs:
        v = 10 ** round(math.log10(statistics.median(vs)))
    return k, v, ("ok" if spread <= K_SPREAD_WARN else f"spread={spread:.4f}")


def build_rows(code: str, data: dict, k: float, vmul: float, dates: list[str]) -> list[tuple]:
    rows = []
    qt = data.get("qt")
    # raw/hfq factor from the live quote (valid back to the last ex-dividend date)
    raw_per_hfq = None
    if qt and data["hfq"].get(qt[0]) and data["hfq"][qt[0]][1] > 0 and qt[1] > 0:
        raw_per_hfq = qt[1] / data["hfq"][qt[0]][1]
    for d in dates:
        t = data["hfq"].get(d)
        if not t:
            continue
        o, c, h, l, vol = t[:5]
        amt_k = t[5] if len(t) > 5 else None
        if vol <= 0 or c <= 0:
            continue
        shares = vol * (1 if code.startswith(("688", "689")) else 100)  # tencent: 手, STAR: 股
        if qt and qt[0] == d:
            amount = qt[2]
        elif amt_k:
            amount = amt_k
        elif raw_per_hfq:
            amount = shares * (o + c + h + l) / 4.0 * raw_per_hfq  # estimate
        else:
            amount = None
        rows.append((code, d, round(o * k, 6), round(h * k, 6), round(l * k, 6), round(c * k, 6),
                     round(vol * vmul, 2), round(amount, 2) if amount else None))
    return rows


def upsert(conn: sqlite3.Connection, rows: list[tuple]) -> None:
    conn.executemany(
        "INSERT INTO stock_daily (symbol, date, open, high, low, close, volume, turnover) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(symbol, date) DO UPDATE SET open=excluded.open, high=excluded.high, "
        "low=excluded.low, close=excluded.close, volume=excluded.volume, turnover=excluded.turnover",
        rows)


def run(dates: list[str], anchor_before: str, workers: int, dry_run: bool, min_write: int,
        cache: str | None = None) -> int:
    dates = sorted(dates)
    with sqlite3.connect(DB_PATH) as conn:
        codes = [r[0] for r in conn.execute(
            "SELECT DISTINCT symbol FROM stock_daily WHERE date >= date(?, '-40 day') ORDER BY 1", (anchor_before,))]
        anchors = load_anchors(conn, codes, anchor_before)
    first_anchor = min((a[-1][0] for a in anchors.values() if a), default=dates[0])
    start, end = min(first_anchor, dates[0]), dates[-1]
    log(f"dates={dates} anchor_before={anchor_before} symbols={len(codes)} fetch={start}..{end}")
    got = fetch_all(codes, start, end, workers, cache=cache)
    all_rows: list[tuple] = []
    stats = {"ok": 0, "no_anchor": 0, "spread": 0, "nofetch": len(codes) - len(got)}
    spreads = []
    for c in codes:
        data = got.get(c)
        if not data:
            continue
        k, vmul, status = calibrate(c, anchors.get(c) or [], data["hfq"])
        if status == "ok":
            stats["ok"] += 1
        elif status == "no_anchor":
            stats["no_anchor"] += 1
        else:
            stats["spread"] += 1
            spreads.append((c, status))
        all_rows.extend(build_rows(c, data, k, vmul, dates))
    per_day = {d: sum(1 for r in all_rows if r[1] == d) for d in dates}
    log(f"calibration {stats}; rows per day {per_day}")
    if spreads:
        log(f"k spread > {K_SPREAD_WARN:.1%} (anchors disagree, median used): {spreads[:15]}{' …' if len(spreads) > 15 else ''}")
    low = [d for d, n in per_day.items() if n < min_write]
    if low:
        log(f"too few rows for {low} (< {min_write}); abort write for those days")
        all_rows = [r for r in all_rows if r[1] not in low]
    if dry_run:
        log("dry-run: no write")
        return 0 if not low else 1
    with sqlite3.connect(DB_PATH) as conn:
        upsert(conn, all_rows)
        conn.commit()
        for d in dates:
            n = conn.execute("SELECT COUNT(*) FROM stock_daily WHERE date=?", (d,)).fetchone()[0]
            log(f"{d}: stock_daily rows now {n}")
    return 0 if not low else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dates", help="comma-separated YYYY-MM-DD")
    ap.add_argument("--today", action="store_true", help="fill today's bars (close_pm fallback)")
    ap.add_argument("--anchor-before", help="calibrate on the last DB rows strictly before this date "
                                            "(default: earliest target date)")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--min-write", type=int, default=1000)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--cache", help="JSON cache of fetched symbols (resume / fetch elsewhere)")
    ap.add_argument("--fetch-only", action="store_true", help="only fetch into --cache (no DB); needs --codes-file --start --end")
    ap.add_argument("--codes-file")
    ap.add_argument("--start")
    ap.add_argument("--end")
    a = ap.parse_args()
    if a.fetch_only:
        codes = [x.strip() for x in Path(a.codes_file).read_text().split() if x.strip()]
        got = fetch_all(codes, a.start, a.end, a.workers, cache=a.cache)
        log(f"fetch-only: {len(got)}/{len(codes)} cached in {a.cache}")
        return 0 if len(got) >= len(codes) * 0.95 else 1
    if a.today:
        dates = [date.today().isoformat()]
    elif a.dates:
        dates = [d.strip() for d in a.dates.split(",") if d.strip()]
    else:
        ap.error("--dates or --today required")
    return run(dates, a.anchor_before or min(dates), a.workers, a.dry_run, a.min_write, cache=a.cache)


if __name__ == "__main__":
    sys.exit(main())
