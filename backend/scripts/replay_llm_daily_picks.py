#!/usr/bin/env python3
"""Replay LLM Top5 rerank for historical signal days (feature_ver=v1.1, prompt_ver=v1.2).

For each day in range:
  1. Backup existing daily_picks
  2. Rebuild full rule-scan union as-of that day (all 8 strategies)
  3. Build v1.1 features (week_oc sliced date<=R from DB — no look-ahead)
  4. LLM rerank → rewrite daily_picks (source=llm_rerank); fail → rule_order
  5. Write comparison JSON under data/daily_picks/_llm_replay/

Does NOT call export_watch_calendar / push (caller does that after).

Usage:
  .venv/bin/python scripts/replay_llm_daily_picks.py --start 2026-09-02 --end 2026-09-10
  .venv/bin/python scripts/replay_llm_daily_picks.py --start 2026-09-10 --end 2026-09-10 --use-latest
"""

from __future__ import annotations

import argparse
import csv
import json
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from sequoia_x.core.config import get_settings  # noqa: E402
from sequoia_x.data.engine import DataEngine  # noqa: E402
from sequoia_x.strategy.bowl_rebound import BowlReboundStrategy  # noqa: E402
from sequoia_x.strategy.high_tight_flag import HighTightFlagStrategy  # noqa: E402
from sequoia_x.strategy.limit_up_shakeout import LimitUpShakeoutStrategy  # noqa: E402
from sequoia_x.strategy.ma_volume import MaVolumeStrategy  # noqa: E402
from sequoia_x.strategy.private_placement import PrivatePlacementStrategy  # noqa: E402
from sequoia_x.strategy.rps_breakout import RpsBreakoutStrategy  # noqa: E402
from sequoia_x.strategy.turtle_trade import TurtleTradeStrategy  # noqa: E402
from sequoia_x.strategy.uptrend_limit_down import UptrendLimitDownStrategy  # noqa: E402

import backfill_daily_picks as bf  # noqa: E402
from llm_rerank import (  # noqa: E402
    FEATURE_VER,
    PROMPT_VER,
    SAMPLE_CODES_PER_STRATEGY,
    WEEK_OC_BARS,
    build_why,
    call_chat_completions,
    build_messages,
    is_st_or_delisted,
    resolve_api_config,
    strategy_blurb,
    strategy_ui_name,
    validate_strategy_review,
    validate_top5,
    week_oc_from_ohlcv,
)

PICKS_DIR = ROOT / "data" / "daily_picks"
BACKUP_DIR = PICKS_DIR / "_pre_llm_rerank"
COMPARE_DIR = PICKS_DIR / "_llm_replay"
DB_PATH = ROOT / "data" / "sequoia_v2.db"
SW_MAP = ROOT / "data" / "sw_industry_map.csv"
LATEST_PATH = ROOT / "data" / "latest.json"


def load_sw_map() -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    if not SW_MAP.is_file():
        return out
    with SW_MAP.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            sym = (row.get("symbol") or "").strip().zfill(6)
            if len(sym) != 6:
                continue
            out[sym] = {
                "industry_group": (row.get("industry_group") or "").strip() or "未分类",
                "board": "",
                "name": (row.get("name") or "").strip(),
            }
    return out


def derive_board(symbol: str) -> str:
    if symbol.startswith("688"):
        return "科创板"
    if symbol.startswith(("300", "301")):
        return "创业板"
    if symbol.startswith(("8", "4")):
        return "北交所"
    if symbol.startswith("60"):
        return "沪市主板"
    return "深市主板"


def full_union_asof(settings: Any, base_engine: DataEngine, as_of: str) -> dict[str, list[str]]:
    """Run all 8 strategies as-of; return {strategy_class: [codes...]}."""
    engine = bf.AsOfEngine(DB_PATH, as_of, base_engine)
    try:
        strategy_ctors: list[tuple[str, Any]] = [
            ("MaVolumeStrategy", lambda: MaVolumeStrategy(engine=engine, settings=settings)),
            ("TurtleTradeStrategy", lambda: bf.AsOfTurtleTradeStrategy(engine=engine, settings=settings)),
            ("HighTightFlagStrategy", lambda: HighTightFlagStrategy(engine=engine, settings=settings)),
            ("LimitUpShakeoutStrategy", lambda: LimitUpShakeoutStrategy(engine=engine, settings=settings)),
            ("UptrendLimitDownStrategy", lambda: UptrendLimitDownStrategy(engine=engine, settings=settings)),
            ("RpsBreakoutStrategy", lambda: bf.AsOfRpsBreakoutStrategy(engine=engine, settings=settings, as_of=as_of)),
            ("PrivatePlacementStrategy", lambda: bf.AsOfPrivatePlacementStrategy(engine=engine, settings=settings, as_of=as_of)),
            ("BowlReboundStrategy", lambda: bf.AsOfBowlReboundStrategy(engine=engine, settings=settings)),
        ]
        result: dict[str, list[str]] = {}
        for name, ctor in strategy_ctors:
            t0 = time.time()
            try:
                selected = [str(c).zfill(6) for c in (ctor().run() or [])]
            except Exception as exc:
                print(f"[warn] {as_of} {name} failed: {exc}", file=sys.stderr, flush=True)
                selected = []
            result[name] = selected
            print(f"  {name}: {len(selected)} in {time.time()-t0:.1f}s", flush=True)
        return result
    finally:
        engine.close()


def strategies_from_latest() -> dict[str, list[str]]:
    latest = json.loads(LATEST_PATH.read_text(encoding="utf-8"))
    out: dict[str, list[str]] = {}
    for s in latest.get("strategies") or []:
        name = str(s.get("name") or "")
        out[name] = [str(c).zfill(6) for c in (s.get("symbols") or [])]
    return out


def ordered_union(strategy_map: dict[str, list[str]]) -> list[str]:
    order = [
        "MaVolumeStrategy",
        "TurtleTradeStrategy",
        "HighTightFlagStrategy",
        "LimitUpShakeoutStrategy",
        "UptrendLimitDownStrategy",
        "RpsBreakoutStrategy",
        "PrivatePlacementStrategy",
        "BowlReboundStrategy",
    ]
    seen: list[str] = []
    for name in order:
        for code in strategy_map.get(name) or []:
            if code not in seen:
                seen.append(code)
    # any unexpected keys
    for name, codes in strategy_map.items():
        if name in order:
            continue
        for code in codes:
            if code not in seen:
                seen.append(code)
    return seen


def hits_map(strategy_map: dict[str, list[str]]) -> dict[str, list[str]]:
    m: dict[str, list[str]] = {}
    for name, codes in strategy_map.items():
        for code in codes:
            m.setdefault(code, [])
            if name not in m[code]:
                m[code].append(name)
    return m


def load_week_oc_details(code: str, as_of: str, n: int = WEEK_OC_BARS) -> list[dict[str, Any]]:
    """Prefer details ohlcv_60d (不复权), sliced to date<=as_of tip."""
    path = ROOT / "data" / "details" / f"{code}.json"
    if not path.is_file():
        return []
    try:
        det = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    ohlcv = det.get("ohlcv_60d") or []
    filtered = [b for b in ohlcv if str(b.get("date") or "") <= as_of]
    return week_oc_from_ohlcv(filtered, n)


def load_week_oc_db(conn: sqlite3.Connection, code: str, as_of: str, n: int = WEEK_OC_BARS) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT date, open, close FROM stock_daily
        WHERE symbol = ? AND date <= ? AND open IS NOT NULL AND close IS NOT NULL
        ORDER BY date DESC
        LIMIT ?
        """,
        (code, as_of, n),
    ).fetchall()
    bars = [{"date": r[0], "open": r[1], "close": r[2]} for r in reversed(rows)]
    return bars


def chg_pct_from_week(week_oc: list[dict[str, Any]]) -> float | None:
    if len(week_oc) < 2:
        return None
    prev = week_oc[-2].get("close", week_oc[-2].get("c"))
    cur = week_oc[-1].get("close", week_oc[-1].get("c"))
    try:
        prev_f = float(prev)
        cur_f = float(cur)
    except (TypeError, ValueError):
        return None
    if prev_f == 0:
        return None
    return (cur_f - prev_f) / prev_f


def build_candidates_asof(
    strategy_map: dict[str, list[str]],
    names: dict[str, str],
    sw: dict[str, dict[str, str]],
    as_of: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    union = ordered_union(strategy_map)
    hits = hits_map(strategy_map)
    dropped: list[str] = []
    cands: list[dict[str, Any]] = []
    with sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True) as conn:
        for code in union:
            name = names.get(code) or (sw.get(code) or {}).get("name") or code
            if is_st_or_delisted(name):
                dropped.append(code)
                continue
            hit_list = hits.get(code) or []
            ig = (sw.get(code) or {}).get("industry_group") or "未分类"
            week_oc = load_week_oc_details(code, as_of)
            if not week_oc:
                week_oc = load_week_oc_db(conn, code, as_of)
            chg = chg_pct_from_week(week_oc)
            row: dict[str, Any] = {
                "code": code,
                "why": build_why(hit_list) if hit_list else "规则并集候选",
                "industry_group": ig,
                "week_oc": week_oc,
                "name": name,
                "strategies": [strategy_ui_name(s) for s in hit_list],
                "n_hit": len(hit_list),
                "board": derive_board(code),
            }
            if isinstance(chg, float):
                row["chg_pct"] = round(chg, 4)
            cands.append(row)
    stats = {
        "union_count": len(union),
        "candidate_count": len(cands),
        "dropped_st_count": len(dropped),
        "dropped_st": dropped,
        "feature_ver": FEATURE_VER,
        "as_of": as_of,
    }
    return cands, stats


def rule_top5_symbols(
    strategy_map: dict[str, list[str]], names: dict[str, str]
) -> list[dict[str, str]]:
    codes = ordered_union(strategy_map)[:5]
    return [{"code": c, "name": names.get(c) or c} for c in codes]


def summaries_from_strategy_map(strategy_map: dict[str, list[str]]) -> list[dict[str, Any]]:
    """Build v1.2 strategy_summaries from as-of strategy_map (class_name → codes)."""
    out: list[dict[str, Any]] = []
    for cls, codes_raw in strategy_map.items():
        codes: list[str] = []
        for code in codes_raw or []:
            c = str(code).zfill(6)
            if c not in codes:
                codes.append(c)
        ui = strategy_ui_name(cls)
        blurb = strategy_blurb(cls)
        if len(blurb) > 40:
            blurb = blurb[:40]
        out.append(
            {
                "strategy_id": cls,
                "strategy": ui,
                "n_hits": len(codes),
                "sample_codes": codes[:SAMPLE_CODES_PER_STRATEGY],
                "rule_blurb": blurb,
            }
        )
    return out


def llm_pick(
    candidates: list[dict[str, Any]],
    names: dict[str, str],
    strategy_summaries: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    cfg = resolve_api_config()
    if not cfg["api_key"]:
        return {
            "ok": False,
            "error": "missing API key",
            "source": "rule_order",
            "model": cfg["model"],
            "prompt_ver": PROMPT_VER,
        }
    if len(candidates) < 5:
        return {
            "ok": False,
            "error": f"candidates < 5 ({len(candidates)})",
            "source": "rule_order",
            "model": cfg["model"],
            "prompt_ver": PROMPT_VER,
            "candidate_count": len(candidates),
        }
    summaries = strategy_summaries or []
    messages = build_messages(candidates, summaries)
    try:
        content = call_chat_completions(
            messages,
            api_key=cfg["api_key"],
            base_url=cfg["base_url"],
            model=cfg["model"],
            temperature=cfg["temperature"],
            timeout=cfg["timeout"],
            json_mode=bool(cfg.get("json_mode", True)),
        )
        from llm_rerank import _extract_json_object

        payload = _extract_json_object(content)
        strategy_review = validate_strategy_review(payload, summaries)
        top5 = validate_top5(payload, {c["code"] for c in candidates})
    except Exception as exc:
        return {
            "ok": False,
            "error": str(exc),
            "source": "rule_order",
            "model": cfg["model"],
            "prompt_ver": PROMPT_VER,
            "candidate_count": len(candidates),
        }
    name_by = {c["code"]: c.get("name") or names.get(c["code"]) or c["code"] for c in candidates}
    symbols = []
    for r in top5:
        entry = {
            "code": r["code"],
            "name": str(name_by.get(r["code"]) or r["code"]),
            "reason": r["reason"],
        }
        if r.get("explain"):
            entry["explain"] = r["explain"]
        symbols.append(entry)
    out: dict[str, Any] = {
        "ok": True,
        "symbols": symbols,
        "source": "llm_rerank",
        "model": cfg["model"],
        "feature_ver": FEATURE_VER,
        "prompt_ver": PROMPT_VER,
        "strategy_review": strategy_review,
        "candidate_count": len(candidates),
    }
    note = payload.get("rejected_note")
    if isinstance(note, str) and note.strip():
        out["rejected_note"] = note.strip()[:200]
    return out


def backup_pick(day: str) -> dict[str, Any] | None:
    src = PICKS_DIR / f"{day}.json"
    if not src.exists():
        return None
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    payload = json.loads(src.read_text(encoding="utf-8"))
    (BACKUP_DIR / f"{day}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return payload


def write_pick(day: str, symbols: list[dict[str, str]], source: str, extra: dict[str, Any]) -> Path:
    PICKS_DIR.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {"date": day, "symbols": symbols, "source": source}
    payload.update(extra)
    path = PICKS_DIR / f"{day}.json"
    import sys as _sys  # pick_guard (PM 2026-09-29): lock at 09:25 next trading day + re-pick records
    _sys.path.insert(0, str(Path(__file__).resolve().parent))
    import pick_guard as _pg
    _pg.safe_guard_write(path, day, payload)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2026-09-02")
    parser.add_argument("--end", default="2026-09-10")
    parser.add_argument(
        "--use-latest",
        action="store_true",
        help="For end day only if matches, use data/latest.json union instead of as-of scan",
    )
    parser.add_argument("--days", default="", help="Comma-separated explicit days (overrides start/end)")
    args = parser.parse_args(argv)

    cfg = resolve_api_config()
    print(
        f"[replay] model={cfg['model']} base={cfg['base_url']} key_set={bool(cfg['api_key'])} "
        f"feature_ver={FEATURE_VER} prompt_ver={PROMPT_VER}",
        flush=True,
    )
    if not cfg["api_key"]:
        print("[error] missing LLM API key", file=sys.stderr)
        return 1

    if args.days.strip():
        days = [d.strip() for d in args.days.split(",") if d.strip()]
    else:
        days = bf.trading_days(args.start, args.end)
    print(f"[replay] days={days}", flush=True)

    settings = get_settings()
    base_engine = DataEngine(settings)
    names = bf.load_names()
    sw = load_sw_map()
    COMPARE_DIR.mkdir(parents=True, exist_ok=True)

    summary: list[dict[str, Any]] = []

    for day in days:
        print(f"===== {day} =====", flush=True)
        old_payload = backup_pick(day)
        old_codes = []
        if old_payload:
            old_codes = [
                str(s.get("code") if isinstance(s, dict) else s).zfill(6)
                for s in (old_payload.get("symbols") or [])
            ]

        use_latest = bool(args.use_latest) and LATEST_PATH.exists() and day == days[-1]
        # Prefer latest.json when its generated calendar date matches day
        if LATEST_PATH.exists() and not args.use_latest:
            try:
                gen = json.loads(LATEST_PATH.read_text(encoding="utf-8")).get("generated_at") or ""
                # generated_at is UTC iso; rough check for date in Shanghai by reading quotes tip
                # Safer: only use --use-latest flag or if day == max trading day with same tip
            except Exception:
                gen = ""
        if args.use_latest and day == sorted(days)[-1] and LATEST_PATH.exists():
            print(f"  using latest.json union for {day}", flush=True)
            strategy_map = strategies_from_latest()
        else:
            print(f"  scanning full as-of union for {day} ...", flush=True)
            t0 = time.time()
            strategy_map = full_union_asof(settings, base_engine, day)
            print(f"  scan done in {time.time()-t0:.1f}s", flush=True)

        cands, stats = build_candidates_asof(strategy_map, names, sw, day)
        print(
            f"  features union={stats['union_count']} candidates={stats['candidate_count']} "
            f"dropped_st={stats['dropped_st_count']}",
            flush=True,
        )

        rule_syms = rule_top5_symbols(strategy_map, names)
        summaries = summaries_from_strategy_map(strategy_map)
        result = llm_pick(cands, names, summaries)
        if result.get("ok"):
            symbols = result["symbols"]
            source = "llm_rerank"
            extra = {
                "model": result.get("model"),
                "feature_ver": FEATURE_VER,
                "prompt_ver": PROMPT_VER,
                "candidate_count": result.get("candidate_count"),
            }
            if result.get("strategy_review"):
                extra["strategy_review"] = result["strategy_review"]
            if result.get("rejected_note"):
                extra["rejected_note"] = result["rejected_note"]
            print(f"  LLM ok → {[s['code'] for s in symbols]}", flush=True)
        else:
            symbols = rule_syms
            source = "rule_order"
            extra = {
                "model": result.get("model") or cfg["model"],
                "feature_ver": FEATURE_VER,
                "prompt_ver": PROMPT_VER,
                "candidate_count": stats["candidate_count"],
                "fallback_reason": result.get("error") or "llm_failed",
            }
            print(f"  FALLBACK rule_order reason={extra['fallback_reason']}", flush=True)

        path = write_pick(day, symbols, source, extra)
        new_codes = [s["code"] for s in symbols]
        row = {
            "date": day,
            "old_top5": old_codes,
            "new_top5": new_codes,
            "source": source,
            "candidate_count": stats["candidate_count"],
            "union_count": stats["union_count"],
            "model": extra.get("model"),
            "path": str(path),
        }
        summary.append(row)
        (COMPARE_DIR / f"{day}.json").write_text(
            json.dumps({**row, "new_symbols": symbols, "stats": stats}, ensure_ascii=False, indent=2)
            + "\n",
            encoding="utf-8",
        )

    out_path = COMPARE_DIR / "summary.json"
    out_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[replay] summary → {out_path}", flush=True)
    for row in summary:
        print(
            f"  {row['date']}: {row['old_top5']} → {row['new_top5']} ({row['source']})",
            flush=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
