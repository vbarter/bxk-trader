"""Pick-model registry (dual model since 2026-09-29 close_pm).

Same candidate pool / prompt / top-5 rule / settlement for every model; only the
LLM differs. gpt keeps the legacy paths (data/daily_picks/<day>.json, top-level
watch_calendar days, latest.daily_picks). Other models live under
data/daily_picks/<key>/<day>.json and watch_calendar tracks.<key>.days.
"""
from __future__ import annotations

import os
from pathlib import Path

MODEL_KEYS = ("gpt", "claude")
MODEL_LABELS = {"gpt": "GPT-6.1 Sol", "claude": "Claude Opus 5.5"}
DEFAULT_IDS = {"gpt": "gpt-6.1-sol", "claude": "claude-opus-5-5"}


def model_id_for(key: str) -> str:
    if key == "gpt":
        return (os.environ.get("LLM_MODEL") or os.environ.get("OPENAI_MODEL") or DEFAULT_IDS["gpt"]).strip()
    if key == "claude":
        return (os.environ.get("LLM_MODEL_CLAUDE") or DEFAULT_IDS["claude"]).strip()
    raise KeyError(key)


def claude_enabled() -> bool:
    """ENABLE_CLAUDE=0|false|no pauses Claude compute (default 0 as of 2026-10-02)."""
    v = (os.environ.get("ENABLE_CLAUDE") or "0").strip().lower()
    return v not in {"0", "false", "no", "off", ""}


def enabled_pick_models(raw: str | None = None) -> list[str]:
    """PICK_MODELS list (default gpt only when Claude paused). Order kept, gpt first.

    Claude is dropped when ENABLE_CLAUDE is off, even if listed in PICK_MODELS.
    Historical Claude picks under data/daily_picks/claude/ are not deleted.
    """
    default = "gpt,claude" if claude_enabled() else "gpt"
    raw = raw if raw is not None else (os.environ.get("PICK_MODELS") or default)
    keys = [k.strip().lower() for k in raw.split(",") if k.strip()]
    out = [k for k in MODEL_KEYS if k in keys]
    if not claude_enabled():
        out = [k for k in out if k != "claude"]
    return out or ["gpt"]


def picks_dir_for(picks_root: Path, key: str) -> Path:
    return picks_root if key == "gpt" else picks_root / key


def all_picks_dirs(picks_root: Path) -> dict[str, Path]:
    return {k: picks_dir_for(picks_root, k) for k in MODEL_KEYS}


# Archived live batches (e.g. the real 2026-09-24 gpt batch replaced by a backfill):
# data/daily_picks/_archived/<key>/<day>.json. Still bought/sold and settled like a
# normal batch, shown nowhere in the grid and excluded from totals.
ARCHIVE_SUBDIR = "_archived"


def archive_dir_for(picks_root: Path, key: str) -> Path:
    return picks_root / ARCHIVE_SUBDIR / key


def all_archive_dirs(picks_root: Path) -> dict[str, Path]:
    return {k: archive_dir_for(picks_root, k) for k in MODEL_KEYS}
