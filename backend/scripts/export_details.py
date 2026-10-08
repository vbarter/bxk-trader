#!/usr/bin/env python3
"""Export per-symbol stock details from SQLite metadata and Baostock 不复权 bars."""

from __future__ import annotations

import csv
import json
import math
import os
import sqlite3
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import baostock as bs
import urllib.request


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
LATEST_PATH = DATA_DIR / "latest.json"
DETAILS_DIR = DATA_DIR / "details"
DB_PATH = DATA_DIR / "sequoia_v2.db"
SW_INDUSTRY_MAP_PATH = DATA_DIR / "sw_industry_map.csv"
REPORT_ATTEMPTS = 12
# Display / quotes / K-line use baostock 不复权 (raw) prices.
ADJUST_FLAG = "3"
OHLCV_LOOKBACK_DAYS = 120


def warn(message: str) -> None:
    print(f"[warn] {message}", file=sys.stderr, flush=True)


def nullable_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def nullable_number(value: Any) -> float | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def infer_market(symbol: str) -> str:
    if symbol.startswith(("4", "8", "92")):
        return "BJ"
    if symbol.startswith(("5", "6", "9")):
        return "SH"
    return "SZ"


def derive_board(symbol: str, market: str) -> str:
    if symbol.startswith("688"):
        return "科创板"
    if symbol.startswith(("300", "301")):
        return "创业板"
    if symbol.startswith(("8", "4")) or market == "BJ":
        return "北交所"
    if symbol.startswith("60"):
        return "沪市主板"
    if market == "SZ":
        return "深市主板"
    return "其他"


def baostock_code(symbol: str, market: str) -> str:
    return f"{market.lower()}.{symbol}"


def load_sw_industry_map(path: Path = SW_INDUSTRY_MAP_PATH) -> dict[str, dict[str, str]]:
    """Load Shenwan map: symbol -> {sw_l1, sw_l1_code, sw_l2, sw_l2_code, industry_group, name}."""
    if not path.is_file():
        warn(f"SW industry map missing: {path}")
        return {}
    mapping: dict[str, dict[str, str]] = {}
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            symbol = (row.get("symbol") or "").strip().zfill(6)
            if len(symbol) != 6:
                continue
            mapping[symbol] = {
                "sw_l1": (row.get("sw_l1_name") or "").strip(),
                "sw_l1_code": (row.get("sw_l1_code") or "").strip(),
                "sw_l2": (row.get("sw_l2_name") or "").strip(),
                "sw_l2_code": (row.get("sw_l2_code") or "").strip(),
                "industry_group": (row.get("industry_group") or "").strip() or "未分类",
                "name": (row.get("name") or "").strip(),
            }
    return mapping


def sw_meta_fields(symbol: str, sw_map: dict[str, dict[str, str]]) -> dict[str, str | None]:
    hit = sw_map.get(symbol)
    if not hit:
        return {
            "sw_l1": "未分类",
            "sw_l1_code": None,
            "sw_l2": None,
            "sw_l2_code": None,
            "industry_group": "未分类",
        }
    return {
        "sw_l1": hit["sw_l1"] or "未分类",
        "sw_l1_code": hit["sw_l1_code"] or None,
        "sw_l2": hit["sw_l2"] or None,
        "sw_l2_code": hit["sw_l2_code"] or None,
        "industry_group": hit["industry_group"] or "未分类",
    }


def compose_meta(
    symbol: str,
    *,
    industry: str | None,
    board: str,
    sw_map: dict[str, dict[str, str]],
) -> dict[str, str | None]:
    meta: dict[str, str | None] = {
        "industry": industry,  # baostock national industry — keep as fallback display
        "board": board,
    }
    meta.update(sw_meta_fields(symbol, sw_map))
    return meta



def result_rows(result: Any, label: str) -> list[dict[str, str]]:
    if result.error_code != "0":
        warn(f"{label}: {result.error_code} {result.error_msg}")
        return []
    rows: list[dict[str, str]] = []
    while result.next():
        rows.append(dict(zip(result.fields, result.get_row_data())))
    return rows


def load_bars_unadj(remote_code: str, symbol: str) -> list[dict[str, Any]]:
    """Fetch recent daily OHLCV with adjustflag=3 (不复权 / raw)."""
    end = date.today()
    start = end - timedelta(days=OHLCV_LOOKBACK_DAYS)
    rows = result_rows(
        bs.query_history_k_data_plus(
            remote_code,
            "date,open,high,low,close,volume",
            start_date=start.isoformat(),
            end_date=end.isoformat(),
            frequency="d",
            adjustflag=ADJUST_FLAG,
        ),
        f"{remote_code} ohlcv unadj",
    )
    bars: list[dict[str, Any]] = []
    for row in rows:
        close = nullable_number(row.get("close"))
        open_ = nullable_number(row.get("open"))
        if close is None and open_ is None:
            continue
        bars.append(
            {
                "date": str(row.get("date", ""))[:10],
                "open": open_,
                "high": nullable_number(row.get("high")),
                "low": nullable_number(row.get("low")),
                "close": close,
                "volume": nullable_number(row.get("volume")),
            }
        )
    bars.sort(key=lambda bar: bar["date"])
    if len(bars) > 60:
        bars = bars[-60:]
    if not bars:
        warn(f"{symbol}: no 不复权 bars from baostock")
    return bars


SIGDAY_BAR_SRC = "tencent_qt"


def signal_day_today() -> str | None:
    """Today (Asia/Shanghai box clock) if it is an exchange trading day."""
    today = date.today().isoformat()
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import trade_calendar  # scripts/trade_calendar.py (local Sina calendar)

        ok, _src = trade_calendar.is_trading_day(today, allow_baostock=False)
        return today if ok else None
    except Exception as exc:  # noqa: BLE001
        warn(f"trade calendar unavailable ({exc}); assume {today} is a trading day")
        return today


def fetch_signal_day_bars(symbols: list[str], day: str) -> dict[str, dict[str, Any]]:
    """Raw (不复权) signal-day OHLCV from Tencent qt, stamped `day`.

    baostock publishes day R only in the evening, so at close_pm (15:05) its
    history ends at R-1. The picker needs R. Fields: 3=price(close after 15:00),
    5=open, 33=high, 34=low, 6=volume (手 -> x100 股 to match baostock; STAR 688/689 already 股), 30=timestamp.
    Suspended (open<=0) or not-stamped-today quotes are skipped. Bars carry
    src=tencent_qt so settlement code never uses them (real opens only).
    """
    out: dict[str, dict[str, Any]] = {}
    stamp = day.replace("-", "")
    for i in range(0, len(symbols), 60):
        chunk = symbols[i : i + 60]
        q = ",".join(("sh" if c.startswith(("6", "9")) else ("bj" if c.startswith(("4", "8")) else "sz")) + c for c in chunk)
        try:
            req = urllib.request.Request(f"https://qt.gtimg.cn/q={q}", headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                raw = resp.read().decode("gbk", errors="replace")
        except Exception as exc:  # noqa: BLE001
            warn(f"tencent qt signal-day chunk failed: {exc}")
            continue
        for line in raw.split(";"):
            if '="' not in line:
                continue
            f = line.split('="', 1)[1].split("~")
            if len(f) < 37 or f[2] not in chunk or not f[30].startswith(stamp):
                continue
            try:
                close, open_ = float(f[3]), float(f[5])
                high, low, vol_lots = float(f[33]), float(f[34]), float(f[6])
            except ValueError:
                continue
            if open_ <= 0 or close <= 0:
                continue
            out[f[2]] = {
                "date": day,
                "open": open_,
                "high": high,
                "low": low,
                "close": close,
                # qt field 6 is 手 (x100 股) except STAR (688/689), already 股.
                "volume": vol_lots if f[2].startswith(("688", "689")) else vol_lots * 100.0,
                "src": SIGDAY_BAR_SRC,
            }
    return out


def load_bars_from_db(connection: sqlite3.Connection, symbol: str) -> list[dict[str, Any]]:
    """Fallback only — stock_daily may still be 后复权 until full re-backfill."""
    rows = connection.execute(
        """
        SELECT date, open, high, low, close, volume
        FROM (
          SELECT date, open, high, low, close, volume
          FROM stock_daily
          WHERE symbol = ?
          ORDER BY date DESC
          LIMIT 60
        )
        ORDER BY date ASC
        """,
        (symbol,),
    ).fetchall()
    return [
        {
            "date": row[0],
            "open": nullable_number(row[1]),
            "high": nullable_number(row[2]),
            "low": nullable_number(row[3]),
            "close": nullable_number(row[4]),
            "volume": nullable_number(row[5]),
        }
        for row in rows
    ]


def quote_from_bars(bars: list[dict[str, Any]]) -> dict[str, float | None] | None:
    if not bars:
        return None
    latest = bars[-1]
    previous = bars[-2] if len(bars) >= 2 else None
    close = latest.get("close")
    volume = latest.get("volume")
    previous_close = previous.get("close") if previous else None
    previous_volume = previous.get("volume") if previous else None
    if close is None:
        return None
    return {
        "close": close if isinstance(close, (int, float)) else None,
        "chg_pct": (
            (close - previous_close) / previous_close
            if isinstance(close, (int, float))
            and isinstance(previous_close, (int, float))
            and previous_close != 0
            else None
        ),
        "volume": volume if isinstance(volume, (int, float)) else None,
        "vol_chg_pct": (
            (volume - previous_volume) / previous_volume
            if isinstance(volume, (int, float))
            and isinstance(previous_volume, (int, float))
            and previous_volume != 0
            else None
        ),
    }


def recent_periods(as_of: datetime) -> list[tuple[int, int]]:
    completed_quarter = (as_of.month - 1) // 3
    year = as_of.year
    if completed_quarter == 0:
        year -= 1
        completed_quarter = 4
    periods: list[tuple[int, int]] = []
    quarter = completed_quarter
    for _ in range(REPORT_ATTEMPTS):
        periods.append((year, quarter))
        quarter -= 1
        if quarter == 0:
            year -= 1
            quarter = 4
    return periods


def profit_report(row: dict[str, str]) -> dict[str, Any]:
    return {
        "stat_date": nullable_text(row.get("statDate")),
        "pub_date": nullable_text(row.get("pubDate")),
        "revenue": nullable_number(row.get("MBRevenue")),
        "net_profit": nullable_number(row.get("netProfit")),
        "eps_ttm": nullable_number(row.get("epsTTM")),
        "roe": nullable_number(row.get("roeAvg")),
        "yoy_revenue": None,
        "yoy_net_profit": None,
    }


def load_reports(code: str, periods: list[tuple[int, int]]) -> list[dict[str, Any]]:
    reports: list[dict[str, Any]] = []
    seen: set[str] = set()
    for year, quarter in periods:
        rows = result_rows(
            bs.query_profit_data(code=code, year=year, quarter=quarter),
            f"{code} profit {year}Q{quarter}",
        )
        for row in rows:
            report = profit_report(row)
            stat_date = report["stat_date"]
            if stat_date and stat_date not in seen:
                reports.append(report)
                seen.add(stat_date)
        if len(reports) >= 4:
            break
    reports.sort(key=lambda report: report["stat_date"] or "", reverse=True)
    return reports[:4]


def atomic_json(path: Path, payload: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def normalize_symbol(value: Any) -> str | None:
    """Accept int/str codes from any strategy; always return 6-digit str."""
    if value is None:
        return None
    text = str(value).strip()
    if text.endswith(".0") and text[:-2].isdigit():
        text = text[:-2]
    if text.isdigit() and 1 <= len(text) <= 6:
        return text.zfill(6)
    return None


def collect_symbols(latest: dict[str, Any]) -> dict[str, list[str]]:
    """Union of every strategy's picks — homepage quotes must cover this set."""
    symbol_strategies: dict[str, list[str]] = {}
    for strategy in latest.get("strategies", []) or []:
        strategy_name = strategy.get("name")
        if not isinstance(strategy_name, str):
            continue
        for raw in strategy.get("symbols", []) or []:
            symbol = normalize_symbol(raw)
            if symbol:
                symbol_strategies.setdefault(symbol, []).append(strategy_name)
    return symbol_strategies


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Export details + enrich latest.json quotes for ALL strategy symbols")
    parser.add_argument(
        "--only-missing",
        action="store_true",
        help="Skip symbols that already have details/{code}.json AND a quote; still cover every strategy symbol in the final maps",
    )
    args = parser.parse_args(argv)

    latest = json.loads(LATEST_PATH.read_text(encoding="utf-8"))
    symbol_strategies = collect_symbols(latest)
    symbols = sorted(symbol_strategies)
    DETAILS_DIR.mkdir(parents=True, exist_ok=True)
    as_of = datetime.now(timezone.utc)
    periods = recent_periods(as_of)

    existing_names = latest.get("names", {}) if isinstance(latest.get("names"), dict) else {}
    existing_quotes = latest.get("quotes", {}) if isinstance(latest.get("quotes"), dict) else {}
    existing_meta = latest.get("meta", {}) if isinstance(latest.get("meta"), dict) else {}

    names: dict[str, str] = {}
    quotes: dict[str, dict[str, float | None]] = {}
    # Keep grouping metadata in a sibling map so quote objects stay numeric-only
    # and the homepage can group every pick with a single latest.json fetch.
    sw_map = load_sw_industry_map()
    print(f"sw_map={len(sw_map)} path={SW_INDUSTRY_MAP_PATH}", flush=True)

    meta: dict[str, dict[str, str | None]] = {
        symbol: compose_meta(
            symbol,
            industry=None,
            board=derive_board(symbol, infer_market(symbol)),
            sw_map=sw_map,
        )
        for symbol in symbols
    }

    # Seed from prior enrich so --only-missing preserves coverage for old-pool codes.
    for symbol in symbols:
        prior_name = existing_names.get(symbol)
        if isinstance(prior_name, str) and prior_name.strip():
            names[symbol] = prior_name
        prior_quote = existing_quotes.get(symbol)
        if isinstance(prior_quote, dict) and prior_quote.get("close") is not None:
            quotes[symbol] = prior_quote  # type: ignore[assignment]
        prior_meta = existing_meta.get(symbol)
        if isinstance(prior_meta, dict):
            board = prior_meta.get("board") or derive_board(symbol, infer_market(symbol))
            meta[symbol] = compose_meta(
                symbol,
                industry=prior_meta.get("industry") if isinstance(prior_meta.get("industry"), str) or prior_meta.get("industry") is None else None,
                board=str(board),
                sw_map=sw_map,
            )

    to_fetch = []
    for symbol in symbols:
        detail_path = DETAILS_DIR / f"{symbol}.json"
        has_quote = symbol in quotes
        if args.only_missing and detail_path.is_file() and has_quote:
            continue
        to_fetch.append(symbol)

    print(
        f"symbols={len(symbols)} to_fetch={len(to_fetch)} only_missing={args.only_missing} "
        f"seeded_quotes={len(quotes)} seeded_names={len(names)}",
        flush=True,
    )

    sig_day = signal_day_today()
    sig_bars: dict[str, dict[str, Any]] = {}
    if sig_day:
        sig_bars = fetch_signal_day_bars(to_fetch, sig_day)
        print(f"[sigday] {sig_day}: tencent qt bars={len(sig_bars)}/{len(to_fetch)}", flush=True)
    sig_appended = 0

    login = bs.login()
    if login.error_code != "0":
        raise RuntimeError(f"Baostock login failed: {login.error_code} {login.error_msg}")

    exported = 0
    try:
        with sqlite3.connect(DB_PATH) as connection:
            for index, symbol in enumerate(to_fetch, start=1):
                try:
                    market = infer_market(symbol)
                    remote_code = baostock_code(symbol, market)
                    basic_rows = result_rows(bs.query_stock_basic(code=remote_code), f"{remote_code} basic")
                    industry_rows = result_rows(bs.query_stock_industry(code=remote_code), f"{remote_code} industry")
                    basic = basic_rows[0] if basic_rows else {}
                    industry = industry_rows[0] if industry_rows else {}
                    name = nullable_text(basic.get("code_name")) or nullable_text(industry.get("code_name"))
                    industry_name = nullable_text(industry.get("industry"))
                    board = derive_board(symbol, market)
                    if name:
                        names[symbol] = name
                    meta[symbol] = compose_meta(symbol, industry=industry_name, board=board, sw_map=sw_map)
                    reports = load_reports(remote_code, periods)
                    bars = load_bars_unadj(remote_code, symbol)
                    if not bars:
                        # stock_daily is 后复权 (hfq) — do NOT publish it as 不复权
                        # ohlcv_60d; keep the previous details file's bars instead.
                        prev_path = DETAILS_DIR / f"{symbol}.json"
                        try:
                            prev_payload = json.loads(prev_path.read_text(encoding="utf-8"))
                            # only reuse bars already known to be 不复权
                            bars = (prev_payload.get("ohlcv_60d") or []) if prev_payload.get("price_basis") == "不复权" else []
                        except (OSError, json.JSONDecodeError):
                            bars = []
                        warn(f"{symbol}: baostock 不复权 empty; kept previous details bars ({len(bars)})")
                    # Signal-day bar: baostock lags until evening -> append raw spot bar.
                    sig_bar = sig_bars.get(symbol)
                    if sig_day and sig_bar and (not bars or str(bars[-1].get("date")) < sig_day):
                        bars = [b for b in bars if str(b.get("date")) != sig_day] + [sig_bar]
                        if len(bars) > 60:
                            bars = bars[-60:]
                        sig_appended += 1
                    quote = quote_from_bars(bars)
                    if quote is not None:
                        quotes[symbol] = quote
                    detail = {
                        "symbol": symbol,
                        "name": name,
                        "market": market,
                        "industry": industry_name,
                        "board": board,
                        "ipo_date": nullable_text(basic.get("ipoDate")),
                        "main_business": None,
                        "as_of": as_of.isoformat(),
                        "price_basis": "不复权",
                        "ohlcv_60d": bars,
                        "last_report": reports[0] if reports else None,
                        "recent_reports": reports[1:4],
                        "picked_strategies": symbol_strategies[symbol],
                    }
                    atomic_json(DETAILS_DIR / f"{symbol}.json", detail)
                    exported += 1
                except Exception as error:
                    warn(f"{symbol}: {error}")
                if index == 1 or index % 10 == 0 or index == len(to_fetch):
                    print(f"[{index}/{len(to_fetch)}] exported={exported}", flush=True)
    finally:
        bs.logout()
    if sig_day:
        print(f"[sigday] {sig_day}: appended tencent_qt signal-day bar to {sig_appended} details", flush=True)

    for symbol in symbols:
        names.setdefault(symbol, "暂无")
        current = meta.get(symbol) or {}
        board = current.get("board") or derive_board(symbol, infer_market(symbol))
        meta[symbol] = compose_meta(
            symbol,
            industry=current.get("industry") if isinstance(current.get("industry"), str) or current.get("industry") is None else None,
            board=str(board),
            sw_map=sw_map,
        )
    # Final maps must cover the union of all strategy symbols (not a stale fixed pool).
    latest["names"] = {symbol: names[symbol] for symbol in symbols}
    latest["quotes"] = {symbol: quotes[symbol] for symbol in symbols if symbol in quotes}
    latest["meta"] = {symbol: meta[symbol] for symbol in symbols}
    latest["price_basis"] = "不复权"
    latest.pop("prices", None)
    atomic_json(LATEST_PATH, latest)
    missing_quotes = [s for s in symbols if s not in latest["quotes"]]
    print(
        f"Exported {exported} detail files; names={len(latest['names'])}; "
        f"quotes={len(latest['quotes'])}; meta={len(latest['meta'])}; "
        f"unique_symbols={len(symbols)}; missing_quotes={len(missing_quotes)}; price_basis=不复权",
        flush=True,
    )
    if missing_quotes:
        warn(f"missing quotes sample: {missing_quotes[:20]}")
    # Success if every symbol was attempted and we have quotes for all (or only_missing seeded them).
    return 0 if not missing_quotes else 1


if __name__ == "__main__":
    raise SystemExit(main())
