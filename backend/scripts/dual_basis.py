#!/usr/bin/env python3
"""Dual-basis totals for watch_calendar.json (实际推荐 / 全部回溯).

序1 (2026-10-02): these totals are PRODUCT mixed (actual/rerun). Never label them
llm_rerank. True LLM KPI lives in kpi_by_source (scripts/source_track_kpi.py).

PM rules (2026-09-29 12:50, refined 13:00, final 13:08):
  * 13:08 rule: the LIVE batch is the batch last shown on the page (:8080 / Cloudflare)
    before the buy-day open. For history this was decided from evidence (pick-file mtimes,
    ingest push times in the sequoia-x-web journal, the 09:35 settle log) and frozen into
    data/live_record/<key>/<day>.json (see data/live_record/<key>/_evidence_*.json).
    From 2026-09-29 on, pick_guard.py locks a day's picks at 09:25 of the next trading day,
    and any re-pick before that needs a live_record/<key>/repicks/ record, so the calendar
    batch of a 15:05-logged (or re-pick-recorded) day IS the last-shown batch.
  * basis_verified: true for live days and for backfills written by the verified drivers
    (backfill:true); false for early after-the-fact days (June-August) -> tip_backfill_early.
Earlier (13:00) wording kept below for reference:
  * A day is LIVE for a model only if the 15:05 live log (log_close_pm.txt) has a
    record of that model's close_pm run writing the day's picks on the signal day
    ("wrote .../daily_picks/[<key>/]<day>.json source=... symbols=[...]").
    Everything else (retroactive files, manual reruns, backfills) is NOT live.
  * 实际推荐 (actual): a live day uses the settled result of the batch the 15:05 run
    wrote; every non-live day uses its current (after-the-fact / backfill) result and
    counts toward n. A live-paused day with no backfill stays excluded; a live day
    whose batch is still unsettled counts as unsettled.
  * 全部回溯 (rerun): every day as it stands in the calendar now.

Live index: parsed from log_close_pm.txt on every run and merged (never pruned) into
data/live_log_index.json, so future days get the flag automatically from the 15:05 run
and survive log rotation.
Live results (settled 15:05 batches), in priority order:
  1. tracks.<key>.archived_days (live batches replaced by a backfill, settled by export)
  2. data/live_record/<key>/<day>.json (frozen settled live results)
  3. the calendar day itself, if it is not a backfill and holds the logged batch
Only a source whose codes equal the logged codes is accepted.
Settled archived live batches are also frozen into data/live_record/ (new files only),
so the no-tracks fallback path sees exactly the same live results as the main path.
Never deletes or overwrites anything except watch_calendar.json annotations.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
LIVE_RECORD = DATA / "live_record"
LIVE_INDEX = DATA / "live_log_index.json"
CLOSE_PM_LOG = ROOT / "log_close_pm.txt"
LIVE_KEYS = ("date", "status", "buy_date", "sell_date", "eq_avg_chg_pct", "eq_sum_chg_pct",
             "n", "stocks", "pick_source", "pick_status")

_RUN_RE = re.compile(r"^===== close_pm start (\d{4}-\d{2}-\d{2})T(\S+) =====")
_WROTE_RE = re.compile(
    r"^(?:\[(?P<key>[a-z0-9_]+)\] )?wrote \S*/daily_picks/(?:(?P<sub>[a-z0-9_]+)/)?(?P<day>\d{4}-\d{2}-\d{2})\.json"
    r" source=(?P<src>\S+)(?: symbols=\[(?P<codes>[^\]]*)\])?(?P<rest>.*)$")


def parse_close_pm_log(path: Path = CLOSE_PM_LOG) -> dict[str, dict[str, dict]]:
    """{key: {day: {...}}} for picks written by a close_pm run on the signal day itself."""
    out: dict[str, dict[str, dict]] = {}
    if not path.exists():
        return out
    run_day = run_at = None
    with path.open(encoding="utf-8", errors="replace") as fh:
        for no, line in enumerate(fh, 1):
            m = _RUN_RE.match(line)
            if m:
                run_day, run_at = m.group(1), m.group(1) + "T" + m.group(2)
                continue
            m = _WROTE_RE.match(line.strip())
            if not m or run_day is None:
                continue
            day = m.group("day")
            if day != run_day:          # only same-day live runs count
                continue
            src = m.group("src")
            if src == "multi_hit" or "/_" in line:  # shadow/archive writes are not the main pick
                continue
            key = m.group("key") or m.group("sub") or "gpt"
            codes = [c for c in (m.group("codes") or "").split(",") if c]
            out.setdefault(key, {})[day] = {
                "codes": codes, "source": src, "paused": src == "paused",
                "run_start": run_at, "log_line": no, "log": path.name,
            }
    return out


def load_live_index(write: bool = True) -> dict[str, dict[str, dict]]:
    idx: dict[str, dict[str, dict]] = {}
    if LIVE_INDEX.exists():
        try:
            idx = json.loads(LIVE_INDEX.read_text(encoding="utf-8")).get("live", {}) or {}
        except (OSError, json.JSONDecodeError):
            idx = {}
    fresh = parse_close_pm_log()
    changed = False
    for key, days in fresh.items():
        for day, rec in days.items():
            if idx.get(key, {}).get(day) != rec:
                idx.setdefault(key, {})[day] = rec
                changed = True
    if write and (changed or not LIVE_INDEX.exists()):
        LIVE_INDEX.write_text(json.dumps({
            "rule": "live = close_pm (15:05) run on the signal day wrote this model's picks; see dual_basis.py",
            "live": {k: dict(sorted(v.items())) for k, v in sorted(idx.items())},
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return idx


def _paused(d: dict) -> bool:
    return d.get("status") == "paused" or d.get("pick_status") == "paused"


def _settled(d: dict) -> bool:
    return d.get("status") == "settled" and isinstance(d.get("eq_sum_chg_pct"), (int, float)) and not _paused(d)


def _codes(d: dict) -> list[str]:
    return [s.get("code") for s in d.get("stocks") or [] if isinstance(s, dict)]


def _load_live_sources(key: str, track: dict) -> dict[str, dict]:
    live: dict[str, dict] = {}
    rec = LIVE_RECORD / key
    if rec.exists():
        for p in sorted(rec.glob("????-??-??.json")):
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(d, dict) and d.get("date"):
                live[d["date"]] = d
    for d in track.get("archived_days") or []:
        if isinstance(d, dict) and d.get("date") and d["date"] not in live:
            live[d["date"]] = d  # archived live batch (settled by export); live_record wins
    return live


def _freeze_archived(key: str, track: dict) -> None:
    for d in track.get("archived_days") or []:
        if not (isinstance(d, dict) and d.get("date") and _settled(d)):
            continue
        p = LIVE_RECORD / key / f"{d['date']}.json"
        if p.exists():
            continue
        p.parent.mkdir(parents=True, exist_ok=True)
        rec = {k: v for k, v in d.items() if k not in ("exclude_from_totals", "archived")}
        rec["_frozen_from"] = "tracks.%s.archived_days (settled archived live batch)" % key
        p.write_text(json.dumps(rec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"[dual_basis] froze archived live {key} {d['date']} -> {p}", flush=True)


def _has_repick(key: str, day: str) -> bool:
    return any((LIVE_RECORD / key / "repicks").glob(f"{day}_*.json"))


def _compact(d: dict) -> dict:
    out = {k: d[k] for k in LIVE_KEYS if k in d}
    out["basis"] = "live"
    return out


def _state(d: dict) -> str:
    if _paused(d):
        return "paused"
    if d.get("exclude_from_totals"):
        return "excluded"
    return "settled" if _settled(d) else "pending"


def _agg(days: list[dict], metric) -> dict:
    by_month: dict[str, dict] = {}
    by_year: dict[str, dict] = {}
    for d in days:
        m = metric(d)
        for bucket, k in ((by_month, d["date"][:7]), (by_year, d["date"][:4])):
            b = bucket.setdefault(k, {"sum": 0.0, "settled": 0, "paused": 0, "pending": 0, "n_backfill": 0, "n_live": 0})
            if m["state"] == "settled":
                b["sum"] += m["value"]; b["settled"] += 1
                b["n_backfill" if m["basis"] == "backfill" else "n_live"] += 1
            elif m["state"] == "paused":
                b["paused"] += 1
            elif m["state"] == "pending":
                b["pending"] += 1
                # Unsettled live days count in n_live (PM 2026-09-29); backfill pending stays separate.
                if m["basis"] == "backfill":
                    b["n_backfill_pending"] = b.get("n_backfill_pending", 0) + 1
                else:
                    b["n_live"] += 1
    for bucket in (by_month, by_year):
        for b in bucket.values():
            b["sum"] = round(b["sum"], 4)
    return {"by_month": by_month, "by_year": by_year}


def annotate(cal: dict, index: dict | None = None) -> dict:
    index = load_live_index() if index is None else index
    tracks = cal.get("tracks") or {}
    items = list(tracks.items())
    if not items and isinstance(cal.get("days"), list):
        # build_dual_track_calendar failed: top-level days are the GPT (llm) track.
        items = [("gpt", {"days_ref": "days"})]
    for key, t in items:
        if not isinstance(t, dict):
            continue
        days = cal.get("days") if t.get("days_ref") == "days" else t.get("days")
        if not isinstance(days, list):
            continue
        _freeze_archived(key, t)
        sources = _load_live_sources(key, t)
        logged = index.get(key, {})
        for d in days:
            if not isinstance(d, dict):
                continue
            d.pop("live", None)
            day = d.get("date")
            src = sources.get(day)
            if src is not None and src is not d and _paused(src) and not _codes(src):
                # live day that was PAUSED before the buy open (nothing shown/bought): no live result,
                # so a successful backfill fills it (PM 12:50 rule); no backfill -> stays paused.
                d["live_flag"] = False
                d["live_paused"] = True
                d["actual_basis"] = "backfill" if d.get("backfill") is True else "live"
                d["basis_verified"] = True
                continue
            if src is not None and src is not d and _codes(src):
                # evidence-decided last-shown live batch (live_record) or archived live batch
                d["live_flag"] = True
                d["actual_basis"] = "live"
                d["live"] = _compact(src)
                d["basis_verified"] = True
                continue
            lg = logged.get(day)
            if (lg or _has_repick(key, day)) and d.get("backfill") is not True:
                d["live_flag"] = True          # the calendar batch is the locked live batch
                d["actual_basis"] = "live"
                d["basis_verified"] = True
                continue
            d["basis_verified"] = d.get("backfill") is True
            if not lg:
                d["live_flag"] = False
                d["actual_basis"] = "backfill"
                continue
            d["live_flag"] = True          # logged live day replaced by a backfill, live batch not frozen
            d["actual_basis"] = "live"
            want = lg.get("codes") or []
            # logged live batch without a settled record: count as unsettled
            d["live"] = {"date": d["date"], "status": "pending", "n": len(want),
                         "stocks": [{"code": c, "name": c} for c in lg.get("codes") or []],
                         "pick_source": lg.get("source"), "basis": "live"}
            print(f"[dual_basis] WARN {key} {d['date']}: logged live batch has no settled record", file=sys.stderr)

        def actual(d: dict) -> dict:
            src = d.get("live") if d.get("actual_basis") == "live" and d.get("live") else d
            st = _state(src)
            return {"state": st, "value": src.get("eq_sum_chg_pct") if st == "settled" else None,
                    "basis": d.get("actual_basis")}

        def rerun(d: dict) -> dict:
            st = _state(d)
            is_live = d.get("live_flag") and d.get("backfill") is not True
            return {"state": st, "value": d.get("eq_sum_chg_pct") if st == "settled" else None,
                    "basis": "live" if is_live else "backfill"}

        ds = [d for d in days if isinstance(d, dict) and isinstance(d.get("date"), str)]
        t["totals"] = {"metric": "eq_sum_chg_pct", "live_rule": "last_batch_on_page_before_buy_open",
                       "actual": _agg(ds, actual), "rerun": _agg(ds, rerun)}
        if key == "gpt" and t.get("days_ref") == "days" and not tracks:
            cal["totals_fallback_gpt"] = t["totals"]
    return cal


def annotate_file(path: Path) -> None:
    cal = json.loads(path.read_text(encoding="utf-8"))
    annotate(cal)
    path.write_text(json.dumps(cal, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tr = cal.get("tracks") or ({"gpt": {"totals": cal["totals_fallback_gpt"]}} if "totals_fallback_gpt" in cal else {})
    for key, t in tr.items():
        tt = t.get("totals") or {}
        for basis in ("actual", "rerun"):
            m = (tt.get(basis) or {}).get("by_month", {})
            last = sorted(m)[-1] if m else None
            if last:
                print(f"[dual_basis] {key} {basis} {last}: {m[last]}", flush=True)


if __name__ == "__main__":
    annotate_file(Path(sys.argv[1]) if len(sys.argv) > 1 else DATA / "watch_calendar.json")
