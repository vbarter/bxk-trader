#!/usr/bin/env python3
"""Annotate watch_calendar.json llm track days with pick_source from daily_picks.source.

Also sets tracks.llm.label to 主轨 Top5 and tracks.llm.source to daily_picks
so UI never implies every day is llm_rerank. multi_hit days get pick_source=multi_hit
(or missing when shadow_missing). Does not rebuild settlements.
After dual_basis, runs source_track_kpi (序1): kpi_by_source.true_llm is the only
block labeled 真 LLM; product actual/rerun totals stay unlabeled as llm_rerank.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Allow running from /workspace/tmp-dual-track OR /root/dev/Sequoia-X/scripts
if (ROOT / "data" / "watch_calendar.json").exists():
    DATA_DIR = ROOT / "data"
elif (Path("/root/dev/Sequoia-X/data/watch_calendar.json")).exists():
    DATA_DIR = Path("/root/dev/Sequoia-X/data")
else:
    DATA_DIR = Path("/workspace/sequoia-x-web/data")

PICKS_DIR = DATA_DIR / "daily_picks"
CAL_PATH = DATA_DIR / "watch_calendar.json"


def load_sources(picks_dir: Path | None = None) -> dict[str, str]:
    out: dict[str, str] = {}
    picks_dir = picks_dir or PICKS_DIR
    if not picks_dir.exists():
        return out
    for path in sorted(picks_dir.glob("*.json")):
        if path.name.startswith("_"):
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        src = payload.get("source")
        if isinstance(src, str) and src.strip():
            out[path.stem] = src.strip()
    return out


def annotate_llm(days: list, sources: dict[str, str]) -> int:
    n = 0
    for day in days:
        if not isinstance(day, dict):
            continue
        src = sources.get(str(day.get("date") or ""))
        if src:
            day["pick_source"] = src
            n += 1
        elif not day.get("pick_source"):
            day["pick_source"] = "unknown"
    return n


def main() -> int:
    if not CAL_PATH.exists():
        print(f"missing {CAL_PATH}", file=sys.stderr)
        return 1
    sources = load_sources()
    cal = json.loads(CAL_PATH.read_text(encoding="utf-8"))
    bak = CAL_PATH.with_suffix(".json.bak.pre_pick_source")
    if not bak.exists():
        bak.write_text(CAL_PATH.read_text(encoding="utf-8"), encoding="utf-8")

    n1 = annotate_llm(cal.get("days") or [], sources)
    if (os.environ.get("MULTI_HIT_ENABLED") or "0").strip() != "1":
        # multi_hit removed 2026-09-28. Keep per-model tracks (gpt/claude);
        # drop legacy llm/multi_hit tracks only.
        tr = cal.get("tracks") if isinstance(cal.get("tracks"), dict) else {}
        tr = {k: v for k, v in tr.items() if k not in ("llm", "multi_hit")}
        for key, t in tr.items():
            if key != "gpt" and isinstance(t, dict) and isinstance(t.get("days"), list):
                annotate_llm(t["days"], load_sources(PICKS_DIR / key))
        if tr:
            cal["tracks"] = tr
        else:
            cal.pop("tracks", None)
            cal.pop("default_track", None)
        cal["generated_at"] = datetime.now(timezone.utc).isoformat()
        CAL_PATH.write_text(json.dumps(cal, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"[pick_source] wrote {CAL_PATH} top={n1} (llm only) sources={len(sources)}", flush=True)
        return 0
    tracks = cal.get("tracks") or {}
    n2 = 0
    if isinstance(tracks.get("llm"), dict):
        n2 = annotate_llm(tracks["llm"].get("days") or [], sources)
        tracks["llm"]["label"] = "主轨 Top5"
        tracks["llm"]["source"] = "daily_picks"
    if isinstance(tracks.get("multi_hit"), dict):
        for day in tracks["multi_hit"].get("days") or []:
            if not isinstance(day, dict):
                continue
            if day.get("shadow_missing"):
                day.setdefault("pick_origin", "missing")
                day["pick_source"] = "missing"
            else:
                day.setdefault("pick_source", "multi_hit")
    cal["tracks"] = tracks
    cal["generated_at"] = datetime.now(timezone.utc).isoformat()
    CAL_PATH.write_text(json.dumps(cal, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[pick_source] wrote {CAL_PATH} top={n1} llm_track={n2} sources={len(sources)}", flush=True)
    return 0


if __name__ == "__main__":
    rc = main()
    # 2026-09-29: dual-basis totals (实际推荐 / 全部回溯). Never fatal.
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import dual_basis  # noqa: E402
        dual_basis.annotate_file(CAL_PATH)
    except Exception as exc:  # pragma: no cover
        print(f"[patch_calendar_pick_source] WARN dual_basis failed: {exc!r}", file=sys.stderr)
    # 序1 2026-10-02: per-source track KPI (真 LLM vs 混轨). Never fatal.
    try:
        import source_track_kpi  # noqa: E402
        source_track_kpi.main([])
    except Exception as exc:  # pragma: no cover
        print(f"[patch_calendar_pick_source] WARN source_track_kpi failed: {exc!r}", file=sys.stderr)
    raise SystemExit(rc)
