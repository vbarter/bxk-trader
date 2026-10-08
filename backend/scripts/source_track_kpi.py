#!/usr/bin/env python3
"""序1 · source 分轨 KPI（样本卫生）.

Hard rule — a day counts as「真 LLM」(track=llm_rerank) only when ALL hold:
  * pick_source / source == llm_rerank (successful LLM call; not fallback)
  * status == settled with complete T+1 open buy → T+2 open sell legs
  * n == 5 (full basket)

Tracks (normalized):
  llm_rerank | rule_order | asof_replay | fallback_* | multi_hit_shadow | paused | coverage_fail | other

Mixed product totals (实际推荐 / 全部回溯) MUST NOT be labeled llm_rerank.
This script writes:
  * data/source_track_kpi/<month>.json  — daily table + monthly summary
  * annotates watch_calendar.json with kpi_by_source (+ per-day source_track)
  * optional: data/source_track_kpi/sep2026_reproduce.json from materials picks

Usage:
  source_track_kpi.py                         # annotate live calendar + write monthly files
  source_track_kpi.py --month 2026-09
  source_track_kpi.py --reproduce-sep-materials /path/to/raw/daily_picks
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
CAL_PATH = DATA / "watch_calendar.json"
PICKS_DIR = DATA / "daily_picks"
SHADOW_DIR = PICKS_DIR / "_shadow"
OUT_DIR = DATA / "source_track_kpi"

TRACK_LLM = "llm_rerank"
TRACK_RULE = "rule_order"
TRACK_ASOF = "asof_replay"
TRACK_MH_SHADOW = "multi_hit_shadow"
TRACK_PAUSED = "paused"
TRACK_COVERAGE = "coverage_fail"
TRACK_OTHER = "other"

DOC_NOTE = (
    "对外 / 对内「真 LLM 月收益」只用 track=llm_rerank 且 settled 且 n=5。"
    "材料对照：Sep 真 LLM ≈ +31.48%/11 日；产品日历混轨（含 asof/rule）≈ −1.90%/12 日。"
    "实际推荐 / 全部回溯 是产品口径，禁止标成 llm_rerank。"
)


def normalize_track(raw: str | None, *, fallback_reason: str | None = None) -> str:
    src = (raw or "").strip()
    if not src:
        return TRACK_OTHER
    low = src.lower()
    if low == "llm_rerank":
        # A successful LLM day that was later found to be a timeout fallback should
        # already have source=rule_order; if fallback_reason is present with llm label,
        # treat as fallback_rule_order for hygiene.
        if fallback_reason:
            return f"fallback_{TRACK_RULE}"
        return TRACK_LLM
    if low.startswith("asof"):
        return TRACK_ASOF
    if low == "rule_order":
        if fallback_reason:
            return f"fallback_{TRACK_RULE}"
        return TRACK_RULE
    if low.startswith("fallback"):
        return low if low.startswith("fallback_") else f"fallback_{low}"
    if low in {"multi_hit", "multi_hit_shadow"}:
        return TRACK_MH_SHADOW
    if low == "paused":
        return TRACK_PAUSED
    if low in {"coverage_fail", "skipped"}:
        return TRACK_COVERAGE
    return TRACK_OTHER


def load_pick_meta(picks_dir: Path) -> dict[str, dict[str, Any]]:
    """date -> {source, fallback_reason, n_symbols, pick_status} from pick files."""
    out: dict[str, dict[str, Any]] = {}
    if not picks_dir.exists():
        return out
    for path in sorted(picks_dir.glob("*.json")):
        if path.name.startswith("_") or ".coverage_fail" in path.name:
            continue
        if not path.stem[:4].isdigit():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        day = str(payload.get("date") or path.stem)[:10]
        syms = payload.get("symbols") or []
        out[day] = {
            "source": payload.get("source"),
            "fallback_reason": payload.get("fallback_reason"),
            "n_symbols": len(syms) if isinstance(syms, list) else 0,
            "pick_status": payload.get("pick_status"),
            "path": str(path),
        }
    # coverage_fail markers
    for path in sorted(picks_dir.glob("*.coverage_fail.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        day = str(payload.get("date") or path.name.split(".")[0])[:10]
        out[day] = {
            "source": "coverage_fail",
            "fallback_reason": payload.get("pause_reason"),
            "n_symbols": 0,
            "pick_status": "skipped",
            "path": str(path),
        }
    return out


def load_shadow_days(shadow_dir: Path = SHADOW_DIR) -> set[str]:
    days: set[str] = set()
    if not shadow_dir.exists():
        return days
    for path in shadow_dir.glob("*.multi_hit.json"):
        day = path.name.split(".")[0]
        if len(day) == 10:
            days.add(day)
    return days


def complete_legs(day: dict[str, Any]) -> bool:
    """T+1 buy open + T+2 sell open settleable (settled days already cleared the gate)."""
    if day.get("status") != "settled":
        return False
    buy = day.get("buy_date")
    sell = day.get("sell_date")
    if not (isinstance(buy, str) and len(buy) >= 10 and isinstance(sell, str) and len(sell) >= 10):
        # Some settled rows may omit dates but still have eq_sum — require eq_sum then.
        return isinstance(day.get("eq_sum_chg_pct"), (int, float))
    return buy < sell


def is_true_llm(day: dict[str, Any], track: str) -> bool:
    if track != TRACK_LLM:
        return False
    if day.get("status") != "settled":
        return False
    if int(day.get("n") or 0) != 5:
        return False
    if not complete_legs(day):
        return False
    if day.get("paused") or day.get("pick_status") == "paused":
        return False
    if not isinstance(day.get("eq_sum_chg_pct"), (int, float)):
        return False
    return True


def classify_day(
    day: dict[str, Any],
    pick_meta: dict[str, dict[str, Any]],
    shadow_days: set[str],
) -> str:
    date = str(day.get("date") or "")[:10]
    meta = pick_meta.get(date) or {}
    raw = day.get("pick_source") or day.get("source") or meta.get("source")
    fb = day.get("fallback_reason") or meta.get("fallback_reason")
    if day.get("paused") or day.get("pick_status") == "paused" or raw == "paused":
        return TRACK_PAUSED
    track = normalize_track(str(raw) if raw else None, fallback_reason=str(fb) if fb else None)
    # Shadow multi_hit never overrides main-day track; recorded separately in shadow summary.
    _ = shadow_days
    return track


def iter_model_days(cal: dict[str, Any]) -> list[tuple[str, list[dict[str, Any]]]]:
    """Yield (model_key, days) for gpt (top-level days) and other model tracks."""
    out: list[tuple[str, list[dict[str, Any]]]] = []
    tracks = cal.get("tracks") if isinstance(cal.get("tracks"), dict) else {}
    gpt = tracks.get("gpt") if isinstance(tracks.get("gpt"), dict) else {}
    if gpt.get("days_ref") == "days" or not isinstance(gpt.get("days"), list):
        out.append(("gpt", [d for d in (cal.get("days") or []) if isinstance(d, dict)]))
    else:
        out.append(("gpt", [d for d in (gpt.get("days") or []) if isinstance(d, dict)]))
    for key, t in tracks.items():
        if key in {"gpt", "llm", "multi_hit"}:
            continue
        if isinstance(t, dict) and isinstance(t.get("days"), list):
            out.append((key, [d for d in t["days"] if isinstance(d, dict)]))
    return out


def summarize_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    settled = [r for r in rows if r.get("true_llm") or (
        r.get("status") == "settled" and isinstance(r.get("eq_sum_chg_pct"), (int, float)) and r.get("n") == 5
    )]
    # For non-llm tracks use settled+n5; for llm use true_llm flag already filtered by caller
    ssum = sum(float(r["eq_sum_chg_pct"]) for r in settled if isinstance(r.get("eq_sum_chg_pct"), (int, float)))
    return {
        "n_days": len(settled),
        "sum_eq_sum": round(ssum, 4),
        "dates": [r["date"] for r in settled],
    }


def build_for_model(
    model_key: str,
    days: list[dict[str, Any]],
    pick_meta: dict[str, dict[str, Any]],
    shadow_days: set[str],
    month: str | None,
) -> dict[str, Any]:
    daily: list[dict[str, Any]] = []
    by_track: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for day in days:
        date = str(day.get("date") or "")[:10]
        if month and not date.startswith(month):
            continue
        track = classify_day(day, pick_meta, shadow_days)
        day["source_track"] = track  # annotate in-place for calendar write
        row = {
            "date": date,
            "model": model_key,
            "source_track": track,
            "pick_source": day.get("pick_source") or day.get("source") or (pick_meta.get(date) or {}).get("source"),
            "status": day.get("status"),
            "n": day.get("n"),
            "eq_sum_chg_pct": day.get("eq_sum_chg_pct"),
            "buy_date": day.get("buy_date"),
            "sell_date": day.get("sell_date"),
            "backfill": bool(day.get("backfill")),
            "true_llm": is_true_llm(day, track),
            "has_shadow_multi_hit": date in shadow_days,
        }
        daily.append(row)
        by_track[track].append(row)

    # True LLM monthly = only true_llm rows
    true_rows = [r for r in daily if r["true_llm"]]
    true_sum = round(sum(float(r["eq_sum_chg_pct"]) for r in true_rows), 4)

    track_summaries: dict[str, Any] = {}
    for track, rows in sorted(by_track.items()):
        if track == TRACK_LLM:
            settled = [r for r in rows if r["true_llm"]]
        else:
            settled = [
                r for r in rows
                if r.get("status") == "settled"
                and int(r.get("n") or 0) == 5
                and isinstance(r.get("eq_sum_chg_pct"), (int, float))
            ]
        track_summaries[track] = {
            "n_days": len(settled),
            "sum_eq_sum": round(sum(float(r["eq_sum_chg_pct"]) for r in settled), 4),
            "dates": [r["date"] for r in settled],
            "label": (
                "真 LLM（llm_rerank + settled + n=5）"
                if track == TRACK_LLM
                else track
            ),
        }

    # Mixed product totals for the same month — labeled explicitly NOT llm_rerank
    mixed = [
        r for r in daily
        if r.get("status") == "settled"
        and int(r.get("n") or 0) == 5
        and isinstance(r.get("eq_sum_chg_pct"), (int, float))
    ]
    mixed_sum = round(sum(float(r["eq_sum_chg_pct"]) for r in mixed), 4)

    return {
        "model": model_key,
        "month": month,
        "daily": daily,
        "by_track": track_summaries,
        "true_llm": {
            "track": TRACK_LLM,
            "rule": "source=llm_rerank AND settled AND n=5 AND complete buy/sell legs",
            "n_days": len(true_rows),
            "sum_eq_sum": true_sum,
            "dates": [r["date"] for r in true_rows],
        },
        "product_mixed_settled_n5": {
            "label": "产品混轨 settled n=5（禁止标成 llm_rerank）",
            "n_days": len(mixed),
            "sum_eq_sum": mixed_sum,
            "dates": [r["date"] for r in mixed],
            "must_not_label_as": TRACK_LLM,
        },
        "shadow_multi_hit_days": sorted(d for d in shadow_days if (not month or d.startswith(month))),
    }


def annotate_calendar(cal: dict[str, Any], reports: dict[str, dict[str, Any]]) -> None:
    """Attach kpi_by_source; never put mixed totals under llm_rerank key."""
    kpi: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "note": DOC_NOTE,
        "models": {},
    }
    for model_key, rep in reports.items():
        by_track = rep.get("by_track") or {}
        # Only pure tracks under by_track; mixed is sibling with explicit label.
        kpi["models"][model_key] = {
            "by_track": by_track,
            "true_llm": rep.get("true_llm"),
            "product_mixed_settled_n5": rep.get("product_mixed_settled_n5"),
            "shadow_multi_hit_days": rep.get("shadow_multi_hit_days"),
        }
        # Convenience: top-level true_llm for default gpt
        if model_key == "gpt":
            kpi["true_llm"] = rep.get("true_llm")
            kpi["product_mixed_settled_n5"] = rep.get("product_mixed_settled_n5")
    cal["kpi_by_source"] = kpi
    # Strip any legacy mislabel if present
    if "tracks" in cal and isinstance(cal["tracks"], dict):
        for key, t in cal["tracks"].items():
            if not isinstance(t, dict):
                continue
            # Ensure model-track totals stay labeled as product actual/rerun, not llm_rerank
            tot = t.get("totals")
            if isinstance(tot, dict):
                tot["label"] = tot.get("label") or "product_actual_rerun"
                tot["not_llm_rerank"] = True
                tot["see"] = "kpi_by_source.true_llm for 真 LLM"


def write_month_files(reports: dict[str, dict[str, Any]], month: str) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"{month}.json"
    payload = {
        "month": month,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "note": DOC_NOTE,
        "models": reports,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def reproduce_sep_materials(picks_dir: Path, cal_path: Path) -> dict[str, Any]:
    """Rebuild Sep split using materials pick sources + calendar settlement numbers."""
    cal = json.loads(cal_path.read_text(encoding="utf-8"))
    pick_meta = load_pick_meta(picks_dir)
    shadow_days = load_shadow_days()
    # Prefer materials source over calendar pick_source
    days = [d for d in (cal.get("days") or []) if isinstance(d, dict) and str(d.get("date", "")).startswith("2026-09")]
    for d in days:
        meta = pick_meta.get(str(d.get("date"))[:10])
        if meta and meta.get("source"):
            d = dict(d)
    # Use materials sources for classification by temporarily overlaying pick_source
    overlay_days: list[dict[str, Any]] = []
    for d in days:
        dd = dict(d)
        meta = pick_meta.get(str(d.get("date"))[:10]) or {}
        if meta.get("source"):
            dd["pick_source"] = meta["source"]
            if meta.get("fallback_reason"):
                dd["fallback_reason"] = meta["fallback_reason"]
        overlay_days.append(dd)
    # Empty pick_meta for classify so overlay pick_source wins
    rep = build_for_model("gpt", overlay_days, {}, shadow_days, "2026-09")
    # Materials expected (from sep2026_summary)
    expected = {
        "A_true_llm_rerank_settled": {"sum_eq_sum": 31.4756, "n_days": 11},
        "mixed_calendar_unref_sep": {"sum_eq_sum": -1.9042, "n_days": 12},
        "asof_or_rule": {"sum_eq_sum": -10.9464, "n_days": 2, "dates": ["2026-09-01", "2026-09-11"]},
    }
    true = rep["true_llm"]
    asof_rule_dates = set()
    for track in (TRACK_ASOF, TRACK_RULE, "fallback_rule_order"):
        asof_rule_dates.update((rep["by_track"].get(track) or {}).get("dates") or [])
    return {
        "note": DOC_NOTE,
        "materials_picks_dir": str(picks_dir),
        "expected": expected,
        "computed_true_llm": true,
        "computed_by_track": rep["by_track"],
        "computed_product_mixed": rep["product_mixed_settled_n5"],
        "asof_or_rule_dates_found": sorted(asof_rule_dates),
        "delta_true_vs_expected": round(true["sum_eq_sum"] - 31.4756, 4),
        "match_n_days_true": true["n_days"] == 11,
    }



def reproduce_sep_from_csv(csv_path: Path, summary_path: Path | None = None) -> dict[str, Any]:
    """Exact materials acceptance table from sep2026_daily_compare.csv (+ optional summary)."""
    import csv
    rows = list(csv.DictReader(csv_path.open(encoding="utf-8")))
    by_track: dict[str, list[dict[str, Any]]] = defaultdict(list)
    daily = []
    for r in rows:
        src = (r.get("pick_source_file") or "").strip()
        track = normalize_track(src, fallback_reason=("timeout" if src == "rule_order" else None))
        # rule_order in materials Sep-11 is fallback (timeout)
        if src == "rule_order":
            track = f"fallback_{TRACK_RULE}"
        status = (r.get("llm_status") or "").strip()
        try:
            n = int(float(r.get("llm_n") or 0))
        except ValueError:
            n = 0
        try:
            eq = float(r.get("llm_eq_sum")) if r.get("llm_eq_sum") not in (None, "") else None
        except ValueError:
            eq = None
        true = track == TRACK_LLM and status == "settled" and n == 5 and eq is not None
        row = {
            "date": r.get("date"),
            "source_track": track,
            "pick_source": src,
            "status": status,
            "n": n,
            "eq_sum_chg_pct": eq,
            "true_llm": true,
        }
        daily.append(row)
        by_track[track].append(row)

    def pack(rows: list[dict[str, Any]], *, true_only: bool = False) -> dict[str, Any]:
        use = [x for x in rows if (x["true_llm"] if true_only else (
            x.get("status") == "settled" and x.get("n") == 5 and isinstance(x.get("eq_sum_chg_pct"), (int, float))
        ))]
        return {
            "n_days": len(use),
            "sum_eq_sum": round(sum(float(x["eq_sum_chg_pct"]) for x in use), 4),
            "dates": [x["date"] for x in use],
        }

    true = pack(by_track.get(TRACK_LLM, []), true_only=True)
    asof = pack(by_track.get(TRACK_ASOF, []))
    fb = pack(by_track.get(f"fallback_{TRACK_RULE}"), )
    mixed = pack(daily)
    expected = None
    if summary_path and summary_path.exists():
        expected = json.loads(summary_path.read_text(encoding="utf-8"))
    match = (
        true["n_days"] == 11
        and abs(true["sum_eq_sum"] - 31.4756) < 0.01
        and asof["n_days"] + fb["n_days"] == 2
        and abs((asof["sum_eq_sum"] + fb["sum_eq_sum"]) - (-10.9464)) < 0.01
    )
    return {
        "note": DOC_NOTE,
        "source_csv": str(csv_path),
        "daily": daily,
        "true_llm": {**true, "track": TRACK_LLM, "label": "真 LLM settled n=5"},
        "by_track": {
            TRACK_LLM: {**true, "label": "真 LLM"},
            TRACK_ASOF: {**asof, "label": "asof_replay"},
            f"fallback_{TRACK_RULE}": {**fb, "label": "fallback_rule_order"},
        },
        "product_mixed_settled_n5": {
            **mixed,
            "label": "材料日历混轨 settled n=5（禁止标成 llm_rerank）",
            "must_not_label_as": TRACK_LLM,
            "note": "materials baseline_calendar_unref Sep ≈ -1.90 / 12d is the product KPI snapshot, not this raw sum of all settled rows",
        },
        "asof_plus_rule": {
            "n_days": asof["n_days"] + fb["n_days"],
            "sum_eq_sum": round(asof["sum_eq_sum"] + fb["sum_eq_sum"], 4),
            "dates": asof["dates"] + fb["dates"],
        },
        "expected_ref": {
            "true_llm": {"n_days": 11, "sum_eq_sum": 31.4756},
            "asof_or_rule": {"n_days": 2, "sum_eq_sum": -10.9464},
            "mixed_calendar_unref_sep": {"n_days": 12, "sum_eq_sum": -1.9042},
        },
        "acceptance_match": match,
        "summary_file": str(summary_path) if summary_path else None,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="序1 source-track KPI")
    ap.add_argument("--month", default=None, help="YYYY-MM (default: all months present, write each)")
    ap.add_argument("--calendar", type=Path, default=CAL_PATH)
    ap.add_argument("--picks-dir", type=Path, default=PICKS_DIR)
    ap.add_argument("--reproduce-sep-materials", type=Path, default=None,
                    help="Path to materials raw/daily_picks for Sep split reproduction")
    ap.add_argument("--reproduce-sep-csv", type=Path, default=None,
                    help="Path to sep2026_daily_compare.csv for exact materials acceptance")
    ap.add_argument("--sep-summary", type=Path, default=None,
                    help="Optional sep2026_summary.json reference")
    ap.add_argument("--no-write-calendar", action="store_true")
    args = ap.parse_args(argv)

    if args.reproduce_sep_csv:
        result = reproduce_sep_from_csv(args.reproduce_sep_csv, args.sep_summary)
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        out = OUT_DIR / "sep2026_reproduce.json"
        out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({
            "wrote": str(out),
            "true_llm": result["true_llm"],
            "asof_plus_rule": result["asof_plus_rule"],
            "acceptance_match": result["acceptance_match"],
            "by_track": {k: {"n": v["n_days"], "sum": v["sum_eq_sum"]} for k, v in result["by_track"].items()},
        }, ensure_ascii=False, indent=2))
        return 0 if result["acceptance_match"] else 2

    if args.reproduce_sep_materials:
        if not args.calendar.exists():
            print(f"missing calendar {args.calendar}", file=sys.stderr)
            return 1
        result = reproduce_sep_materials(args.reproduce_sep_materials, args.calendar)
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        out = OUT_DIR / "sep2026_reproduce_from_live_cal.json"
        out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({
            "wrote": str(out),
            "true_llm": result["computed_true_llm"],
            "by_track_keys": list(result["computed_by_track"].keys()),
            "asof_or_rule_dates": result["asof_or_rule_dates_found"],
            "match_n_days_true": result["match_n_days_true"],
            "delta_true_vs_expected": result["delta_true_vs_expected"],
            "note": "live calendar settlements differ from materials snapshot; use --reproduce-sep-csv for exact acceptance",
        }, ensure_ascii=False, indent=2))
        return 0

    if not args.calendar.exists():
        print(f"missing {args.calendar}", file=sys.stderr)
        return 1

    cal = json.loads(args.calendar.read_text(encoding="utf-8"))
    pick_meta = load_pick_meta(args.picks_dir)
    shadow_days = load_shadow_days()

    # Determine months
    all_dates = [str(d.get("date"))[:10] for d in (cal.get("days") or []) if isinstance(d, dict) and d.get("date")]
    months = sorted({d[:7] for d in all_dates if len(d) >= 7})
    if args.month:
        months = [args.month]

    last_reports: dict[str, dict[str, Any]] = {}
    for month in months:
        reports: dict[str, dict[str, Any]] = {}
        for model_key, days in iter_model_days(cal):
            # For non-gpt, picks may live under daily_picks/<key>/
            meta = pick_meta
            if model_key != "gpt":
                meta = {**pick_meta, **load_pick_meta(PICKS_DIR / model_key)}
            reports[model_key] = build_for_model(model_key, days, meta, shadow_days, month)
        path = write_month_files(reports, month)
        print(f"[source_track_kpi] wrote {path} models={list(reports)} "
              f"gpt_true_llm={reports.get('gpt', {}).get('true_llm')}", flush=True)
        last_reports = reports

    # Annotate calendar with full-range kpi (recompute without month filter for kpi_by_source)
    full_reports: dict[str, dict[str, Any]] = {}
    for model_key, days in iter_model_days(cal):
        meta = pick_meta if model_key == "gpt" else {**pick_meta, **load_pick_meta(PICKS_DIR / model_key)}
        full_reports[model_key] = build_for_model(model_key, days, meta, shadow_days, None)
    annotate_calendar(cal, full_reports)

    if not args.no_write_calendar:
        args.calendar.write_text(json.dumps(cal, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"[source_track_kpi] annotated {args.calendar} kpi_by_source.true_llm="
              f"{(cal.get('kpi_by_source') or {}).get('true_llm')}", flush=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
