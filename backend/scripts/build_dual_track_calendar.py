#!/usr/bin/env python3
"""Build dual-track watch_calendar.json: LLM (main) + multi_hit.

Keeps existing LLM days untouched as default track.
multi_hit days settled with same open→open logic / buy_date+sell_date
from the LLM calendar trading cadence.

Sources for multi_hit picks (priority):
  1. data/daily_picks/_shadow/YYYY-MM-DD.multi_hit.json
  2. CSV backfill (daily_picks_optimized.csv) — multi_hit replay codes
  3. else day marked shadow_missing (UI: 暂无影子)
"""
from __future__ import annotations

import csv
import json
import os
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
PICKS_DIR = DATA_DIR / "daily_picks"
SHADOW_DIR = PICKS_DIR / "_shadow"
CAL_PATH = DATA_DIR / "watch_calendar.json"
OUT_PATH = DATA_DIR / "watch_calendar.json"
MULTI_OUT = DATA_DIR / "watch_calendar_multi_hit.json"
CSV_CANDIDATES = [
    Path("/tmp/daily_picks_optimized.csv"),
    ROOT / "data" / "daily_picks_optimized.csv",
    Path("/workspace/baixiaoka-max-month-replay/daily_picks_optimized.csv"),
]
DETAILS_DIR = DATA_DIR / "details"
START_DATE = "2024-01-01"


def round_pct(v: float) -> float:
    return round(float(v), 4)



def load_main_pick_source(day: str) -> str | None:
    path = PICKS_DIR / f"{day}.json"
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    src = payload.get("source")
    return src.strip() if isinstance(src, str) and src.strip() else None

def load_csv_picks() -> dict[str, list[dict[str, str]]]:
    path = next((p for p in CSV_CANDIDATES if p.exists()), None)
    out: dict[str, list[dict[str, str]]] = {}
    if path is None:
        print("[dual] no optimized CSV found; shadow-only", flush=True)
        return out
    with path.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            day = (row.get("date") or "").strip()
            code = str(row.get("code") or "").zfill(6)
            name = (row.get("name") or code).strip()
            if not day or not code.isdigit():
                continue
            out.setdefault(day, []).append({"code": code, "name": name})
    for day in list(out):
        out[day] = out[day][:5]
    print(f"[dual] CSV picks days={len(out)} from {path}", flush=True)
    return out


def load_shadow(day: str) -> list[dict[str, str]] | None:
    path = SHADOW_DIR / f"{day}.multi_hit.json"
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"[dual] bad shadow {path}: {exc}", flush=True)
        return None
    symbols = payload.get("symbols") or []
    out: list[dict[str, str]] = []
    for item in symbols:
        if isinstance(item, str):
            code = item.zfill(6)
            out.append({"code": code, "name": code})
            continue
        if not isinstance(item, dict):
            continue
        code = str(item.get("code") or "").zfill(6)
        if not code.isdigit():
            continue
        name = item.get("name")
        if not isinstance(name, str) or not name.strip():
            name = code
        out.append({"code": code, "name": name.strip()})
    return out[:5] if out else None


def multi_hit_picks(day: str, csv_map: dict[str, list[dict[str, str]]]) -> tuple[list[dict[str, str]] | None, str]:
    shadow = load_shadow(day)
    if shadow:
        return shadow, "shadow"
    csv_p = csv_map.get(day)
    if csv_p:
        return csv_p, "csv_backfill"
    return None, "missing"


def load_detail_opens(code: str) -> dict[str, float]:
    path = DETAILS_DIR / f"{code}.json"
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if payload.get("price_basis") != "不复权":
        return {}  # legacy/unknown basis (may be 后复权): never use
    opens: dict[str, float] = {}
    for bar in payload.get("ohlcv_60d") or []:
        if not isinstance(bar, dict) or bar.get("src"):
            continue  # skip spot-appended signal-day bars (picker only)
        d = bar.get("date")
        o = bar.get("open")
        if isinstance(d, str) and o is not None:
            try:
                opens[d] = float(o)
            except (TypeError, ValueError):
                pass
    return opens


def fetch_tencent_opens(code: str, end_date: str) -> dict[str, float]:
    """Fallback: Tencent fq kline (raw day)."""
    if code.startswith(("5", "6", "9")):
        mkt = "sh"
    else:
        mkt = "sz"
    url = (
        "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
        f"?param={mkt}{code},day,{START_DATE},{end_date},640,"
    )
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        data = (payload.get("data") or {}).get(f"{mkt}{code}") or {}
        rows = data.get("day") or []  # raw only; never qfqday
    except Exception as exc:  # noqa: BLE001
        print(f"[dual] tencent fail {code}: {exc}", flush=True)
        return {}
    opens: dict[str, float] = {}
    for row in rows:
        if not row or len(row) < 2:
            continue
        try:
            opens[str(row[0])] = float(row[1])
        except (TypeError, ValueError):
            continue
    return opens


def baostock_opens(codes: list[str], end_date: str) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    try:
        import baostock as bs
    except ImportError:
        print("[dual] baostock missing; using details/tencent only", flush=True)
        return out
    lg = bs.login()
    if lg.error_code != "0":
        print(f"[dual] baostock login fail: {lg.error_msg}", flush=True)
        return out
    try:
        for code in codes:
            if code.startswith(("5", "6", "9")):
                bs_code = f"sh.{code}"
            else:
                bs_code = f"sz.{code}"
            rs = bs.query_history_k_data_plus(
                bs_code,
                "date,open",
                start_date=START_DATE,
                end_date=end_date,
                frequency="d",
                adjustflag="3",
            )
            opens: dict[str, float] = {}
            if rs.error_code == "0":
                while rs.next():
                    row = dict(zip(rs.fields, rs.get_row_data()))
                    o = row.get("open")
                    if o in ("", None):
                        continue
                    try:
                        opens[row["date"]] = float(o)
                    except (TypeError, ValueError):
                        continue
            if opens:
                out[code] = opens
    finally:
        bs.logout()
    return out


def settle_day(
    llm_day: dict[str, Any],
    picks: list[dict[str, str]] | None,
    opens_map: dict[str, dict[str, float]],
    origin: str,
) -> dict[str, Any]:
    buy_date = llm_day.get("buy_date")
    sell_date = llm_day.get("sell_date")
    signal = llm_day["date"]
    if not picks:
        return {
            "date": signal,
            "status": "pending",
            "buy_date": buy_date,
            "sell_date": sell_date,
            "eq_avg_chg_pct": None,
            "eq_sum_chg_pct": None,
            "n": 0,
            "stocks": [],
            "shadow_missing": True,
            "pick_origin": origin,
        }

    stocks: list[dict[str, Any]] = []
    settled_returns: list[float] = []
    pending = False
    if not buy_date or not sell_date:
        pending = True

    for p in picks:
        code = p["code"]
        name = p["name"]
        om = opens_map.get(code) or {}
        buy_open = om.get(buy_date) if buy_date else None
        sell_open = om.get(sell_date) if sell_date else None
        chg = None
        if buy_open is not None and sell_open is not None and buy_open != 0:
            chg = round_pct((sell_open - buy_open) / buy_open * 100)
            settled_returns.append(chg)
        else:
            pending = True
        stocks.append(
            {
                "code": code,
                "name": name,
                "buy_open": buy_open,
                "sell_open": sell_open,
                "chg_pct": chg,
            }
        )

    # Match LLM cadence: if sell not reached, pending even with partial
    if llm_day.get("status") == "pending":
        pending = True

    if pending or not settled_returns:
        return {
            "date": signal,
            "status": "pending",
            "buy_date": buy_date,
            "sell_date": sell_date,
            "eq_avg_chg_pct": None,
            "eq_sum_chg_pct": None,
            "n": len(picks),
            "stocks": stocks,
            "shadow_missing": False,
            "pick_origin": origin,
        }

    eq_sum = sum(settled_returns)
    eq_avg = eq_sum / len(settled_returns)
    return {
        "date": signal,
        "status": "settled",
        "buy_date": buy_date,
        "sell_date": sell_date,
        "eq_avg_chg_pct": round_pct(eq_avg),
        "eq_sum_chg_pct": round_pct(eq_sum),
        "n": len(settled_returns),
        "stocks": stocks,
        "shadow_missing": False,
        "pick_origin": origin,
    }


def multi_hit_enabled() -> bool:
    """multi_hit track removed 2026-09-28; MULTI_HIT_ENABLED=1 brings it back."""
    return (os.environ.get("MULTI_HIT_ENABLED") or "0").strip() == "1"


def main_llm_only(llm_cal: dict[str, Any]) -> int:
    """multi_hit disabled: no multi_hit picks fetched/settled, no tracks in output.

    llm days are taken as-is (top-level `days`, or tracks.llm if an older dual file
    is still present); only pick_source is annotated, exactly as before.
    """
    tracks = llm_cal.get("tracks") if isinstance(llm_cal.get("tracks"), dict) else {}
    llm_track = tracks.get("llm") if isinstance(tracks.get("llm"), dict) else None
    days = llm_track.get("days") if llm_track and isinstance(llm_track.get("days"), list) else llm_cal.get("days")
    llm_days = [d for d in (days or []) if isinstance(d, dict) and d.get("date")]
    for d in llm_days:
        src = load_main_pick_source(d["date"])
        if src:
            d["pick_source"] = src
        elif not d.get("pick_source"):
            d["pick_source"] = "unknown"
    out = {k: v for k, v in llm_cal.items() if k not in ("tracks", "default_track", "days")}
    out["days"] = llm_days
    # Keep per-model tracks (gpt/claude, 2026-09-29); drop legacy llm/multi_hit tracks.
    model_tracks = {k: v for k, v in tracks.items() if k not in ("llm", "multi_hit")}
    if model_tracks:
        out["tracks"] = model_tracks
        out["default_track"] = llm_cal.get("default_track") or "gpt"
    out["generated_at"] = datetime.now(timezone.utc).isoformat()
    OUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[dual] multi_hit disabled (MULTI_HIT_ENABLED!=1): wrote llm-only {OUT_PATH} days={len(llm_days)}", flush=True)
    return 0


def main() -> int:
    if not CAL_PATH.exists():
        print(f"missing {CAL_PATH}", file=sys.stderr)
        return 1
    llm_cal = json.loads(CAL_PATH.read_text(encoding="utf-8"))
    if not multi_hit_enabled():
        return main_llm_only(llm_cal)
    llm_days = [d for d in (llm_cal.get("days") or []) if isinstance(d, dict) and d.get("date")]
    csv_map = load_csv_picks()

    needed: list[str] = []
    plan: list[tuple[dict[str, Any], list[dict[str, str]] | None, str]] = []
    for day in llm_days:
        picks, origin = multi_hit_picks(day["date"], csv_map)
        plan.append((day, picks, origin))
        if picks:
            for p in picks:
                if p["code"] not in needed:
                    needed.append(p["code"])

    from datetime import date as _date

    end_date = max((d["date"] for d in llm_days), default="2026-09-21")
    # bump end through today so R+2 sell opens (and R+1 buys) can settle AM
    end_date = max(end_date, _date.today().isoformat())

    print(f"[dual] fetching opens for {len(needed)} codes… end={end_date}", flush=True)
    opens_map: dict[str, dict[str, float]] = baostock_opens(needed, end_date)
    for code in needed:
        # Always try details/tencent merge so today is not missed when baostock lags
        detail = load_detail_opens(code)
        if detail:
            # Fill gaps only: never let details override baostock raw opens
            # (details may be a stock_daily 后复权 fallback).
            om = opens_map.setdefault(code, {})
            for d_, o_ in detail.items():
                om.setdefault(d_, o_)
        if code not in opens_map or end_date not in opens_map.get(code, {}):
            tencent = fetch_tencent_opens(code, end_date)
            if tencent:
                opens_map.setdefault(code, {}).update(tencent)

    # Overlay watch_spot_opens.json (AM sync / Tencent fill) for today
    spot_path = DATA_DIR / "watch_spot_opens.json"
    if spot_path.exists():
        try:
            spot = json.loads(spot_path.read_text(encoding="utf-8"))
            spot_day = spot.get("date")
            if isinstance(spot_day, str) and isinstance(spot.get("opens"), dict):
                n_spot = 0
                for code, item in spot["opens"].items():
                    if not isinstance(item, dict) or item.get("open") is None:
                        continue
                    if float(item["open"]) <= 0:
                        continue
                    if code not in needed:
                        continue
                    opens_map.setdefault(code, {})[spot_day] = float(item["open"])
                    n_spot += 1
                print(f"[dual] spot overlay day={spot_day} codes={n_spot}", flush=True)
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
            print(f"[dual] spot overlay skip: {exc}", flush=True)

    mh_days: list[dict[str, Any]] = []
    n_shadow = n_csv = n_miss = 0
    for llm_day, picks, origin in plan:
        if origin == "shadow":
            n_shadow += 1
        elif origin == "csv_backfill":
            n_csv += 1
        else:
            n_miss += 1
        mh_days.append(settle_day(llm_day, picks, opens_map, origin))

    # latest symbols for multi_hit = last non-missing day
    mh_symbols = llm_cal.get("symbols") or []
    for d in reversed(mh_days):
        if d.get("stocks") and not d.get("shadow_missing"):
            mh_symbols = [{"code": s["code"], "name": s["name"]} for s in d["stocks"]]
            break

    multi_payload = {
        "symbols": mh_symbols,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "note": llm_cal.get("note"),
        "price_basis": llm_cal.get("price_basis", "不复权"),
        "source": "multi_hit",
        "days": mh_days,
    }
    MULTI_OUT.write_text(json.dumps(multi_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    for d in llm_days:
        src = load_main_pick_source(d["date"])
        if src:
            d["pick_source"] = src
        elif not d.get("pick_source"):
            d["pick_source"] = "unknown"
    for d in mh_days:
        if d.get("shadow_missing"):
            d["pick_source"] = "missing"
        else:
            d.setdefault("pick_source", "multi_hit")

    dual = {
        "symbols": llm_cal.get("symbols") or [],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "note": llm_cal.get("note"),
        "price_basis": llm_cal.get("price_basis", "不复权"),
        "default_track": "llm",
        "days": llm_days,  # backward-compat = main track
        "tracks": {
            "llm": {
                "id": "llm",
                "label": "主轨 Top5",
                "source": "daily_picks",
                "days": llm_days,
            },
            "multi_hit": {
                "id": "multi_hit",
                "label": "multi_hit",
                "source": "multi_hit",
                "days": mh_days,
            },
        },
    }
    # backup then write
    bak = CAL_PATH.with_suffix(".json.bak.pre_dual_track")
    if not bak.exists():
        bak.write_text(CAL_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    OUT_PATH.write_text(json.dumps(dual, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    settled_mh = sum(1 for d in mh_days if d.get("status") == "settled")
    print(
        f"[dual] wrote {OUT_PATH} + {MULTI_OUT} "
        f"llm_days={len(llm_days)} mh_settled={settled_mh} "
        f"origin shadow={n_shadow} csv={n_csv} missing={n_miss}",
        flush=True,
    )
    for d in mh_days[-5:]:
        codes = [s["code"] for s in d.get("stocks") or []]
        print(
            f"  mh {d['date']} {d.get('status')} sum={d.get('eq_sum_chg_pct')} "
            f"origin={d.get('pick_origin')} miss={d.get('shadow_missing')} {codes}",
            flush=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
