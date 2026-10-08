#!/usr/bin/env python3
"""Record a manual re-pick / replacement of a live day's picks (PM rule 2026-09-29).

Usage: record_repick.py <gpt|claude> <YYYY-MM-DD> --reason "why" --new CODE,CODE,CODE,CODE,CODE
Writes data/live_record/<key>/repicks/<day>_<HHMMSS>.json with the time, the reason, the old symbols
(read from the current picks file), the new symbols and which were swapped. Refused after the lock
(09:25 of the next trading day). Then run the re-pick; pick_guard lets that exact new batch through.
"""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import pick_guard  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("key"); ap.add_argument("day")
    ap.add_argument("--reason", required=True); ap.add_argument("--new", required=True)
    ap.add_argument("--by", default="")
    a = ap.parse_args()
    f = pick_guard.PROD_PICKS / (f"{a.day}.json" if a.key == "gpt" else f"{a.key}/{a.day}.json")
    old = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
    try:
        pick_guard.record_repick(a.key, a.day, a.reason, pick_guard._codes(old), [c for c in a.new.split(",") if c], by=a.by)
    except pick_guard.PickGuardError as exc:
        print(f"[record_repick] REFUSED: {exc}", file=sys.stderr); return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
