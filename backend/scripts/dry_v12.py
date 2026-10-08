#!/usr/bin/env python3
"""One-day dry run for prompt_ver=v1.2 (does not overwrite daily_picks)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from llm_rerank import (  # noqa: E402
    DEFAULT_MODEL,
    FEATURE_VER,
    PROMPT_VER,
    rerank_top5,
    resolve_api_config,
    rule_order_top5,
)


def main() -> int:
    cfg = resolve_api_config()
    print(
        "cfg model=%s base=%s timeout=%s key_set=%s default=%s feature=%s prompt=%s"
        % (
            cfg["model"],
            cfg["base_url"],
            cfg["timeout"],
            bool(cfg["api_key"]),
            DEFAULT_MODEL,
            FEATURE_VER,
            PROMPT_VER,
        ),
        flush=True,
    )
    latest_path = ROOT / "data" / "latest.json"
    details_dir = ROOT / "data" / "details"
    latest = json.loads(latest_path.read_text(encoding="utf-8"))
    print(
        "latest generated_at=%s strategies=%s"
        % (latest.get("generated_at"), len(latest.get("strategies") or [])),
        flush=True,
    )
    result = rerank_top5(latest, details_dir)
    out = {
        "ok": result.get("ok"),
        "source": result.get("source"),
        "model": result.get("model"),
        "feature_ver": result.get("feature_ver"),
        "prompt_ver": result.get("prompt_ver"),
        "candidate_count": result.get("candidate_count"),
        "error": result.get("error"),
        "strategy_review": result.get("strategy_review"),
        "symbols": [
            {
                "code": s.get("code"),
                "name": s.get("name"),
                "reason": (s.get("reason") or "")[:40],
            }
            for s in (result.get("symbols") or [])
        ],
        "rejected_note": result.get("rejected_note"),
        "rule_order_top5": [x["code"] for x in rule_order_top5(latest)],
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    picks = ROOT / "data" / "daily_picks"
    picks.mkdir(parents=True, exist_ok=True)
    dest = picks / "_dry_v12_latest.json"
    dest.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("wrote", dest, flush=True)
    return 0 if result.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
