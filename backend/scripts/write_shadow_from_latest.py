#!/usr/bin/env python3
"""Offline: write _shadow from current latest.json without touching main picks."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from llm_rerank import multi_hit_top5, rule_order_top5  # noqa: E402


def main() -> int:
    latest = json.loads((ROOT / "data" / "latest.json").read_text(encoding="utf-8"))
    dp = latest.get("daily_picks") or {}
    day = dp.get("date")
    if not day:
        gen = str(latest.get("generated_at") or "")[:10]
        day = gen if len(gen) == 10 else "unknown"
    shadow = multi_hit_top5(latest)
    path = ROOT / "data" / "daily_picks" / "_shadow" / f"{day}.multi_hit.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"date": day, "symbols": shadow, "source": "multi_hit", "track": "multi_hit_shadow", "offline": True}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    main_codes = [
        str(x.get("code")).zfill(6)
        for x in (dp.get("symbols") or [])
        if isinstance(x, dict)
    ]
    shadow_codes = [x["code"] for x in shadow]
    print(f"wrote {path}")
    print(
        "compare main=["
        + ",".join(main_codes)
        + "] multi_hit=["
        + ",".join(shadow_codes)
        + "]"
    )
    print("rule_order=" + str([x["code"] for x in rule_order_top5(latest)]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
