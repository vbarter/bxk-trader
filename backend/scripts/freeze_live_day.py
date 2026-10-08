#!/usr/bin/env python3
"""Freeze a live day before a backfill overwrites it (PM rule 2026-09-29).

Usage: freeze_live_day.py <gpt|claude> <YYYY-MM-DD>

- live + settled (not paused, not backfill) in the current watch_calendar
    -> data/live_record/<key>/<D>.json (verbatim settled day object; never overwritten)
- live + pending (not paused, not backfill)
    -> copy the live daily_picks file to data/daily_picks/_archived/<key>/<D>.json
       (the export then settles it into tracks.<key>.archived_days; never overwritten)
- live + paused, backfill day, or no day -> nothing to freeze
- "live" means (PM 13:08 rule): the batch last shown before the buy-day open. Going forward that is
  the calendar batch of a day with a 15:05 log record or a live_record/<key>/repicks/ record
  (pick_guard.py locks picks at 09:25 of the next trading day).
  Days without a 15:05 log record are never frozen as live (PM rule 2026-09-29 13:00).
dual_basis.py then uses the live result as 实际推荐 and the backfill as the 回溯版 block.
Additive only: never deletes or overwrites anything.
"""
from __future__ import annotations
import json, shutil, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"


def track_days(cal: dict, key: str) -> list:
    t = (cal.get("tracks") or {}).get(key) or {}
    if isinstance(t.get("days"), list):
        return t["days"]
    if key == "gpt" and (t.get("days_ref") == "days" or not t):
        return cal.get("days") or []
    return []


def main() -> int:
    key, day = sys.argv[1], sys.argv[2]
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import dual_basis
    lg = dual_basis.load_live_index().get(key, {}).get(day)
    if not lg and not dual_basis._has_repick(key, day):
        print(f"[freeze] {key} {day}: no 15:05 live-log record and no re-pick record, not live, nothing to freeze"); return 0
    lg = lg or {}
    cal = json.loads((DATA / "watch_calendar.json").read_text(encoding="utf-8"))
    d = next((x for x in track_days(cal, key) if isinstance(x, dict) and x.get("date") == day), None)
    if d is None:
        print(f"[freeze] {key} {day}: not in calendar, nothing to freeze"); return 0
    if d.get("backfill") is True:
        print(f"[freeze] {key} {day}: already a backfill day, nothing to freeze"); return 0
    if d.get("status") == "paused" or d.get("pick_status") == "paused":
        print(f"[freeze] {key} {day}: live paused, nothing to freeze"); return 0
    want = sorted(lg.get("codes") or [])
    have = sorted(s.get("code") for s in d.get("stocks") or [] if isinstance(s, dict))
    if want and want != have and not dual_basis._has_repick(key, day):
        # 13:08 rule: the calendar batch at lock time is the last-shown batch; pick_guard requires a
        # re-pick record for any change, so a mismatch without one needs a human look.
        print(f"[freeze] {key} {day}: calendar batch {have} != 15:05 batch {want} and no re-pick record; not freezing", file=sys.stderr); return 3
    if d.get("status") == "settled" and isinstance(d.get("eq_sum_chg_pct"), (int, float)):
        out = DATA / "live_record" / key / f"{day}.json"
        if out.exists():
            print(f"[freeze] {key} {day}: live_record exists, kept"); return 0
        out.parent.mkdir(parents=True, exist_ok=True)
        rec = dict(d); rec["_frozen_from"] = "watch_calendar.json before backfill"
        out.write_text(json.dumps(rec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"[freeze] {key} {day}: live settled {d.get('eq_sum_chg_pct')} -> {out}"); return 0
    src = DATA / "daily_picks" / (f"{day}.json" if key == "gpt" else f"{key}/{day}.json")
    dst = DATA / "daily_picks" / "_archived" / key / f"{day}.json"
    if dst.exists():
        print(f"[freeze] {key} {day}: live pending, archive exists, kept"); return 0
    if not src.exists():
        print(f"[freeze] {key} {day}: live pending but {src} missing", file=sys.stderr); return 2
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    print(f"[freeze] {key} {day}: live pending -> archived {dst}"); return 0


if __name__ == "__main__":
    raise SystemExit(main())
