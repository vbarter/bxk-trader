#!/usr/bin/env python3
"""Guard for writing daily picks (PM rules 2026-09-29).

(a) After the 15:05 pick, a manual re-pick / replacement of a LIVE day's picks needs a record in
    data/live_record/<key>/repicks/<day>_<HHMMSS>.json (time, reason, old/new symbols). Write it with
    scripts/record_repick.py, or in the same call by setting PICK_REPICK_REASON="...".
(b) From 09:25 CST of the next trading day (call auction) the day's picks are LOCKED: every rewrite is
    refused; the only allowed change is marking the day paused.
Backfill drivers: set PICK_GUARD_BACKFILL=1 together with PICK_BACKFILL=1. That override only lets
them write into their own work dirs (never the prod daily_picks dir). Installing a backfill over a
prod day goes through `pick_guard.py install-backfill ... --backfill-override`, which refuses unless
the live batch is already preserved (live_record/ or _archived/), keeps a copy of the replaced file,
and never touches a live batch otherwise.

CLI:
  pick_guard.py check <picks_file> <new_payload.json>            # exit 0 allowed / 3 refused
  pick_guard.py install-backfill <key> <day> <src.json> --backfill-override
Environment (for tests): PICK_GUARD_NOW=2026-09-30T09:26:00  PICK_GUARD_ROOT=/tmp/copy (Sequoia-X root)
"""
from __future__ import annotations

import json
import os
import shutil
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path

ROOT = Path(os.environ.get("PICK_GUARD_ROOT") or Path(__file__).resolve().parents[1])
PROD_PICKS = (ROOT / "data" / "daily_picks").resolve()
LOCK_AT = time(9, 25)
# Non-weekend exchange holidays still ahead in 2026 (weekday rule otherwise). If a holiday is
# missing the lock only comes earlier (stricter), never later.
HOLIDAYS = {"2026-10-01", "2026-10-02", "2026-10-05", "2026-10-06", "2026-10-07"}
_extra = ROOT / "data" / "market_holidays.json"
if _extra.exists():
    try:
        HOLIDAYS |= set(json.loads(_extra.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError):
        pass


class PickGuardError(RuntimeError):
    pass


def _now() -> datetime:
    v = os.environ.get("PICK_GUARD_NOW")
    return datetime.fromisoformat(v) if v else datetime.now()


def next_trading_day(day: str) -> date:
    d = date.fromisoformat(day) + timedelta(days=1)
    while d.weekday() >= 5 or d.isoformat() in HOLIDAYS:
        d += timedelta(days=1)
    return d


def lock_time(day: str) -> datetime:
    return datetime.combine(next_trading_day(day), LOCK_AT)


def _codes(p: dict | None) -> list[str]:
    out = []
    for s in (p or {}).get("symbols") or []:
        out.append(s if isinstance(s, str) else (s or {}).get("code"))
    return [c for c in out if c]


def _is_paused(p: dict | None) -> bool:
    return bool(p) and (p.get("pick_status") == "paused" or p.get("source") == "paused")


def _key_for(target: Path) -> str:
    parent = target.parent.name
    return "gpt" if parent == "daily_picks" else parent


def _is_prod(target: Path) -> bool:
    try:
        return target.resolve().parent in (PROD_PICKS, *[PROD_PICKS / k for k in ("claude", "gpt")])
    except OSError:
        return False


def _repick_dir(key: str) -> Path:
    return ROOT / "data" / "live_record" / key / "repicks"


def record_repick(key: str, day: str, reason: str, old_codes: list[str], new_codes: list[str], *, by: str = "") -> Path:
    if not reason.strip():
        raise PickGuardError("re-pick record needs a reason")
    now = _now()
    if now >= lock_time(day):
        raise PickGuardError(f"{key} {day}: picks locked since {lock_time(day):%Y-%m-%d %H:%M}; no re-pick allowed")
    d = _repick_dir(key); d.mkdir(parents=True, exist_ok=True)
    p = d / f"{day}_{now:%H%M%S}.json"
    rec = {"date": day, "model": key, "recorded_at": now.isoformat(timespec="seconds"), "reason": reason.strip(),
           "old_symbols": old_codes, "new_symbols": new_codes,
           "swapped_out": [c for c in old_codes if c not in new_codes],
           "swapped_in": [c for c in new_codes if c not in old_codes],
           "by": by or os.environ.get("USER", ""), "lock_at": lock_time(day).isoformat(timespec="minutes")}
    p.write_text(json.dumps(rec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[pick_guard] re-pick record {p}", flush=True)
    return p


def _has_record_for(key: str, day: str, new_codes: list[str], since: float) -> bool:
    for p in sorted(_repick_dir(key).glob(f"{day}_*.json")):
        try:
            r = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if p.stat().st_mtime >= since - 1 and sorted(r.get("new_symbols") or []) == sorted(new_codes):
            return True
    return False


def guard_write(target: Path, day: str, payload: dict) -> None:
    """Raise PickGuardError if writing `payload` to `target` breaks the rules; return to allow."""
    target = Path(target)
    if target.parent.name.startswith("_"):
        return  # _archived/_shadow/_replaced etc. are not the day's picks
    backfill_mode = os.environ.get("PICK_BACKFILL") == "1" or payload.get("backfill") is True
    if os.environ.get("PICK_GUARD_BACKFILL") == "1" and backfill_mode:
        if _is_prod(target):
            raise PickGuardError(f"{target}: backfill override never writes the prod picks dir; use install-backfill")
        return
    if not target.exists():
        return  # first write of the day
    try:
        old = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        old = None
    key = _key_for(target)
    new_codes, old_codes = _codes(payload), _codes(old)
    if _is_paused(payload):
        return  # marking a day paused is always allowed
    if backfill_mode:
        if old is not None and old.get("backfill") is not True and old_codes:
            raise PickGuardError(f"{key} {day}: refusing to overwrite a live batch with a backfill (use install-backfill)")
        return
    if _now() >= lock_time(day):
        raise PickGuardError(f"{key} {day}: picks locked since {lock_time(day):%Y-%m-%d %H:%M} (next trading day 09:25); "
                             "only a paused mark is allowed")
    if old is None or not old_codes or old.get("backfill") is True:
        return  # nothing live to protect yet (empty / paused / backfill file), before the lock
    if sorted(new_codes) == sorted(old_codes):
        return  # same batch (e.g. explanation refresh) before the lock
    reason = os.environ.get("PICK_REPICK_REASON", "").strip()
    if reason:
        record_repick(key, day, reason, old_codes, new_codes)
        return
    if _has_record_for(key, day, new_codes, target.stat().st_mtime):
        return
    raise PickGuardError(f"{key} {day}: live picks {old_codes} -> {new_codes} need a re-pick record "
                         "(scripts/record_repick.py or PICK_REPICK_REASON=...)")


def safe_guard_write(target: Path, day: str, payload: dict) -> None:
    """guard_write, but an internal bug in the guard never blocks the live pipeline."""
    try:
        guard_write(target, day, payload)
    except PickGuardError:
        raise
    except Exception as exc:  # pragma: no cover
        print(f"[pick_guard] WARN guard internal error ignored: {exc!r}", file=sys.stderr)


def _is_live_day(key: str, day: str) -> bool:
    """Live = 15:05 log record or a re-pick record (dual_basis rules). Early after-the-fact files are not live."""
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import dual_basis
        return bool(dual_basis.load_live_index(write=False).get(key, {}).get(day)) or dual_basis._has_repick(key, day)
    except Exception as exc:  # unknown -> treat as live (safe side)
        print(f"[pick_guard] WARN live check failed ({exc!r}); treating {key} {day} as live", file=sys.stderr)
        return True


def install_backfill(key: str, day: str, src: Path) -> int:
    dst = PROD_PICKS / (f"{day}.json" if key == "gpt" else f"{key}/{day}.json")
    new = json.loads(Path(src).read_text(encoding="utf-8"))
    if new.get("backfill") is not True and not _is_paused(new):
        raise PickGuardError(f"{src}: not a backfill payload")
    if dst.exists():
        old = json.loads(dst.read_text(encoding="utf-8"))
        if old.get("backfill") is not True and _codes(old) and _is_live_day(key, day):
            kept = [ROOT / "data" / "live_record" / key / f"{day}.json", PROD_PICKS / "_archived" / key / f"{day}.json"]
            if not any(p.exists() for p in kept):
                raise PickGuardError(f"{key} {day}: live batch not preserved in live_record/ or _archived/; refusing")
        rep = PROD_PICKS / "_replaced" / key
        rep.mkdir(parents=True, exist_ok=True)
        shutil.copy2(dst, rep / f"{day}.{_now():%Y%m%d_%H%M%S}.json")
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    print(f"[pick_guard] installed backfill {key} {day} <- {src}", flush=True)
    return 0


def main(argv: list[str]) -> int:
    try:
        if len(argv) >= 3 and argv[0] == "check":
            payload = json.loads(Path(argv[2]).read_text(encoding="utf-8"))
            t = Path(argv[1])
            guard_write(t, payload.get("date") or t.stem, payload)
            print(f"[pick_guard] allowed: {t}"); return 0
        if len(argv) >= 4 and argv[0] == "install-backfill":
            if "--backfill-override" not in argv:
                raise PickGuardError("install-backfill needs --backfill-override (backfill drivers only)")
            return install_backfill(argv[1], argv[2], Path(argv[3]))
    except PickGuardError as exc:
        print(f"[pick_guard] REFUSED: {exc}", file=sys.stderr); return 3
    print(__doc__); return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
