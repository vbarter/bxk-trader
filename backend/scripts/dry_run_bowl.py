#!/usr/bin/env python3
"""Dry-run BowlReboundStrategy and merge into data/latest.json."""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv("/root/dev/Sequoia-X/.env")

from sequoia_x.core.config import get_settings
from sequoia_x.data.engine import DataEngine
from sequoia_x.strategy.bowl_rebound import BowlReboundStrategy

ROOT = Path("/root/dev/Sequoia-X")


def main() -> None:
    settings = get_settings()
    engine = DataEngine(settings)
    strat = BowlReboundStrategy(engine=engine, settings=settings)
    print("running BowlReboundStrategy dry-run...", flush=True)
    selected = strat.run()
    print("count", len(selected), flush=True)
    print("sample", selected[:40], flush=True)

    path = ROOT / "data/latest.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    found = False
    for s in data.get("strategies", []):
        if s.get("name") == "BowlReboundStrategy":
            s["symbols"] = selected
            found = True
            break
    if not found:
        data.setdefault("strategies", []).append(
            {"name": "BowlReboundStrategy", "symbols": selected}
        )
    data["generated_at"] = datetime.now(timezone.utc).isoformat()
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        "latest.json updated; strategies:",
        [(x["name"], len(x["symbols"])) for x in data["strategies"]],
        flush=True,
    )

    # Re-enrich quotes/names/details for the full strategy union so homepage chips
    # (esp. BowlRebound) never stay on a stale old-pool quotes map.
    enrich = subprocess.run(
        [sys.executable, str(ROOT / "scripts/export_details.py"), "--only-missing"],
        cwd=str(ROOT),
        check=False,
    )
    if enrich.returncode != 0:
        raise SystemExit(f"export_details --only-missing failed rc={enrich.returncode}")


if __name__ == "__main__":
    main()
