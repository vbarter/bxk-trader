#!/usr/bin/env python3
"""Export watch calendar: signal-day R picks → R+1 open buy → R+2 open sell.

Cadence (Asia/Shanghai):
  - 15:05 close scan writes that day's 5 recommended stocks into
    data/daily_picks/YYYY-MM-DD.json (signal day R) and homepage latest.json.
  - Next trading day 09:35: buy at open (buy_date=R+1).
  - Trading day after that 09:35: sell at open and settle (sell_date=R+2).

Per-stock return: (open_{R+2} - open_{R+1}) / open_{R+1} * 100
Day metric: sum of that day's up-to-5 stock % returns (eq_sum_chg_pct); eq_avg_chg_pct kept for compat.
Settle when both opens exist — do NOT wait for close.

Picks source:
  - Prefer data/daily_picks/{date}.json
  - Days without daily_picks are omitted (no fake Theo Top5 placeholders).

Prices: baostock adjustflag=3 不复权 opens (raw). Spot overlay for
today when baostock has no bar yet. Falls back to details ohlcv_60d.
Writes data/watch_calendar.json.
"""

from __future__ import annotations

import json
import sys
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from loss_review import build_review, industry_horizon_return


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
DETAILS_DIR = DATA_DIR / "details"
PICKS_DIR = DATA_DIR / "daily_picks"
OUT_PATH = DATA_DIR / "watch_calendar.json"
sys.path.insert(0, str(Path(__file__).resolve().parent))
from pick_models import MODEL_KEYS, MODEL_LABELS, all_archive_dirs, all_picks_dirs, model_id_for  # noqa: E402
SPOT_PATH = DATA_DIR / "watch_spot_opens.json"

# Bootstrap trading calendar / baostock probe symbols (not used as fake picks).
CALENDAR_PROBE: list[str] = ["000001", "600519", "000002"]

# Match historical calendar range used by prior exports.
START_DATE = "2024-01-01"
ADJUST_FLAG = "3"  # 不复权

NOTE = (
    "信号日 R 推荐 → 次日开盘买入 → 再下一日开盘卖出结算；"
    "收益=(卖出日开盘−买入日开盘)/买入日开盘，五只涨跌幅相加；"
    "未走完标未结算。仅观察非建议。"
    "价格与涨跌均按不复权行情。"
)



def day_looks_settled(day: dict[str, Any]) -> bool:
    """True if a calendar day already carries settlement fields.

    Hard rule: never demote such a day back to pending on rebuild.
    A pending/paused day, or one where any bought pick lacks a sell open, is
    not settled (2026-10-08: partial sell opens froze 2026-09-24 GPT).
    """
    if not isinstance(day, dict):
        return False
    status = day.get("status")
    if status == "settled":
        return True
    # 2026-10-08 fix: a pending day with only *partial* sell opens (quote failed
    # for some picks) must NOT be frozen; let rebuild re-settle it.
    if status in ("pending", "paused"):
        return False
    if day.get("eq_sum_chg_pct") is not None or day.get("eq_avg_chg_pct") is not None:
        return True
    # Unknown/legacy status: settled only if EVERY bought pick (has buy_open)
    # has a sell_open. Never-bought picks (suspended, no buy open) are ignored.
    bought = [
        s for s in (day.get("stocks") or [])
        if isinstance(s, dict) and s.get("buy_open") is not None
    ]
    return bool(bought) and all(s.get("sell_open") is not None for s in bought)


def merge_preserve_settled(payload: dict[str, Any]) -> dict[str, Any]:
    """Merge rebuild onto existing watch_calendar: never demote settled days.

    Prefer keeping the existing settled day object (picks + eq + sell_open) when
    the rebuild would mark it pending or replace it with a divergent pick list.
    Also keep settled days the rebuild omitted (e.g. local picks file diverged).
    """
    if not OUT_PATH.exists():
        return payload
    try:
        existing = json.loads(OUT_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        warn(f"preserve: cannot read existing calendar: {exc}")
        return payload
    existing_days = {
        d["date"]: d
        for d in (existing.get("days") or [])
        if isinstance(d, dict) and isinstance(d.get("date"), str)
    }
    if not existing_days:
        return payload

    new_days = [d for d in (payload.get("days") or []) if isinstance(d, dict)]
    new_dates = {d["date"] for d in new_days if isinstance(d.get("date"), str)}
    merged: list[dict[str, Any]] = []
    preserved = 0

    for day in new_days:
        date = day.get("date")
        old = existing_days.get(date) if isinstance(date, str) else None
        if old is not None and day_looks_settled(old):
            # Keep prior settlement even if rebuild also claims settled (pick-list drift).
            merged.append(old)
            preserved += 1
            new_status = day.get("status")
            if not day_looks_settled(day):
                print(
                    f"[preserve] {date}: keep existing settled (rebuild was {new_status})",
                    flush=True,
                )
            else:
                print(
                    f"[preserve] {date}: keep existing settled (skip rebuild replace)",
                    flush=True,
                )
        else:
            merged.append(day)

    for date, old in existing_days.items():
        if date not in new_dates and day_looks_settled(old):
            merged.append(old)
            preserved += 1
            print(f"[preserve] {date}: keep settled day omitted by rebuild", flush=True)

    merged.sort(key=lambda d: d.get("date") or "")
    payload = dict(payload)
    payload["days"] = merged
    if preserved:
        print(
            f"[preserve] preserved {preserved} settled day(s) from existing calendar",
            flush=True,
        )
    return payload


def warn(message: str) -> None:
    print(f"[warn] {message}", file=sys.stderr, flush=True)


def round_pct(value: float) -> float:
    return round(value, 4)


def round_price(value: float) -> float:
    return round(value, 6)


def to_bs_code(symbol: str) -> str:
    prefix = "sh" if symbol.startswith(("6", "9")) else "sz"
    return f"{prefix}.{symbol}"


def to_sina_code(symbol: str) -> str:
    return ("sh" if symbol.startswith(("6", "9")) else "sz") + symbol


def to_em_secid(symbol: str) -> str:
    mkt = "1" if symbol.startswith(("6", "9")) else "0"
    return f"{mkt}.{symbol}"


def load_bars_from_baostock(code: str, end_date: str) -> list[dict[str, Any]]:
    import baostock as bs

    rs = bs.query_history_k_data_plus(
        to_bs_code(code),
        "date,open,high,low,close,volume",
        start_date=START_DATE,
        end_date=end_date,
        frequency="d",
        adjustflag=ADJUST_FLAG,
    )
    if rs.error_code != "0":
        warn(f"{code}: baostock 不复权 failed: {rs.error_msg}")
        return []
    bars: list[dict[str, Any]] = []
    while rs.next():
        row = dict(zip(rs.fields, rs.get_row_data()))
        open_ = row.get("open")
        close = row.get("close")
        if open_ in ("", None) and close in ("", None):
            continue
        try:
            open_f = float(open_) if open_ not in ("", None) else None
            close_f = float(close) if close not in ("", None) else None
        except ValueError:
            continue
        if open_f is None and close_f is None:
            continue
        high = row.get("high")
        low = row.get("low")
        volume = row.get("volume")
        bars.append(
            {
                "date": str(row.get("date", ""))[:10],
                "open": open_f,
                "high": float(high) if high not in ("", None) else None,
                "low": float(low) if low not in ("", None) else None,
                "close": close_f,
                "volume": float(volume) if volume not in ("", None) else None,
            }
        )
    return bars



def load_bars_from_tencent(code: str, end_date: str) -> list[dict[str, Any]]:
    """不复权日K via Tencent fqkline (empty adjust suffix)."""
    prefix = "sh" if code.startswith(("6", "9")) else "sz"
    # end inclusive; ask from START_DATE compressed as YYYY-MM-DD
    url = (
        "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
        f"?param={prefix}{code},day,{START_DATE},{end_date},640,"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        warn(f"{code}: tencent 不复权 failed: {exc}")
        return []
    data = (payload.get("data") or {}).get(f"{prefix}{code}") or {}
    rows = data.get("day") or []  # raw only; never qfqday
    bars: list[dict[str, Any]] = []
    for row in rows:
        if not row or len(row) < 2:
            continue
        try:
            open_f = float(row[1]) if row[1] not in ("", None) else None
        except (TypeError, ValueError):
            continue
        close_f = None
        high_f = low_f = vol_f = None
        try:
            if len(row) > 2 and row[2] not in ("", None):
                close_f = float(row[2])
            if len(row) > 3 and row[3] not in ("", None):
                high_f = float(row[3])
            if len(row) > 4 and row[4] not in ("", None):
                low_f = float(row[4])
            if len(row) > 5 and row[5] not in ("", None):
                vol_f = float(row[5])
        except (TypeError, ValueError):
            pass
        bars.append(
            {
                "date": str(row[0])[:10],
                "open": open_f,
                "high": high_f,
                "low": low_f,
                "close": close_f,
                "volume": vol_f,
            }
        )
    return bars

def load_bars_from_details(code: str) -> list[dict[str, Any]]:
    path = DETAILS_DIR / f"{code}.json"
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        warn(f"{code}: failed to read details: {exc}")
        return []
    if payload.get("price_basis") != "不复权":
        warn(f"{code}: details price_basis={payload.get('price_basis')!r}; not used")
        return []
    out: list[dict[str, Any]] = []
    for bar in payload.get("ohlcv_60d") or []:
        if bar.get("src"):
            continue  # spot-appended signal-day bar (picker only) — never settle on it
        open_ = bar.get("open")
        close = bar.get("close")
        if open_ is None and close is None:
            continue
        out.append(
            {
                "date": str(bar.get("date", ""))[:10],
                "open": float(open_) if open_ is not None else None,
                "high": float(bar["high"]) if bar.get("high") is not None else None,
                "low": float(bar["low"]) if bar.get("low") is not None else None,
                "close": float(close) if close is not None else None,
                "volume": float(bar["volume"]) if bar.get("volume") is not None else None,
            }
        )
    out.sort(key=lambda b: b["date"])
    return out


def fetch_spot_opens(codes: list[str]) -> dict[str, float]:
    """Raw open prices from EM/Sina for codes missing today's baostock bar."""
    out: dict[str, float] = {}
    if not codes:
        return out
    # Prefer cached spot file from sync_watch_today when same day.
    today = date.today().isoformat()
    if SPOT_PATH.exists():
        try:
            cached = json.loads(SPOT_PATH.read_text(encoding="utf-8"))
            if cached.get("date") == today and isinstance(cached.get("opens"), dict):
                for code, item in cached["opens"].items():
                    if code in codes and isinstance(item, dict) and item.get("open") is not None:
                        if float(item["open"]) > 0:
                            out[code] = float(item["open"])
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            pass
    missing = [c for c in codes if c not in out]
    if not missing:
        return out

    secids = ",".join(to_em_secid(c) for c in missing)
    em_url = (
        "https://push2.eastmoney.com/api/qt/ulist.np/get"
        f"?fltt=2&fields=f12,f17&secids={secids}"
    )
    req = urllib.request.Request(
        em_url,
        headers={"User-Agent": "Mozilla/5.0", "Referer": "https://quote.eastmoney.com/"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        for item in (payload.get("data") or {}).get("diff") or []:
            code = str(item.get("f12", "")).zfill(6)
            open_ = item.get("f17")
            if code in missing and open_ not in (None, "-", "") and float(open_) > 0:
                out[code] = float(open_)
    except Exception as exc:
        warn(f"eastmoney spot overlay failed: {exc}")

    still = [c for c in missing if c not in out]
    if not still:
        return out
    sina_list = ",".join(to_sina_code(c) for c in still)
    req = urllib.request.Request(
        f"https://hq.sinajs.cn/list={sina_list}",
        headers={"User-Agent": "Mozilla/5.0", "Referer": "https://finance.sina.com.cn"},
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
            if len(fields) < 2 or code not in still:
                continue
            if len(fields) > 30 and fields[30] and fields[30] != today:
                continue  # stale quote
            try:
                o = float(fields[1])
            except ValueError:
                continue
            if o > 0:  # 0 = not opened / suspended -> stay missing (pending)
                out[code] = o
    except Exception as exc:
        warn(f"sina spot overlay failed: {exc}")
    return out


def resolve_name(code: str, fallback: str) -> str:
    path = DETAILS_DIR / f"{code}.json"
    if path.exists():
        try:
            name = json.loads(path.read_text(encoding="utf-8")).get("name")
            if isinstance(name, str) and name.strip():
                return name.strip()
        except (OSError, json.JSONDecodeError):
            pass
    return fallback


def index_bars(bars: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {bar["date"]: bar for bar in bars if bar.get("date")}


def load_picks_file(day: str, picks_dir: Path | None = None) -> list[dict[str, str]] | None:
    path = (picks_dir or PICKS_DIR) / f"{day}.json"
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        warn(f"{day}: bad daily_picks file: {exc}")
        return None
    # Paused day (pick step failed): never treat any symbols as picks.
    if payload.get("paused") or payload.get("pick_status") == "paused":
        return None
    # Ignore theo placeholder files if any remain on disk.
    if payload.get("source") == "theo_top5_backfill":
        warn(f"{day}: ignoring theo_top5_backfill daily_picks")
        return None
    symbols = payload.get("symbols") or []
    source = str(payload.get("source") or "")
    out: list[dict[str, str]] = []
    for item in symbols:
        if isinstance(item, str):
            code = item.zfill(6)
            out.append({"code": code, "name": resolve_name(code, code)})
            continue
        if not isinstance(item, dict):
            continue
        code = str(item.get("code") or "").zfill(6)
        if not code.isdigit() or len(code) != 6:
            continue
        name = item.get("name")
        if not isinstance(name, str) or not name.strip():
            name = resolve_name(code, code)
        row: dict[str, str] = {"code": code, "name": name.strip()}
        # Preserve LLM 人话推荐理由 into calendar stocks (do not strip to code/name).
        if source == "llm_rerank":
            reason = item.get("reason")
            explain = item.get("explain")
            if isinstance(reason, str) and reason.strip():
                row["reason"] = reason.strip()[:40]
            if isinstance(explain, str) and explain.strip():
                row["explain"] = explain.strip()[:150]
        out.append(row)
    return out[:5] if out else None


def picks_paused(day: str, picks_dir: Path | None = None) -> bool:
    """daily_picks/<day>.json marked paused (pick step failed, no picks)."""
    path = (picks_dir or PICKS_DIR) / f"{day}.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return bool(payload.get("paused") or payload.get("pick_status") == "paused")
    except (OSError, json.JSONDecodeError, AttributeError):
        return False


PICK_STATUS_KEYS = ("pick_status", "pause_reason", "attempts", "pick_status_at")


def pick_status_fields(day: str, picks_dir: Path | None = None) -> dict[str, Any]:
    """pick_status/pause_reason/attempts/pick_status_at from the daily_picks file.

    Only files written since 2026-09-28 carry these; older days get nothing
    (kept byte-identical).
    """
    path = (picks_dir or PICKS_DIR) / f"{day}.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    out = {k: payload[k] for k in PICK_STATUS_KEYS if k in payload}
    # Dual-model files (model_key present, 2026-09-29+) also carry model + backfill.
    if "model_key" in payload:
        if payload.get("model"):
            out["model"] = payload["model"]
        out["backfill"] = bool(payload.get("backfill"))
    if (payload.get("paused") or payload.get("pick_status") == "paused"):
        out["pick_status"] = "paused"
    return out


def picks_for_day(day: str, picks_dir: Path | None = None) -> list[dict[str, str]] | None:
    """Return real picks for day, or None to omit the day (no fake symbols)."""
    return load_picks_file(day, picks_dir)


def collect_needed_codes() -> list[str]:
    codes: list[str] = list(CALENDAR_PROBE)
    # union of every model's picks + archived live batches (still settled)
    for pdir in [*all_picks_dirs(PICKS_DIR).values(), *all_archive_dirs(PICKS_DIR).values()]:
        if not pdir.exists():
            continue
        for path in sorted(pdir.glob("*.json")):
            loaded = load_picks_file(path.stem, pdir)
            if loaded:
                for s in loaded:
                    if s["code"] not in codes:
                        codes.append(s["code"])
    return codes


def build_trading_calendar(per_symbol: dict[str, dict[str, dict[str, Any]]]) -> list[str]:
    probe_dates = sorted(
        {d for code in CALENDAR_PROBE for d in (per_symbol.get(code) or {})}
    )
    if probe_dates:
        return probe_dates
    return sorted({d for bars in per_symbol.values() for d in bars})



def apply_local_calendar(bar_dates: list[str], today: str) -> list[str]:
    """R / R+1 / R+2 date math from the local exchange calendar (Sina cache).

    Past days come from data/trade_calendar.json (not from probe-symbol bars, so a
    baostock/tencent outage can't drop or invent days). *Today* is only included
    when it is a trading day AND bars/spot already show today's open (same rule as
    before, so a pending day never gets a buy/sell date without prices).
    Falls back to the bar-derived list if the local calendar is unavailable.
    """
    try:
        import trade_calendar  # scripts/trade_calendar.py
    except Exception as exc:  # noqa: BLE001
        warn(f"local trade calendar unavailable ({exc}); using bar-derived dates")
        return bar_dates
    if not bar_dates:
        return bar_dates
    yesterday = (date.fromisoformat(today) - timedelta(days=1)).isoformat()
    start = max(START_DATE, bar_dates[0])
    local = trade_calendar.trading_days(start, yesterday)
    if not local:
        warn("local trade calendar has no coverage; using bar-derived dates")
        return bar_dates
    out = list(local)
    if today in bar_dates:
        ok, src = trade_calendar.is_trading_day(today, allow_baostock=False)
        if ok is not False:  # True, or unknown beyond coverage -> trust bar evidence
            out.append(today)
        else:
            warn(f"{today}: bars/spot present but calendar says non-trading ({src}); dropped")
    extra = sorted(set(d for d in bar_dates if d < today) - set(local))
    missing = sorted(set(local) - set(bar_dates))
    if extra:
        warn(f"calendar: bar dates not in exchange calendar dropped: {extra[-5:]}")
    if missing:
        print(f"[calendar] exchange days without probe bars (kept): {missing[-5:]}", flush=True)
    return out


INDEX_CANDIDATES = ["000300", "000001"]  # 沪深300 then 上证; queried as sh.XXXXXX


def load_index_bars(logged_in: bool, end_date: str) -> tuple[str | None, dict[str, dict[str, Any]]]:
    """Prefer 沪深300 sh.000300, else 上证 sh.000001. Returns (code, date->bar)."""
    import baostock as bs

    for code in INDEX_CANDIDATES:
        bars: list[dict[str, Any]] = []
        if logged_in:
            rs = bs.query_history_k_data_plus(
                f"sh.{code}",
                "date,open,high,low,close,volume",
                start_date=START_DATE,
                end_date=end_date,
                frequency="d",
                adjustflag=ADJUST_FLAG,
            )
            if rs.error_code == "0":
                while rs.next():
                    row = dict(zip(rs.fields, rs.get_row_data()))
                    open_ = row.get("open")
                    if open_ in ("", None):
                        continue
                    try:
                        bars.append(
                            {
                                "date": row["date"],
                                "open": float(open_),
                                "close": float(row["close"]) if row.get("close") not in ("", None) else None,
                                "volume": float(row["volume"]) if row.get("volume") not in ("", None) else None,
                            }
                        )
                    except (TypeError, ValueError):
                        continue
        if not bars:
            # Index codes live on Shanghai; bypass load_bars_from_tencent board heuristic.
            try:
                url = (
                    "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
                    f"?param=sh{code},day,{START_DATE},{end_date},640,"
                )
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=20) as resp:
                    payload = json.loads(resp.read().decode("utf-8"))
                data = (payload.get("data") or {}).get(f"sh{code}") or {}
                rows = data.get("day") or data.get("qfqday") or []
                for row in rows:
                    if not row or len(row) < 2:
                        continue
                    try:
                        open_f = float(row[1])
                    except (TypeError, ValueError):
                        continue
                    bars.append({"date": str(row[0])[:10], "open": open_f})
            except Exception as exc:
                warn(f"index {code} tencent failed: {exc}")
                bars = []
        if bars:
            print(f"[index] using sh.{code} bars={len(bars)}", flush=True)
            return code, index_bars(bars)
    warn("index bars missing; market_drag/weak_vs_index skipped")
    return None, {}


def load_industry_map() -> dict[str, list[str]]:
    """industry -> [codes] from details/*.json."""
    out: dict[str, list[str]] = {}
    if not DETAILS_DIR.exists():
        return out
    for path in DETAILS_DIR.glob("*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        industry = payload.get("industry")
        code = str(payload.get("symbol") or path.stem).zfill(6)
        if not isinstance(industry, str) or not industry.strip():
            continue
        if not code.isdigit() or len(code) != 6:
            continue
        out.setdefault(industry.strip(), []).append(code)
    return out


def load_strategies(code: str) -> list[str]:
    path = DETAILS_DIR / f"{code}.json"
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    strats = payload.get("picked_strategies") or []
    return [str(s) for s in strats if isinstance(s, str) and s.strip()]


def load_industry_for(code: str) -> str | None:
    path = DETAILS_DIR / f"{code}.json"
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    industry = payload.get("industry")
    return industry.strip() if isinstance(industry, str) and industry.strip() else None


def bar_field(per_symbol: dict, code: str, day: str | None, field: str):
    if day is None:
        return None
    bar = (per_symbol.get(code) or {}).get(day) or {}
    val = bar.get(field)
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def prev_trading_close(per_symbol: dict, code: str, calendar_dates: list[str], day: str) -> float | None:
    if day not in calendar_dates:
        # find nearest
        earlier = [d for d in calendar_dates if d < day]
        if not earlier:
            return None
        # use last earlier bar close as prev? still need day before signal
    try:
        i = calendar_dates.index(day)
    except ValueError:
        earlier = [d for d in calendar_dates if d < day]
        if not earlier:
            return None
        prev = earlier[-1]
        return bar_field(per_symbol, code, prev, "close")
    if i <= 0:
        return None
    return bar_field(per_symbol, code, calendar_dates[i - 1], "close")


def build_calendar() -> dict[str, Any]:
    import baostock as bs

    end_date = date.today().isoformat()
    bootstrap_codes = list(CALENDAR_PROBE)
    per_symbol: dict[str, dict[str, dict[str, Any]]] = {}

    login = bs.login()
    if login.error_code != "0":
        warn(f"baostock login failed: {login.error_msg}; will try details fallback")
        logged_in = False
    else:
        logged_in = True

    try:
        def ensure_bars(code: str) -> None:
            if code in per_symbol:
                return
            bars: list[dict[str, Any]] = []
            if logged_in:
                bars = load_bars_from_baostock(code, end_date)
            if not bars:
                bars = load_bars_from_tencent(code, end_date)
                if bars:
                    print(f"[tencent] {code}: {len(bars)} 不复权 bars", flush=True)
            if not bars:
                bars = load_bars_from_details(code)
                if bars:
                    warn(f"{code}: using details ohlcv_60d ({len(bars)} bars)")
                else:
                    warn(f"{code}: no 不复权 bars from baostock/tencent/details")
            per_symbol[code] = index_bars(bars)

        for code in bootstrap_codes:
            ensure_bars(code)

        calendar_dates = build_trading_calendar(per_symbol)
        needed = collect_needed_codes()
        for code in needed:
            ensure_bars(code)

        # Overlay today's raw spot opens when baostock has no bar yet (AM settle).
        today = end_date
        missing_today = [
            code
            for code in per_symbol
            if (per_symbol[code].get(today) or {}).get("open") is None
        ]
        if missing_today:
            spot = fetch_spot_opens(missing_today)
            for code, open_ in spot.items():
                bar = per_symbol.setdefault(code, {}).setdefault(today, {"date": today})
                bar["open"] = open_
                bar.setdefault("high", None)
                bar.setdefault("low", None)
                bar.setdefault("close", None)
                bar.setdefault("volume", None)
                print(f"[overlay] {code} {today} raw open={open_}", flush=True)

        calendar_dates = build_trading_calendar(per_symbol)
        # AM settle: baostock often has no bar for *today* yet. Probe symbols
        # (calendar source) may also miss today's spot if EM/Sina are blocked and
        # watch_spot_opens only covers pick codes. If any symbol (or spot cache)
        # has today's open, append today so R+2 can settle.
        if today not in calendar_dates:
            has_today_open = any(
                (bars.get(today) or {}).get("open") is not None
                for bars in per_symbol.values()
            )
            spot_says_today = False
            if SPOT_PATH.exists():
                try:
                    cached = json.loads(SPOT_PATH.read_text(encoding="utf-8"))
                    spot_says_today = (
                        cached.get("date") == today and bool(cached.get("opens"))
                    )
                except (OSError, json.JSONDecodeError, TypeError, ValueError):
                    spot_says_today = False
            if has_today_open or spot_says_today:
                calendar_dates = sorted(set(calendar_dates) | {today})
                print(
                    f"[calendar] appended today={today} "
                    f"(baostock lag; spot opens available)",
                    flush=True,
                )

        calendar_dates = apply_local_calendar(calendar_dates, today)

        index_code, index_by_date = load_index_bars(logged_in, end_date)
        industry_map = load_industry_map()

        def get_open_any(code: str, day: str) -> float | None:
            # Prefer in-memory bars; fall back to details ohlcv_60d for industry peers.
            v = bar_field(per_symbol, code, day, "open")
            if v is not None:
                return v
            path = DETAILS_DIR / f"{code}.json"
            if not path.exists():
                return None
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return None
            for bar in payload.get("ohlcv_60d") or []:
                if isinstance(bar, dict) and bar.get("date") == day and bar.get("open") is not None:
                    try:
                        return float(bar["open"])
                    except (TypeError, ValueError):
                        return None
            return None

        if not calendar_dates:
            warn("no trading dates found for watch universe")
            return {
                "symbols": [],
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "note": NOTE,
                "price_basis": "不复权",
                "days": [],
            }

        def build_days(picks_dir: Path) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
            """Same settlement rules for every model; only the picks dir differs."""
            days: list[dict[str, Any]] = []
            latest_symbols: list[dict[str, str]] = []

            for i, signal_date in enumerate(calendar_dates):
                picks = picks_for_day(signal_date, picks_dir)
                if not picks:
                    if picks_paused(signal_date, picks_dir):
                        # AI pick step failed after retries: show the day as paused
                        # (no stocks, nothing bought/settled, excluded from KPI).
                        paused_day: dict[str, Any] = {
                            "date": signal_date,
                            "status": "paused",
                            "buy_date": None,
                            "sell_date": None,
                            "eq_avg_chg_pct": None,
                            "eq_sum_chg_pct": None,
                            "n": 0,
                            "stocks": [],
                        }
                        paused_day.update(pick_status_fields(signal_date, picks_dir))
                        days.append(paused_day)
                        latest_symbols = []
                    # No real daily_picks for this signal day — omit (do not invent).
                    continue
                latest_symbols = picks
                for p in picks:
                    ensure_bars(p["code"])

                has_buy = i + 1 < len(calendar_dates)
                has_sell = i + 2 < len(calendar_dates)
                buy_date = calendar_dates[i + 1] if has_buy else None
                sell_date = calendar_dates[i + 2] if has_sell else None

                sell_opens_ready = False
                if has_sell and sell_date is not None:
                    # PM rule 2026-09-27: settle only when EVERY pick that was bought
                    # has a real sell-day open. A missing open (quote failed) keeps
                    # the whole day pending; never fill it from another price.
                    def _open(code: str, d: str | None):
                        return ((per_symbol.get(code) or {}).get(d) or {}).get("open") if d else None
                    bought = [p for p in picks if _open(p["code"], buy_date) is not None]
                    sell_opens_ready = bool(bought) and all(
                        _open(p["code"], sell_date) is not None for p in bought
                    )
                pending = (not has_sell) or (not sell_opens_ready)

                stocks: list[dict[str, Any]] = []
                settled_returns: list[float] = []

                for p in picks:
                    code = p["code"]
                    name = p["name"]
                    buy_open: float | None = None
                    sell_open: float | None = None
                    chg_pct: float | None = None

                    if buy_date is not None:
                        buy_bar = (per_symbol.get(code) or {}).get(buy_date)
                        if buy_bar is not None and buy_bar.get("open") is not None:
                            buy_open = float(buy_bar["open"])

                    if sell_date is not None:
                        sell_bar = (per_symbol.get(code) or {}).get(sell_date)
                        if sell_bar is not None and sell_bar.get("open") is not None:
                            sell_open = float(sell_bar["open"])

                    if (
                        buy_open is not None
                        and sell_open is not None
                        and buy_open != 0
                        and not pending
                    ):
                        chg_pct = (sell_open / buy_open - 1.0) * 100.0
                        settled_returns.append(chg_pct)

                    stock_obj: dict[str, Any] = {
                        "code": code,
                        "name": name,
                        "buy_open": round_price(buy_open) if buy_open is not None else None,
                        "sell_open": round_price(sell_open) if sell_open is not None else None,
                        "chg_pct": round_pct(chg_pct) if chg_pct is not None else None,
                    }
                    if p.get("reason"):
                        stock_obj["reason"] = str(p["reason"])[:40]
                    if p.get("explain"):
                        stock_obj["explain"] = str(p["explain"])[:150]
                    if (
                        (not pending)
                        and chg_pct is not None
                        and chg_pct < 0
                        and buy_open is not None
                        and sell_open is not None
                        and buy_date is not None
                        and sell_date is not None
                    ):
                        ret = sell_open / buy_open - 1.0
                        r_close = bar_field(per_symbol, code, signal_date, "close")
                        r_volume = bar_field(per_symbol, code, signal_date, "volume")
                        r_prev_close = prev_trading_close(
                            per_symbol, code, calendar_dates, signal_date
                        )
                        buy_close = bar_field(per_symbol, code, buy_date, "close")
                        buy_volume = bar_field(per_symbol, code, buy_date, "volume")

                        idx_ret = None
                        if index_by_date:
                            ib = index_by_date.get(buy_date) or {}
                            is_ = index_by_date.get(sell_date) or {}
                            if ib.get("open") and is_.get("open") and ib["open"] != 0:
                                idx_ret = float(is_["open"]) / float(ib["open"]) - 1.0

                        industry = load_industry_for(code)
                        industry_ret = None
                        industry_n = None
                        if industry and industry in industry_map:
                            peers = [{"code": c} for c in industry_map[industry] if c != code]
                            industry_ret, industry_n = industry_horizon_return(
                                peers, buy_date, sell_date, get_open_any
                            )

                        review = build_review(
                            code=code,
                            ret=ret,
                            buy_open=buy_open,
                            sell_open=sell_open,
                            r_close=r_close,
                            r_prev_close=r_prev_close,
                            r_volume=r_volume,
                            buy_close=buy_close,
                            buy_volume=buy_volume,
                            idx_ret=idx_ret,
                            industry_ret=industry_ret,
                            industry_n=industry_n,
                            strategies=load_strategies(code),
                            asof=sell_date,
                        )
                        if review is not None:
                            stock_obj["review"] = review

                    if pending:
                        stocks.append(stock_obj)
                    elif chg_pct is not None:
                        stocks.append(stock_obj)

                n = (
                    len(settled_returns)
                    if not pending
                    else sum(1 for s in stocks if s.get("buy_open") is not None)
                )

                if pending:
                    day_obj: dict[str, Any] = {
                        "date": signal_date,
                        "status": "pending",
                        "buy_date": buy_date,
                        "sell_date": sell_date,
                        "eq_avg_chg_pct": None,
                        "eq_sum_chg_pct": None,
                        "n": n,
                        "stocks": stocks,
                    }
                else:
                    if not settled_returns:
                        continue
                    eq_sum = sum(settled_returns)
                    eq_avg = eq_sum / len(settled_returns)
                    day_obj = {
                        "date": signal_date,
                        "status": "settled",
                        "buy_date": buy_date,
                        "sell_date": sell_date,
                        "eq_avg_chg_pct": round_pct(eq_avg),
                        "eq_sum_chg_pct": round_pct(eq_sum),
                        "n": len(settled_returns),
                        "stocks": stocks,
                    }
                day_obj.update(pick_status_fields(signal_date, picks_dir))
                days.append(day_obj)
            return days, latest_symbols

        days, latest_symbols = build_days(PICKS_DIR)  # gpt (legacy top-level days)
        extra_tracks: dict[str, list[dict[str, Any]]] = {}
        for _key, _pdir in all_picks_dirs(PICKS_DIR).items():
            if _key == "gpt":
                continue
            extra_tracks[_key] = build_days(_pdir)[0] if _pdir.exists() else []
        archived_tracks: dict[str, list[dict[str, Any]]] = {}
        for _key, _adir in all_archive_dirs(PICKS_DIR).items():
            if _adir.exists() and any(_adir.glob("*.json")):
                archived_tracks[_key] = [
                    {**_d, "archived": True, "exclude_from_totals": True} for _d in build_days(_adir)[0]
                ]

        symbols_meta = [
            {"code": s["code"], "name": resolve_name(s["code"], s["name"])}
            for s in latest_symbols
        ]

        return {
            "symbols": symbols_meta,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "note": NOTE,
            "price_basis": "不复权",
            "days": days,
            "_extra_tracks": extra_tracks,
            "_archived_tracks": archived_tracks,
        }
    finally:
        if logged_in:
            bs.logout()


def merge_track_days(new_days: list[dict[str, Any]], old_days: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """merge_preserve_settled for a model track: never demote a settled day."""
    old = {d["date"]: d for d in old_days if isinstance(d, dict) and isinstance(d.get("date"), str)}
    out: list[dict[str, Any]] = []
    seen = set()
    for d in new_days:
        o = old.get(d.get("date"))
        out.append(o if (o is not None and day_looks_settled(o)) else d)
        seen.add(d.get("date"))
    for date_, o in old.items():
        if date_ not in seen and day_looks_settled(o):
            out.append(o)
    out.sort(key=lambda d: d.get("date") or "")
    return out


def build_tracks(
    extra_tracks: dict[str, list[dict[str, Any]]],
    archived_tracks: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    """tracks.gpt -> top-level days (days_ref); tracks.<key>.days for other models.

    Each track may carry archived_days (e.g. a live batch replaced by a backfill
    for the same date): kept verbatim, excluded from grid and totals.
    """
    old_tracks: dict[str, Any] = {}
    if OUT_PATH.exists():
        try:
            old_tracks = json.loads(OUT_PATH.read_text(encoding="utf-8")).get("tracks") or {}
        except (OSError, json.JSONDecodeError, AttributeError):
            old_tracks = {}
    tracks: dict[str, Any] = {}
    for key in MODEL_KEYS:
        t: dict[str, Any] = {"id": key, "model": model_id_for(key), "label": MODEL_LABELS[key]}
        old_t = old_tracks.get(key) if isinstance(old_tracks.get(key), dict) else {}
        if key == "gpt":
            t["days_ref"] = "days"
        else:
            t["days"] = merge_track_days(extra_tracks.get(key) or [], old_t.get("days") or [])
        new_arch = (archived_tracks or {}).get(key) or []
        if new_arch or old_t.get("archived_days"):
            t["archived_days"] = merge_track_days(new_arch, old_t.get("archived_days") or [])
        tracks[key] = t
    return tracks


def main() -> int:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    payload = build_calendar()
    extra_tracks = payload.pop("_extra_tracks", {}) or {}
    archived_tracks = payload.pop("_archived_tracks", {}) or {}
    payload = merge_preserve_settled(payload)
    payload["tracks"] = build_tracks(extra_tracks, archived_tracks)
    payload["default_track"] = "gpt"
    for _k, _t in payload["tracks"].items():
        if _k != "gpt":
            print(f"[tracks] {_k}: days={len(_t.get('days') or [])}", flush=True)
    OUT_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    settled = [d for d in payload["days"] if d.get("status") == "settled"]
    pending = [d for d in payload["days"] if d.get("status") == "pending"]
    first = payload["days"][0]["date"] if payload["days"] else None
    last = payload["days"][-1]["date"] if payload["days"] else None
    mon = next((d for d in payload["days"] if d["date"] == "2026-09-08"), None)
    if mon is None:
        mon = next((d for d in payload["days"] if d["date"] == "2026-09-07"), None)
    if mon:
        print(
            f"[check] {mon.get('date')} status={mon.get('status')} "
            f"eq_sum={mon.get('eq_sum_chg_pct')} eq_avg={mon.get('eq_avg_chg_pct')} "
            f"buy={mon.get('buy_date')} sell={mon.get('sell_date')} "
            f"stocks={[ (s['code'], s.get('buy_open'), s.get('sell_open')) for s in mon.get('stocks', []) ]}",
            flush=True,
        )
    # Sample near-month diversity check
    near = [d for d in payload["days"] if d["date"] >= "2026-08-11"]
    if near:
        print(f"[check] near-month days={len(near)}", flush=True)
        for d in near[-8:]:
            codes = [s["code"] for s in d.get("stocks") or []]
            print(
                f"  {d['date']} {d.get('status')} sum={d.get('eq_sum_chg_pct')} avg={d.get('eq_avg_chg_pct')} {codes}",
                flush=True,
            )
    for day in payload["days"]:
        for s in day.get("stocks") or []:
            if s.get("code") == "000521" and s.get("buy_open") is not None:
                print(
                    f"[check] 000521 on {day['date']}: buy_open={s.get('buy_open')} "
                    f"sell_open={s.get('sell_open')}",
                    flush=True,
                )
    print(
        f"wrote {OUT_PATH} days={len(payload['days'])} "
        f"settled={len(settled)} pending={len(pending)} range={first}..{last} "
        f"price_basis=不复权",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
