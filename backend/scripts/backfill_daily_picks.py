#!/usr/bin/env python3
"""As-of replay strategies → write data/daily_picks/YYYY-MM-DD.json.

For each A-share trading day R in [start, end], truncate bars to date<=R,
run the same strategy order as main.py / 15:05 close scan, take unique
symbols in display order (first 5), write the same shape as
write_daily_picks.py.

Usage:
  .venv/bin/python scripts/backfill_daily_picks.py
  .venv/bin/python scripts/backfill_daily_picks.py --start 2026-08-11 --end 2026-09-09
  .venv/bin/python scripts/backfill_daily_picks.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
import sys
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from sequoia_x.core.config import get_settings  # noqa: E402
from sequoia_x.data.engine import DataEngine  # noqa: E402
from sequoia_x.strategy.bowl_rebound import BowlReboundStrategy  # noqa: E402
from sequoia_x.strategy.high_tight_flag import HighTightFlagStrategy  # noqa: E402
from sequoia_x.strategy.limit_up_shakeout import LimitUpShakeoutStrategy  # noqa: E402
from sequoia_x.strategy.ma_volume import MaVolumeStrategy  # noqa: E402
from sequoia_x.strategy.private_placement import PrivatePlacementStrategy  # noqa: E402
from sequoia_x.strategy.rps_breakout import RpsBreakoutStrategy  # noqa: E402
from sequoia_x.strategy.turtle_trade import TurtleTradeStrategy  # noqa: E402
from sequoia_x.strategy.uptrend_limit_down import UptrendLimitDownStrategy  # noqa: E402

SH_TZ = ZoneInfo("Asia/Shanghai")
PICKS_DIR = ROOT / "data" / "daily_picks"
DETAILS_DIR = ROOT / "data" / "details"
CACHE_PATH = ROOT / "data" / "market_cap_cache.json"
DB_PATH = ROOT / "data" / "sequoia_v2.db"

# Keep existing real (non-theo) picks unless --force. Theo placeholders are
# always overwritten when we produce real as-of picks.
REAL_SOURCES = {"latest_strategies_unique_first5", "asof_strategies_unique_first5"}
THEO_PLACEHOLDER = {"000626", "301072", "000700", "002868", "605088"}


class AsOfEngine:
    """DataEngine-compatible view truncated to as_of (inclusive)."""

    def __init__(self, db_path: str | Path, as_of: str, base: DataEngine) -> None:
        self.db_path = str(db_path)
        self.as_of = as_of
        self._base = base
        self._symbols: list[str] | None = None
        # Reuse one connection for the day (read-only).
        self._conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass

    def get_ohlcv(self, symbol: str) -> pd.DataFrame:
        # Limit lookback: Bowl needs ~119, RPS 120 — keep 160.
        df = pd.read_sql(
            """
            SELECT * FROM (
              SELECT symbol, date, open, high, low, close, volume, turnover
              FROM stock_daily
              WHERE symbol = ? AND date <= ? AND close IS NOT NULL AND volume > 0
              ORDER BY date DESC
              LIMIT 160
            ) t
            ORDER BY date ASC
            """,
            self._conn,
            params=(symbol, self.as_of),
        )
        return df

    def get_local_symbols(self) -> list[str]:
        if self._symbols is None:
            rows = self._conn.execute(
                """
                SELECT DISTINCT symbol FROM stock_daily
                WHERE date = ? AND close IS NOT NULL AND volume > 0
                ORDER BY symbol
                """,
                (self.as_of,),
            ).fetchall()
            self._symbols = [r[0] for r in rows]
        return self._symbols

    def _to_baostock_code(self, symbol: str) -> str:
        return self._base._to_baostock_code(symbol)


class AsOfRpsBreakoutStrategy(RpsBreakoutStrategy):
    """RPS reads full SQL; restrict to bars through as_of and signal day = as_of."""

    def __init__(self, engine: AsOfEngine, settings: Any, as_of: str) -> None:
        super().__init__(engine=engine, settings=settings)
        self.as_of = as_of

    def run(self) -> list[str]:
        try:
            with sqlite3.connect(self.engine.db_path) as conn:
                df = pd.read_sql(
                    "SELECT symbol, date, close, high FROM stock_daily "
                    "WHERE date <= ? AND close IS NOT NULL",
                    conn,
                    params=(self.as_of,),
                )
        except Exception as exc:
            print(f"[warn] RpsBreakout as-of read failed: {exc}", file=sys.stderr)
            return []

        if df.empty:
            return []

        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values(["symbol", "date"])
        as_of_ts = pd.Timestamp(self.as_of)

        df["close_shift"] = df.groupby("symbol")["close"].shift(self.rps_period)
        df["pct_change"] = (df["close"] - df["close_shift"]) / df["close_shift"]

        latest_df = df[df["date"] == as_of_ts].copy()
        latest_df = latest_df.dropna(subset=["pct_change"])
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
        df = df.copy()
        df["roll_high"] = roll_high
        latest_roll = df[df["date"] == as_of_ts][["symbol", "roll_high"]]
        strong = strong.merge(latest_roll, on="symbol")
        selected = strong[strong["close"] >= strong["roll_high"] * 0.90]
        return selected["symbol"].tolist()


class AsOfTurtleTradeStrategy(TurtleTradeStrategy):
    """Avoid live date.today() market-cap API; sort by turnover instead when as-of."""

    def _get_market_caps(self, symbols: list[str]) -> dict[str, float]:
        # Prefer cache; fall back to last-bar turnover as a stable sort key.
        caps: dict[str, float] = {}
        if CACHE_PATH.exists():
            try:
                payload = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
                raw = payload.get("caps") or {}
                for s in symbols:
                    v = raw.get(s)
                    if v is not None:
                        caps[s] = float(v)
            except (OSError, json.JSONDecodeError, TypeError, ValueError):
                pass
        missing = [s for s in symbols if s not in caps]
        for s in missing:
            try:
                df = self.engine.get_ohlcv(s)
                if not df.empty and "turnover" in df.columns:
                    caps[s] = float(df.iloc[-1]["turnover"] or 0)
                else:
                    caps[s] = 0.0
            except Exception:
                caps[s] = 0.0
        return caps


class AsOfPrivatePlacementStrategy(PrivatePlacementStrategy):
    def __init__(self, engine: Any, settings: Any, as_of: str) -> None:
        super().__init__(engine=engine, settings=settings)
        self.as_of = as_of

    def run(self) -> list[str]:
        # Historical akshare snapshot unavailable; approximate with as_of cutoff
        # against the live feed (old announcements still listed). Empty is fine.
        try:
            import akshare as ak

            df = ak.stock_qbzf_em()
        except Exception as exc:
            print(f"[warn] PrivatePlacement as-of fetch failed: {exc}", file=sys.stderr)
            return []
        if df is None or df.empty:
            return []
        df = df[df["发行方式"] == "定向增发"]
        if df.empty:
            return []
        as_of_d = date.fromisoformat(self.as_of)
        cutoff = as_of_d - __import__("datetime").timedelta(days=self._LOOKBACK_DAYS)
        df = df.copy()
        df["发行日期"] = pd.to_datetime(df["发行日期"], errors="coerce")
        df = df.dropna(subset=["发行日期"])
        df = df[
            (df["发行日期"].dt.date >= cutoff) & (df["发行日期"].dt.date <= as_of_d)
        ]
        if df.empty:
            return []
        df = df.sort_values("发行日期", ascending=False)
        symbols = df["股票代码"].astype(str).str.extract(r"(\d{6})")[0].dropna().tolist()
        seen: set[str] = set()
        out: list[str] = []
        for s in symbols:
            if s not in seen:
                seen.add(s)
                out.append(s)
        return out


class AsOfBowlReboundStrategy(BowlReboundStrategy):
    """Reuse latest market_cap_cache regardless of cache date (bars are as-of)."""

    def _load_market_cache(self) -> tuple[dict[str, float], dict[str, str]]:
        if not CACHE_PATH.exists():
            return {}, {}
        try:
            payload = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}, {}
        caps_raw = payload.get("caps") or {}
        names_raw = payload.get("names") or {}
        caps = {
            str(k).zfill(6): float(v)
            for k, v in caps_raw.items()
            if v is not None
        }
        names = {str(k).zfill(6): str(v) for k, v in names_raw.items()}
        return caps, names


def load_names() -> dict[str, str]:
    names: dict[str, str] = {}
    if CACHE_PATH.exists():
        try:
            payload = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
            for k, v in (payload.get("names") or {}).items():
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
                name = json.loads(path.read_text(encoding="utf-8")).get("name")
                if isinstance(name, str) and name.strip():
                    names[code] = name.strip()
            except (OSError, json.JSONDecodeError):
                continue
    return names


def trading_days(start: str, end: str) -> list[str]:
    with sqlite3.connect(DB_PATH) as conn:
        # Prefer days with broad coverage (not spot-open stubs).
        rows = conn.execute(
            """
            SELECT date, COUNT(*) AS n,
                   SUM(CASE WHEN close IS NOT NULL AND volume > 0 THEN 1 ELSE 0 END) AS good
            FROM stock_daily
            WHERE date >= ? AND date <= ?
            GROUP BY date
            ORDER BY date
            """,
            (start, end),
        ).fetchall()
    days: list[str] = []
    for d, n, good in rows:
        # A-share trading day with meaningful coverage.
        if good and good >= 1000:
            days.append(d)
        else:
            print(
                f"[warn] {d}: skip/thin coverage n={n} good={good}",
                flush=True,
            )
    return days


def coverage(day: str) -> tuple[int, int]:
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            """
            SELECT COUNT(*),
                   SUM(CASE WHEN close IS NOT NULL AND volume > 0 THEN 1 ELSE 0 END)
            FROM stock_daily WHERE date = ?
            """,
            (day,),
        ).fetchone()
    return int(row[0] or 0), int(row[1] or 0)


def picks_from_strategies(
    settings: Any,
    base_engine: DataEngine,
    as_of: str,
    stop_at: int = 5,
) -> tuple[list[str], list[tuple[str, int]]]:
    engine = AsOfEngine(DB_PATH, as_of, base_engine)
    try:
        n_sym = len(engine.get_local_symbols())
        if n_sym < 1000:
            print(f"[warn] {as_of}: only {n_sym} symbols with good bars — thin", flush=True)

        strategy_ctors: list[tuple[str, Any]] = [
            ("MaVolumeStrategy", lambda: MaVolumeStrategy(engine=engine, settings=settings)),
            ("TurtleTradeStrategy", lambda: AsOfTurtleTradeStrategy(engine=engine, settings=settings)),
            ("HighTightFlagStrategy", lambda: HighTightFlagStrategy(engine=engine, settings=settings)),
            ("LimitUpShakeoutStrategy", lambda: LimitUpShakeoutStrategy(engine=engine, settings=settings)),
            ("UptrendLimitDownStrategy", lambda: UptrendLimitDownStrategy(engine=engine, settings=settings)),
            ("RpsBreakoutStrategy", lambda: AsOfRpsBreakoutStrategy(engine=engine, settings=settings, as_of=as_of)),
            ("PrivatePlacementStrategy", lambda: AsOfPrivatePlacementStrategy(engine=engine, settings=settings, as_of=as_of)),
            ("BowlReboundStrategy", lambda: AsOfBowlReboundStrategy(engine=engine, settings=settings)),
        ]

        seen: list[str] = []
        counts: list[tuple[str, int]] = []
        for name, ctor in strategy_ctors:
            if len(seen) >= stop_at:
                # Still record skipped for transparency? Skip to save time.
                counts.append((name, -1))  # -1 = not run (already have enough)
                continue
            t0 = time.time()
            try:
                selected = ctor().run()
            except Exception as exc:
                print(f"[warn] {as_of} {name} failed: {exc}", file=sys.stderr, flush=True)
                selected = []
            counts.append((name, len(selected)))
            print(
                f"  {name}: {len(selected)} in {time.time()-t0:.1f}s",
                flush=True,
            )
            for code in selected:
                code = str(code).zfill(6)
                if code not in seen:
                    seen.append(code)
                if len(seen) >= stop_at:
                    break
        return seen[:stop_at], counts
    finally:
        engine.close()


def existing_payload(day: str) -> dict[str, Any] | None:
    path = PICKS_DIR / f"{day}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def is_theo_placeholder(payload: dict[str, Any] | None) -> bool:
    if not payload:
        return False
    if payload.get("source") == "theo_top5_backfill":
        return True
    codes = []
    for item in payload.get("symbols") or []:
        if isinstance(item, dict):
            codes.append(str(item.get("code", "")).zfill(6))
        else:
            codes.append(str(item).zfill(6))
    return set(codes) == THEO_PLACEHOLDER


def should_write(
    day: str,
    new_codes: list[str],
    force: bool,
) -> tuple[bool, str]:
    prev = existing_payload(day)
    if force:
        return True, "force"
    if not prev:
        return True, "missing"
    if is_theo_placeholder(prev):
        return True, "replace_theo"
    src = prev.get("source") or ""
    if src in REAL_SOURCES and len(new_codes) >= 5:
        # Prefer fresh as-of replay over stale live snapshot when both real.
        old_codes = [
            str(s.get("code") if isinstance(s, dict) else s).zfill(6)
            for s in (prev.get("symbols") or [])
        ]
        if old_codes == new_codes:
            return False, "unchanged"
        # Improve: overwrite with as-of (true signal-day bars).
        return True, "replace_with_asof"
    if src in REAL_SOURCES and len(new_codes) < 5:
        return False, "keep_real_thin_asof"
    return True, "default"


def write_picks(day: str, codes: list[str], names: dict[str, str]) -> Path:
    PICKS_DIR.mkdir(parents=True, exist_ok=True)
    symbols = [
        {"code": c, "name": names.get(c) or c}
        for c in codes
    ]
    payload = {
        "date": day,
        "symbols": symbols,
        "source": "asof_strategies_unique_first5",
    }
    path = PICKS_DIR / f"{day}.json"
    import sys as _sys  # pick_guard (PM 2026-09-29): lock at 09:25 next trading day + re-pick records
    _sys.path.insert(0, str(Path(__file__).resolve().parent))
    import pick_guard as _pg
    _pg.safe_guard_write(path, day, payload)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Backfill daily_picks via as-of strategy replay")
    parser.add_argument("--start", default="2026-08-11")
    parser.add_argument("--end", default="2026-09-09")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true", help="Overwrite even existing real picks")
    parser.add_argument(
        "--all-strategies",
        action="store_true",
        help="Always run all strategies (slower); default stops once 5 unique picks exist",
    )
    args = parser.parse_args(argv)

    if not DB_PATH.exists():
        print(f"[error] missing {DB_PATH}", file=sys.stderr)
        return 1

    settings = get_settings()
    base_engine = DataEngine(settings)
    names = load_names()

    # Include thin days in the candidate list from calendar, but skip if coverage bad.
    with sqlite3.connect(DB_PATH) as conn:
        all_days = [
            r[0]
            for r in conn.execute(
                "SELECT DISTINCT date FROM stock_daily WHERE date >= ? AND date <= ? ORDER BY date",
                (args.start, args.end),
            ).fetchall()
        ]
    # Also ensure we attempt end date even if only stubs exist (after sync).
    print(f"candidate days in DB: {all_days}", flush=True)

    days = []
    for d in all_days:
        n, good = coverage(d)
        if good >= 1000:
            days.append(d)
        else:
            print(f"[skip] {d}: coverage n={n} good={good} (<1000)", flush=True)

    if not days:
        print("[error] no trading days with adequate coverage", file=sys.stderr)
        return 1

    print(f"backfill days ({len(days)}): {days}", flush=True)
    results: list[tuple[str, list[str], str]] = []

    for day in days:
        print(f"=== {day} ===", flush=True)
        t0 = time.time()
        stop_at = 5 if not args.all_strategies else 10_000
        codes, counts = picks_from_strategies(
            settings, base_engine, day, stop_at=5 if not args.all_strategies else 10_000
        )
        # If stop_at was large, still only keep first 5 for file.
        codes5 = codes[:5]
        print(
            f"  union_first5={codes5} counts={counts} elapsed={time.time()-t0:.1f}s",
            flush=True,
        )
        if len(codes5) < 5:
            print(f"[warn] {day}: only {len(codes5)} picks", flush=True)

        ok, reason = should_write(day, codes5, force=args.force)
        if not ok:
            print(f"  skip write ({reason})", flush=True)
            results.append((day, codes5, f"skipped:{reason}"))
            continue
        if args.dry_run:
            print(f"  dry-run would write ({reason})", flush=True)
            results.append((day, codes5, f"dry-run:{reason}"))
            continue
        if not codes5:
            print(f"  skip write: empty", flush=True)
            results.append((day, codes5, "skipped:empty"))
            continue
        path = write_picks(day, codes5, names)
        print(f"  wrote {path} ({reason})", flush=True)
        results.append((day, codes5, reason))

    print("--- summary ---", flush=True)
    for day, codes, reason in results:
        print(f"{day} [{reason}] {','.join(codes)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
