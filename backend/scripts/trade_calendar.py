#!/usr/bin/env python3
"""Local A-share trading calendar (SSE/SZSE share the same calendar).

Source order:
  1. cache  data/trade_calendar.json  (exchange calendar from Sina, via akshare
     tool_trade_date_hist_sina; covers through the last published year-end)
  2. refresh from Sina (akshare) when the cache is missing, stale (>7d) or does
     not cover the requested date — result is written back to the cache
  3. baostock query_trade_dates — last, optional fallback (network/login may fail)

A date inside the covered range that is not listed is a non-trading day
(weekend or exchange holiday). Dates beyond the covered range return None
(unknown) unless baostock answers.

CLI:
  trade_calendar.py refresh            force refresh cache from Sina
  trade_calendar.py check [DATE ...]   print trading/non-trading + source
  trade_calendar.py next|prev DATE     next/previous trading day
"""

from __future__ import annotations

import json
import sys
from bisect import bisect_left, bisect_right
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CAL_PATH = ROOT / "data" / "trade_calendar.json"
KEEP_FROM = "2020-01-01"
STALE_DAYS = 7

_cache: dict | None = None


def _log(msg: str) -> None:
    print(f"[trade_calendar] {msg}", file=sys.stderr, flush=True)


def _norm(day: str | date) -> str:
    if isinstance(day, date):
        return day.isoformat()
    return str(day)[:10]


def _read_cache() -> dict | None:
    try:
        payload = json.loads(CAL_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    dates = payload.get("dates")
    if not isinstance(dates, list) or not dates:
        return None
    payload["dates"] = sorted({str(d)[:10] for d in dates})
    return payload


def _fetch_sina() -> list[str]:
    import akshare as ak  # hits finance.sina.com.cn klc_td_sh

    df = ak.tool_trade_date_hist_sina()
    return sorted({str(x)[:10] for x in df["trade_date"]})


def refresh(force: bool = True) -> dict | None:
    """Refresh cache from Sina. Keeps old cache if the fetch fails or looks wrong."""
    global _cache
    old = _read_cache()
    try:
        dates = _fetch_sina()
    except Exception as exc:  # noqa: BLE001
        _log(f"sina refresh failed: {exc}")
        return old
    dates = [d for d in dates if d >= KEEP_FROM]
    # sanity: ~240 trading days/year, must reach at least today's year
    this_year = str(date.today().year)
    n_year = sum(1 for d in dates if d.startswith(this_year))
    if n_year < 200:
        _log(f"sina refresh rejected: only {n_year} dates in {this_year}")
        return old
    payload = {
        "source": "sina (akshare tool_trade_date_hist_sina)",
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "covers_from": dates[0],
        "covers_through": f"{dates[-1][:4]}-12-31",
        "last_trade_date": dates[-1],
        "dates": dates,
    }
    CAL_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = CAL_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=0) + "\n", encoding="utf-8")
    tmp.replace(CAL_PATH)
    _cache = payload
    _log(f"refreshed from sina: {len(dates)} dates {dates[0]}..{dates[-1]}")
    return payload


def _is_stale(payload: dict) -> bool:
    try:
        fetched = datetime.fromisoformat(payload.get("fetched_at", ""))
    except ValueError:
        return True
    return datetime.now(timezone.utc) - fetched > timedelta(days=STALE_DAYS)


def load(need: str | None = None, allow_refresh: bool = True) -> dict | None:
    """Return calendar payload; refresh from Sina if missing/stale/not covering `need`."""
    global _cache
    if _cache is None:
        _cache = _read_cache()
    payload = _cache
    want_refresh = payload is None or _is_stale(payload)
    if need and payload is not None and need > payload.get("covers_through", ""):
        want_refresh = True
    if want_refresh and allow_refresh:
        fresh = refresh()
        if fresh is not None:
            payload = _cache = fresh
    return payload


def _via_baostock(day: str) -> bool | None:
    try:
        import baostock as bs
    except ImportError:
        return None
    try:
        lg = bs.login()
        if lg.error_code != "0":
            return None
        rs = bs.query_trade_dates(start_date=day, end_date=day)
        if rs.error_code != "0":
            return None
        while rs.next():
            row = rs.get_row_data()
            if len(row) >= 2 and str(row[0])[:10] == day:
                return str(row[1]).strip() == "1"
        return None
    except Exception:  # noqa: BLE001
        return None
    finally:
        try:
            bs.logout()
        except Exception:  # noqa: BLE001
            pass


def is_trading_day(day: str | date, allow_baostock: bool = True) -> tuple[bool | None, str]:
    d = _norm(day)
    payload = load(need=d)
    if payload is not None and payload["covers_from"] <= d <= payload["covers_through"]:
        dates = payload["dates"]
        i = bisect_left(dates, d)
        return (i < len(dates) and dates[i] == d), "local calendar (sina)"
    if allow_baostock:
        r = _via_baostock(d)
        if r is not None:
            return r, "baostock (fallback)"
    return None, "unknown"


def trading_days(start: str | date, end: str | date) -> list[str] | None:
    s, e = _norm(start), _norm(end)
    payload = load(need=e)
    if payload is None or s < payload["covers_from"]:
        return None
    dates = payload["dates"]
    out = dates[bisect_left(dates, s): bisect_right(dates, e)]
    if e > payload["covers_through"]:
        return None  # partially unknown
    return out


def next_trading_day(day: str | date) -> str | None:
    d = _norm(day)
    payload = load(need=d)
    if payload is None:
        return None
    dates = payload["dates"]
    i = bisect_right(dates, d)
    return dates[i] if i < len(dates) else None


def prev_trading_day(day: str | date) -> str | None:
    d = _norm(day)
    payload = load(need=d)
    if payload is None:
        return None
    dates = payload["dates"]
    i = bisect_left(dates, d)
    return dates[i - 1] if i > 0 else None


def main(argv: list[str]) -> int:
    cmd = argv[0] if argv else "check"
    if cmd == "refresh":
        return 0 if refresh() is not None else 1
    if cmd in ("next", "prev") and len(argv) > 1:
        fn = next_trading_day if cmd == "next" else prev_trading_day
        print(fn(argv[1]))
        return 0
    days = argv[1:] if cmd == "check" else argv
    for d in days or [date.today().isoformat()]:
        r, src = is_trading_day(d)
        label = "trading" if r else ("non-trading" if r is False else "unknown")
        print(f"{d} {label} via {src}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
