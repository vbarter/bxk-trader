#!/usr/bin/env python3
"""Rebuild multi_hit _shadow for historical signal days via as-of strategy replay.

PICK_MODE=shadow only landed 2026-09-21; 09-17/09-18 never got shadow files.
Method = multi_hit_top5(latest) — same as write_shadow_from_latest / write_daily_picks.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

# DataEngine uses relative db_path; always run from repo root.
import os
os.chdir(ROOT)


from sequoia_x.core.config import get_settings
from sequoia_x.data.engine import DataEngine
from sequoia_x.strategy.high_tight_flag import HighTightFlagStrategy
from sequoia_x.strategy.limit_up_shakeout import LimitUpShakeoutStrategy
from sequoia_x.strategy.ma_volume import MaVolumeStrategy
from sequoia_x.strategy.rps_breakout import RpsBreakoutStrategy
from sequoia_x.strategy.turtle_trade import TurtleTradeStrategy
from sequoia_x.strategy.uptrend_limit_down import UptrendLimitDownStrategy
from llm_rerank import multi_hit_top5

DATA_DIR = ROOT / "data"
DETAILS_DIR = DATA_DIR / "details"
SHADOW_DIR = DATA_DIR / "daily_picks" / "_shadow"
LATEST_PATH = DATA_DIR / "latest.json"
DB_PATH = DATA_DIR / "sequoia_v2.db"


def load_names() -> dict[str, str]:
    names: dict[str, str] = {}
    if LATEST_PATH.exists():
        try:
            latest = json.loads(LATEST_PATH.read_text(encoding="utf-8"))
            for k, v in (latest.get("names") or {}).items():
                if isinstance(v, str) and v.strip():
                    names[str(k).zfill(6)] = v.strip()
        except (OSError, json.JSONDecodeError):
            pass
    if DETAILS_DIR.exists():
        for path in DETAILS_DIR.glob("*.json"):
            code = path.stem.zfill(6)
            if code in names:
                continue
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            name = payload.get("name")
            if isinstance(name, str) and name.strip():
                names[code] = name.strip()
    return names


def patch_engine_asof(engine: DataEngine, asof: str) -> None:
    orig = engine.get_ohlcv

    def get_ohlcv_asof(symbol: str) -> pd.DataFrame:
        df = orig(symbol)
        if df is None or df.empty or "date" not in df.columns:
            return df
        return df[df["date"] <= asof].reset_index(drop=True)

    engine.get_ohlcv = get_ohlcv_asof  # type: ignore[method-assign]


def patch_rps_asof(asof: str) -> None:
    def run(self) -> list[str]:  # noqa: ANN001
        import gc

        try:
            with sqlite3.connect(self.engine.db_path) as conn:
                lookback_days = max(self.rps_period * 2 + 40, 280)
                df = pd.read_sql(
                    "SELECT symbol, date, close, high FROM stock_daily "
                    "WHERE date <= ? AND date >= date(?, ?)",
                    conn,
                    params=(asof, asof, f"-{lookback_days} days"),
                )
        except Exception as exc:  # noqa: BLE001
            from sequoia_x.core.logger import get_logger

            get_logger(__name__).error(f"读取数据库失败: {exc}")
            return []

        if df.empty:
            return []

        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values(["symbol", "date"])
        df["close_shift"] = df.groupby("symbol")["close"].shift(self.rps_period)
        df["pct_change"] = (df["close"] - df["close_shift"]) / df["close_shift"]

        latest_date = pd.Timestamp(asof)
        latest_df = df[df["date"] == latest_date].copy().dropna(subset=["pct_change"])
        if latest_df.empty:
            return []

        latest_df["rps"] = latest_df["pct_change"].rank(pct=True) * 100
        strong = latest_df[latest_df["rps"] >= self.rps_threshold].copy()

        roll_high = (
            df.groupby("symbol")["high"]
            .rolling(window=self.rps_period, min_periods=self.rps_period // 2)
            .max()
            .reset_index(level=0, drop=True)
        )
        df["roll_high"] = roll_high
        latest_roll = df[df["date"] == latest_date][["symbol", "roll_high"]]
        del df
        gc.collect()
        strong = strong.merge(latest_roll, on="symbol")
        selected = strong[strong["close"] >= strong["roll_high"] * 0.90]
        from sequoia_x.core.logger import get_logger

        get_logger(__name__).info(
            f"RpsBreakoutStrategy(asof={asof}) 选出 {len(selected)} 只股票"
        )
        out = selected["symbol"].tolist()
        del latest_df, strong, selected, latest_roll
        gc.collect()
        return out

    RpsBreakoutStrategy.run = run  # type: ignore[method-assign]


def patch_turtle_caps_asof(asof: str) -> None:
    """Skip live today caps — keep discovery order (stable for multi_hit)."""

    def _get_market_caps(self, symbols: list[str]) -> dict[str, float]:  # noqa: ANN001
        # Equal caps → preserve original candidate order from scan.
        return {s: float(len(symbols) - i) for i, s in enumerate(symbols)}

    TurtleTradeStrategy._get_market_caps = _get_market_caps  # type: ignore[method-assign]


def coverage(asof: str) -> int:
    with sqlite3.connect(DB_PATH) as conn:
        return int(
            conn.execute(
                "SELECT COUNT(DISTINCT symbol) FROM stock_daily WHERE date = ?",
                (asof,),
            ).fetchone()[0]
        )


def run_asof(asof: str, names: dict[str, str], min_cov: int = 4000) -> list[dict[str, str]]:
    cov = coverage(asof)
    print(f"[backfill_shadow] asof={asof} coverage={cov}", flush=True)
    if cov < min_cov:
        raise SystemExit(f"coverage too low for {asof}: {cov} < {min_cov}")

    settings = get_settings()
    engine = DataEngine(settings)
    patch_engine_asof(engine, asof)
    patch_rps_asof(asof)
    patch_turtle_caps_asof(asof)

    strategies = [
        MaVolumeStrategy(engine=engine, settings=settings),
        TurtleTradeStrategy(engine=engine, settings=settings),
        HighTightFlagStrategy(engine=engine, settings=settings),
        LimitUpShakeoutStrategy(engine=engine, settings=settings),
        UptrendLimitDownStrategy(engine=engine, settings=settings),
        RpsBreakoutStrategy(engine=engine, settings=settings),
    ]

    results: list[dict[str, Any]] = []
    for strategy in strategies:
        selected = strategy.run()
        print(f"[backfill_shadow] {type(strategy).__name__} n={len(selected)}", flush=True)
        results.append({"name": type(strategy).__name__, "symbols": selected})

    results.append({"name": "PrivatePlacementStrategy", "symbols": []})
    results.append({"name": "BowlReboundStrategy", "symbols": []})

    latest = {
        "generated_at": f"{asof}T00:00:00+08:00",
        "mode": "shadow_asof_backfill",
        "strategies": results,
        "names": names,
    }
    shadow = multi_hit_top5(latest)
    SHADOW_DIR.mkdir(parents=True, exist_ok=True)
    path = SHADOW_DIR / f"{asof}.multi_hit.json"
    payload = {
        "date": asof,
        "symbols": shadow,
        "source": "multi_hit",
        "offline": True,
        "asof_backfill": True,
        "coverage": cov,
        "strategies_note": "local strategies only; private+bowl empty",
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    codes = [x["code"] for x in shadow]
    print(f"[backfill_shadow] wrote {path} multi_hit={codes}", flush=True)

    snap = SHADOW_DIR / f"{asof}.strategies.json"
    snap.write_text(
        json.dumps({"date": asof, "strategies": results, "coverage": cov}, ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )
    return shadow


def main() -> int:
    days = sys.argv[1:] or ["2026-09-17", "2026-09-18"]
    names = load_names()
    print(f"[backfill_shadow] names loaded={len(names)}", flush=True)
    for day in days:
        run_asof(day, names)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
