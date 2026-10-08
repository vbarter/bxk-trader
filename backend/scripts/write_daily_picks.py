#!/usr/bin/env python3
"""Write data/daily_picks/YYYY-MM-DD.json from latest.json.

PICK_MODE (env, default **shadow**):
  llm        — LLM Top5 (source=llm_rerank, pick_status=ok). On failure retry
               (3 attempts total, backoff 20s/60s); if all fail the signal day
               is PAUSED: symbols=[], source=paused, pick_status=paused,
               pause_reason, attempts, source_track=paused, fault=true,
               fallback_policy=pause_no_rule_order.
               序3 Option B (2026-10-02, matches 0.12.4): NEVER silently write
               source=rule_order as a successful Top5. multi_hit stays shadow-only
               (ALLOW_MULTI_HIT_MAIN=0); optional _shadow/*.multi_hit.json still
               written on failure days for对照.
               Env: LLM_PICK_ATTEMPTS (default 3), LLM_RETRY_BACKOFF_S ("20,60").
               Test: LLM_FORCE_FAIL=1 (see llm_rerank.rerank_top5).
  multi_hit  — MAIN path = multi_hit_top5. HARD GATE: requires
               ALLOW_MULTI_HIT_MAIN=1 (default OFF). Without the kill-switch,
               forced to shadow. Do NOT enable in production without explicit OK.
  rule_order — DISABLED as a day's picks since 2026-09-28 (treated as shadow)
  shadow     — (default) main path = llm dual-model write; ALSO write
               data/daily_picks/_shadow/YYYY-MM-DD.multi_hit.json with
               source=multi_hit, track=multi_hit_shadow (never pushed to CF /
               never into watch_calendar live Top5 / latest home picks).
  Unknown PICK_MODE → shadow (safe).

LLM_RERANK kept for compat: when PICK_MODE=llm (or shadow main), LLM_RERANK=1
enables LLM; otherwise the day is paused (never rule_order).

MIN_VALID_STOCKS (default 4000): if stock_daily coverage for the signal day
is below threshold, do NOT write a normal Top5; log n_valid_stocks + write
and write a coverage_fail marker instead.

Usage:
  write_daily_picks.py              # today (Asia/Shanghai calendar date)
  write_daily_picks.py 2026-09-07   # explicit signal day
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
LATEST_PATH = DATA_DIR / "latest.json"
# PICK_BACKFILL=1: after-the-fact recompute (as-of signal-day close); marks files + latest block backfill=true.
PICK_BACKFILL = os.environ.get("PICK_BACKFILL", "").strip() == "1"
DETAILS_DIR = DATA_DIR / "details"
PICKS_DIR = DATA_DIR / "daily_picks"
SHADOW_DIR = PICKS_DIR / "_shadow"
SH_TZ = ZoneInfo("Asia/Shanghai")

# Signal-day K coverage gate (Phase0): skip writing picks if below threshold.
DEFAULT_MIN_VALID_STOCKS = 4000

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pick_models import MODEL_LABELS, enabled_pick_models, model_id_for, picks_dir_for  # noqa: E402
from llm_rerank import (  # noqa: E402
    FEATURE_VER,
    PROMPT_VER,
    llm_rerank_enabled,
    multi_hit_top5,
    rerank_top5,
    resolve_api_config,
)


def today_sh() -> str:
    return datetime.now(SH_TZ).strftime("%Y-%m-%d")


def allow_multi_hit_main() -> bool:
    """Hard kill-switch for PICK_MODE=multi_hit as the MAIN calendar path.

    Default OFF. Production must stay on shadow/llm unless ops explicitly set
    ALLOW_MULTI_HIT_MAIN=1. (MULTI_HIT_ENABLED is legacy / dual-track UI only —
    it does NOT unlock main multi_hit.)
    """
    return (os.environ.get("ALLOW_MULTI_HIT_MAIN") or "0").strip() == "1"


def pick_mode() -> str:
    """Resolve PICK_MODE; default shadow. Unknown → shadow (safe).

    PICK_MODE=multi_hit (main cutover) requires ALLOW_MULTI_HIT_MAIN=1;
    otherwise forced to shadow so multi_hit stays side-file only.
    """
    raw = (os.environ.get("PICK_MODE") or "shadow").strip().lower()
    if raw == "rule_order":
        print(
            "[write_daily_picks] PICK_MODE=rule_order no longer writes picks -> shadow",
            file=sys.stderr,
        )
        return "shadow"
    if raw == "multi_hit":
        if not allow_multi_hit_main():
            print(
                "[write_daily_picks] HARD GATE: PICK_MODE=multi_hit blocked "
                "(set ALLOW_MULTI_HIT_MAIN=1 to cut over main); using shadow",
                file=sys.stderr,
                flush=True,
            )
            return "shadow"
        return "multi_hit"
    if raw in {"llm", "shadow"}:
        return raw
    print(
        f"[write_daily_picks] warn: unknown PICK_MODE={raw!r}; using shadow",
        file=sys.stderr,
    )
    return "shadow"


def min_valid_stocks() -> int:
    raw = (os.environ.get("MIN_VALID_STOCKS") or str(DEFAULT_MIN_VALID_STOCKS)).strip()
    try:
        return max(0, int(raw))
    except ValueError:
        return DEFAULT_MIN_VALID_STOCKS


def count_stock_daily(day: str) -> int | None:
    """Return DISTINCT symbol count for day, or None if DB missing/unreadable."""
    db = os.environ.get("DB_PATH") or str(DATA_DIR / "sequoia_v2.db")
    path = Path(db)
    if not path.is_absolute():
        path = ROOT / path
    if not path.exists():
        return None
    try:
        with sqlite3.connect(str(path)) as conn:
            n = conn.execute(
                "SELECT COUNT(DISTINCT symbol) FROM stock_daily WHERE date = ?",
                (day,),
            ).fetchone()[0]
            return int(n)
    except sqlite3.Error as exc:
        print(f"[write_daily_picks] warn: stock_daily count failed: {exc}", file=sys.stderr)
        return None


def write_coverage_fail_marker(day: str, n: int | None, threshold: int) -> Path:
    """Refuse a normal Top5 day: log + write skip marker (not a live Top5)."""
    path = PICKS_DIR / f"{day}.coverage_fail.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "date": day,
        "source": "coverage_fail",
        "pick_status": "skipped",
        "paused": True,
        "n_valid_stocks": n,
        "min_valid_stocks": threshold,
        "symbols": [],
        "pause_reason": (
            f"n_valid_stocks={n} < MIN_VALID_STOCKS={threshold}"
            if n is not None
            else f"stock_daily unreadable; MIN_VALID_STOCKS={threshold}"
        ),
        "pick_status_at": now_sh_iso(),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        f"[write_daily_picks] wrote coverage_fail marker {path} "
        f"n_valid_stocks={n} threshold={threshold}",
        flush=True,
    )
    return path


def coverage_ok(day: str) -> bool:
    """Gate: signal day must have enough bars. Alert + skip picks if not."""
    threshold = min_valid_stocks()
    n = count_stock_daily(day)
    if n is None:
        print(
            f"[write_daily_picks] ALERT: cannot read stock_daily for {day}; "
            f"n_valid_stocks=None MIN_VALID_STOCKS={threshold}; "
            f"skip writing picks (coverage_fail)",
            file=sys.stderr,
            flush=True,
        )
        write_coverage_fail_marker(day, None, threshold)
        return False
    if n < threshold:
        print(
            f"[write_daily_picks] ALERT: signal-day coverage too low "
            f"day={day} n_valid_stocks={n} < MIN_VALID_STOCKS={threshold}; "
            f"skip writing picks (coverage_fail)",
            file=sys.stderr,
            flush=True,
        )
        write_coverage_fail_marker(day, n, threshold)
        return False
    print(
        f"[write_daily_picks] coverage ok day={day} n_valid_stocks={n} "
        f"(MIN_VALID_STOCKS={threshold})",
        flush=True,
    )
    return True


STATUS_KEYS = ("pick_status", "paused", "pause_reason", "attempts", "pick_status_at")


def now_sh_iso() -> str:
    return datetime.now(SH_TZ).isoformat(timespec="seconds")


def merge_daily_picks_into_latest(
    day: str,
    symbols: list[dict[str, str]],
    source: str,
    status: dict | None = None,
    model_key: str = "gpt",
) -> None:
    """Attach Top5 reason/explain onto latest.json for homepage (drop-point fix)."""
    if not LATEST_PATH.exists():
        return
    try:
        latest = json.loads(LATEST_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"[warn] cannot read latest.json for daily_picks merge: {exc}", file=sys.stderr)
        return
    slim: list[dict[str, str]] = []
    for item in symbols:
        if not isinstance(item, dict):
            continue
        code = str(item.get("code") or "").zfill(6)
        if not code.isdigit() or len(code) != 6:
            continue
        row: dict[str, str] = {
            "code": code,
            "name": str(item.get("name") or code),
        }
        if source == "llm_rerank":
            reason = str(item.get("reason") or "").strip()
            explain = str(item.get("explain") or "").strip()
            if reason:
                row["reason"] = reason[:40]
            if explain:
                row["explain"] = explain[:150]
        slim.append(row)
    block: dict = {
        "date": day,
        "source": source,
        "symbols": slim,
    }
    for key in STATUS_KEYS:
        if status and key in status:
            block[key] = status[key]
    if model_key == "gpt":
        latest["daily_picks"] = block  # legacy top-level = gpt (compat)
    # Per-model view for PM checks / web switch: latest.models.<key>.pick_status
    models = latest.get("models") if isinstance(latest.get("models"), dict) else {}
    mblock = dict(block)
    mblock["model"] = (status or {}).get("model") or model_id_for(model_key)
    mblock["label"] = MODEL_LABELS.get(model_key, model_key)
    mblock["backfill"] = PICK_BACKFILL
    models[model_key] = mblock
    latest["models"] = models
    tmp = LATEST_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(latest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(LATEST_PATH)
    print(f"[write_daily_picks] merged {model_key} picks into {LATEST_PATH} source={source} n={len(slim)}", flush=True)


def write_picks(
    day: str,
    symbols: list[dict[str, str]],
    source: str,
    *,
    extra: dict | None = None,
    path: Path | None = None,
) -> Path:
    target = path or (PICKS_DIR / f"{day}.json")
    target.parent.mkdir(parents=True, exist_ok=True)
    payload: dict = {"date": day, "symbols": symbols, "source": source}
    if extra:
        payload.update(extra)
    import sys as _sys  # pick_guard (PM 2026-09-29): lock at 09:25 next trading day + re-pick records
    _sys.path.insert(0, str(Path(__file__).resolve().parent))
    import pick_guard as _pg
    _pg.safe_guard_write(target, day, payload)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target


def pick_attempts() -> int:
    try:
        return max(1, int((os.environ.get("LLM_PICK_ATTEMPTS") or "3").strip()))
    except ValueError:
        return 3


def retry_backoffs() -> list[float]:
    raw = (os.environ.get("LLM_RETRY_BACKOFF_S") or "20,60").strip()
    out: list[float] = []
    for part in raw.split(","):
        try:
            out.append(max(0.0, float(part)))
        except ValueError:
            continue
    return out or [20.0, 60.0]


def paused_result(reason: str, attempts: int, base: dict | None = None) -> tuple[list, str, dict]:
    """序3 Option B: pause the day — never emit source=rule_order Top5."""
    extra = dict(base or {})
    extra.update({
        "pick_status": "paused",
        "paused": True,
        "fault": True,
        "source_track": "paused",
        "fallback_policy": "pause_no_rule_order",
        "pause_reason": reason,
        "attempts": attempts,
        "pick_status_at": now_sh_iso(),
    })
    print(
        f"[write_daily_picks] ALERT: pick PAUSED (序3 no silent rule_order) "
        f"attempts={attempts} reason={reason}",
        file=sys.stderr,
        flush=True,
    )
    return [], "paused", extra


def details_min_share() -> float:
    try:
        return min(1.0, max(0.0, float((os.environ.get("PICK_DETAILS_MIN_SHARE") or "0.9").strip())))
    except ValueError:
        return 0.9


def details_date_check(latest: dict, day: str) -> tuple[bool, str]:
    """Guard: candidates' details must end on the signal day.

    Share of strategy-union symbols whose details ohlcv_60d last bar == day must
    be >= PICK_DETAILS_MIN_SHARE (default 0.9; suspended names legitimately lack
    the bar). Otherwise the picker would see stale prices -> pause, no retry.
    """
    from collections import Counter

    # Scan-date guard (2026-09-29): the rule scan must have seen the signal day.
    # main.py records scan_day_rows = stocks with a bar on the scan's calendar day.
    if latest.get("scan_calendar_day") == day and isinstance(latest.get("scan_day_rows"), int):
        cov = count_stock_daily(day) or 0
        rows = latest["scan_day_rows"]
        need_s = details_min_share()
        print(f"[write_daily_picks] scan date check day={day} scan_rows={rows} db_rows_now={cov} max_date_at_scan={latest.get('scan_data_max_date')}", flush=True)
        if cov <= 0 or rows < need_s * cov:
            return False, (
                f"data date wrong: rule scan saw {rows}/{cov} stocks on signal day {day} "
                f"(latest bar at scan {latest.get('scan_data_max_date')}), need >= {need_s:.0%}"
            )

    union: set[str] = set()
    for strat in latest.get("strategies") or []:
        for raw in strat.get("symbols") or []:
            code = str(raw.get("code") if isinstance(raw, dict) else raw or "").zfill(6)
            if code.isdigit() and len(code) == 6:
                union.add(code)
    last_dates: Counter = Counter()
    for code in union:
        path = DETAILS_DIR / f"{code}.json"
        last = None
        try:
            bars = json.loads(path.read_text(encoding="utf-8")).get("ohlcv_60d") or []
            last = str(bars[-1].get("date"))[:10] if bars else None
        except (OSError, json.JSONDecodeError, AttributeError):
            last = None
        last_dates[last or "missing"] += 1
    total = sum(last_dates.values())
    on_day = last_dates.get(day, 0)
    need = details_min_share()
    common = last_dates.most_common(1)[0][0] if last_dates else "missing"
    summary = f"{on_day}/{total} candidates on signal day, need >= {need:.0%}"
    print(f"[write_daily_picks] details date check day={day} {summary} dist={dict(last_dates.most_common(4))}", flush=True)
    if total == 0 or on_day < need * total:
        return False, f"data date wrong: details latest {common} != signal day {day} ({summary})"
    return True, summary


def select_llm_or_rule(
    latest: dict,
    day: str | None = None,
    model_key: str = "gpt",
    guard: tuple[bool, str] | None = None,
) -> tuple[list[dict[str, str]], str, dict]:
    """Main-path selection for one model. Retries, then pauses (序3 Option B; never rule_order)."""
    model_id = model_id_for(model_key)
    tag = {"model": model_id, "model_key": model_key, "backfill": PICK_BACKFILL}
    if not llm_rerank_enabled():
        return paused_result("LLM_RERANK disabled (LLM_RERANK!=1)", 0, tag)
    if guard is None and day and (os.environ.get("PICK_SKIP_DATE_GUARD") or "0").strip() != "1":
        guard = details_date_check(latest, day)
    if guard is not None and not guard[0]:
        return paused_result(guard[1], 0, tag)
    cfg = resolve_api_config(model_id)
    print(
        f"[write_daily_picks] LLM_RERANK=1 model={cfg['model']} "
        f"feature_ver={FEATURE_VER} prompt_ver={PROMPT_VER} "
        f"base={cfg['base_url']} key={'set' if cfg['api_key'] else 'MISSING'} "
        f"timeout_s={cfg['timeout']}",
        flush=True,
    )
    max_n = pick_attempts()
    backoffs = retry_backoffs()
    result: dict = {}
    attempts = 0
    for _ in range(max_n):
        attempts += 1
        print(f"[write_daily_picks] llm attempt {attempts}/{max_n}", flush=True)
        result = rerank_top5(latest, DETAILS_DIR, model=model_id)
        if result.get("ok"):
            symbols = result["symbols"]
            extra = {
                "model": result.get("model"),
                "model_key": model_key,
                "backfill": PICK_BACKFILL,
                "feature_ver": result.get("feature_ver", FEATURE_VER),
                "prompt_ver": result.get("prompt_ver", PROMPT_VER),
                "candidate_count": result.get("candidate_count"),
                "pick_status": "ok",
                "attempts": attempts,
                "pick_status_at": now_sh_iso(),
            }
            if result.get("strategy_review"):
                extra["strategy_review"] = result["strategy_review"]
            if result.get("rejected_note"):
                extra["rejected_note"] = result["rejected_note"]
            print(
                f"[write_daily_picks] llm_rerank ok attempts={attempts} prompt_ver={extra.get('prompt_ver')} "
                f"candidates={extra.get('candidate_count')} "
                f"reviews={len(result.get('strategy_review') or [])}",
                flush=True,
            )
            return symbols, "llm_rerank", extra
        reason = str(result.get("error") or "llm_failed")
        print(f"[write_daily_picks] attempt {attempts}/{max_n} failed: {reason}", file=sys.stderr, flush=True)
        if not result.get("retryable", True):
            break
        if attempts < max_n:
            wait = backoffs[min(attempts - 1, len(backoffs) - 1)]
            print(f"[write_daily_picks] retry in {wait:.0f}s", flush=True)
            time.sleep(wait)
    base = {
        "model": result.get("model") or cfg["model"],
        "model_key": model_key,
        "backfill": PICK_BACKFILL,
        "feature_ver": result.get("feature_ver", FEATURE_VER),
        "prompt_ver": result.get("prompt_ver", PROMPT_VER),
        "candidate_count": result.get("candidate_count"),
    }
    # Non-retryable failures (key missing / no candidates) never reach the API.
    api_attempts = attempts if result.get("retryable", True) else 0
    return paused_result(str(result.get("error") or "llm_failed"), api_attempts, base)


def write_shadow_multi_hit(day: str, latest: dict, main_codes: list[str]) -> None:
    """Side-file only: never merges into latest.json / watch_calendar live Top5."""
    shadow_syms = multi_hit_top5(latest)
    path = write_picks(
        day,
        shadow_syms,
        "multi_hit",
        extra={"track": "multi_hit_shadow"},
        path=SHADOW_DIR / f"{day}.multi_hit.json",
    )
    shadow_codes = [s["code"] for s in shadow_syms]
    print(
        f"[write_daily_picks] shadow track=multi_hit_shadow "
        f"main=[{','.join(main_codes)}] "
        f"multi_hit=[{','.join(shadow_codes)}] -> {path}",
        flush=True,
    )


def main(argv: list[str]) -> int:
    args = list(argv)
    models_arg: str | None = None
    for a in list(args):
        if a.startswith("--models="):
            models_arg = a.split("=", 1)[1]
            args.remove(a)
    use_theo = False
    if args and args[0] == "--theo":
        use_theo = True
        args = args[1:]
    day = args[0] if args else today_sh()

    if use_theo:
        print("[error] --theo Top5 backfill disabled; use scripts/backfill_daily_picks.py", file=sys.stderr)
        return 2

    if not LATEST_PATH.exists():
        print(f"[error] missing {LATEST_PATH}", file=sys.stderr)
        return 1

    # Phase0 gate: incomplete K → skip picks (do not corrupt calendar)
    if not coverage_ok(day):
        return 3

    latest = json.loads(LATEST_PATH.read_text(encoding="utf-8"))
    mode = pick_mode()
    print(f"[write_daily_picks] PICK_MODE={mode}", flush=True)

    if mode == "multi_hit":
        # Reached only when ALLOW_MULTI_HIT_MAIN=1 (see pick_mode hard gate).
        symbols = multi_hit_top5(latest)
        if not symbols:
            print("[error] no symbols extracted from latest.json", file=sys.stderr)
            return 1
        path = write_picks(day, symbols, "multi_hit", extra={"track": "multi_hit_main"})
        merge_daily_picks_into_latest(day, symbols, "multi_hit")
        print(
            f"wrote {path} source=multi_hit track=multi_hit_main "
            f"symbols=[{','.join(s['code'] for s in symbols)}]",
            flush=True,
        )
        return 0

    # llm / shadow: every enabled model on the SAME pool; one shared data-date guard.
    keys = enabled_pick_models(models_arg)
    guard: tuple[bool, str] | None = None
    if llm_rerank_enabled() and (os.environ.get("PICK_SKIP_DATE_GUARD") or "0").strip() != "1":
        guard = details_date_check(latest, day)
    print(f"[write_daily_picks] models={keys}", flush=True)
    rc = 0
    for key in keys:
        print(f"[write_daily_picks] ===== model {key} ({model_id_for(key)}) =====", flush=True)
        try:
            symbols, source, extra = select_llm_or_rule(latest, day, model_key=key, guard=guard)
        except Exception as exc:  # noqa: BLE001 - one model failing must not stop the other
            symbols, source, extra = paused_result(
                f"internal error: {type(exc).__name__}: {str(exc)[:200]}", 0,
                {"model": model_id_for(key), "model_key": key, "backfill": PICK_BACKFILL},
            )
        target = picks_dir_for(PICKS_DIR, key) / f"{day}.json"
        if source == "paused" or not symbols:
            if source != "paused":
                symbols, source, extra = paused_result("no symbols returned", 0, extra)
            # Guard: never masquerade as llm_rerank / rule_order on failure.
            assert source == "paused", source
            path = write_picks(day, [], "paused", extra=extra, path=target)
            merge_daily_picks_into_latest(day, [], "paused", extra, model_key=key)
            print(
                f"[{key}] wrote {path} source=paused pick_status=paused "
                f"source_track=paused fault=true attempts={extra.get('attempts')}",
                flush=True,
            )
            # 序3/序5: on LLM fail, still emit multi_hit shadow for对照 (main stays paused).
            if mode == "shadow" and key == "gpt":
                write_shadow_multi_hit(day, latest, [])
            rc = 4
            continue
        if len(symbols) < 5:
            print(f"[warn] {key}: only {len(symbols)} symbols", file=sys.stderr)
        path = write_picks(day, symbols, source, extra=extra or None, path=target)
        merge_daily_picks_into_latest(day, symbols, source, extra, model_key=key)
        codes = [s["code"] for s in symbols]
        print(f"[{key}] wrote {path} source={source} symbols=[{','.join(codes)}]", flush=True)
        if mode == "shadow" and key == "gpt":
            write_shadow_multi_hit(day, latest, codes)
    return rc


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
