"""碗口反弹策略：上升趋势内回踩+近异动+J低位。

核心逻辑移植自 a-share-quant-selector strategy/bowl_rebound.py（MIT），
不跑对方 main/Flask/钉钉/B1。参数按现网 yaml 冻结。

结构指标使用本地 stock_daily（后复权）即可；结算/展示仍走不复权链路。
缺市值一律剔除，不做估算放行。
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import requests

from sequoia_x.core.logger import get_logger
from sequoia_x.strategy.base import BaseStrategy

logger = get_logger(__name__)
SH_TZ = ZoneInfo("Asia/Shanghai")

# Frozen yaml params (config/strategy_params.yaml runtime truth)
_N = 2
_M = 30
_CAP = 40e8  # 40亿
_J_VAL = 20.0
_DUOKONG_PCT = 0.87  # percent
_SHORT_PCT = 1.0  # percent
_M1, _M2, _M3, _M4 = 14, 28, 57, 114
_MIN_BARS = _M4 + 5  # need enough history for 知行多空


def _today_sh() -> str:
    return datetime.now(SH_TZ).strftime("%Y-%m-%d")


def _ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False, min_periods=1).mean()


def _kdj_j(df: pd.DataFrame, n: int = 9, m1: int = 3, m2: int = 3) -> pd.Series:
    """通达信风格 KDJ，输入为正序（早→晚）。返回 J 序列。"""
    low_min = df["low"].rolling(window=n, min_periods=1).min()
    high_max = df["high"].rolling(window=n, min_periods=1).max()
    range_val = high_max - low_min
    rsv = pd.Series(50.0, index=df.index, dtype=float)
    valid = range_val != 0
    # 前 n-1 根不足窗口时用 50（与源实现一致）
    enough = pd.Series(df.index >= n - 1, index=df.index)
    rsv.loc[valid & enough] = (
        (df["close"] - low_min) / range_val * 100
    ).loc[valid & enough]

    k = pd.Series(0.0, index=df.index, dtype=float)
    d = pd.Series(0.0, index=df.index, dtype=float)
    k.iloc[0] = 50.0
    d.iloc[0] = 50.0
    for i in range(1, len(df)):
        k.iloc[i] = (rsv.iloc[i] * 1 + k.iloc[i - 1] * (m1 - 1)) / m1
        d.iloc[i] = (k.iloc[i] * 1 + d.iloc[i - 1] * (m2 - 1)) / m2
    return 3 * k - 2 * d


def _invalid_name(name: str) -> bool:
    if not name:
        return False
    if name.startswith("ST") or name.startswith("*ST"):
        return True
    for kw in ("退", "未知", "退市", "已退"):
        if kw in name:
            return True
    return False


class BowlReboundStrategy(BaseStrategy):
    """碗口反弹选股。

    条件（最新交易日）：
    1. 知行短期趋势线 > 知行多空线
    2. 近 M 日存在关键阳线：量≥前日×N 且 C>O 且总市值>CAP
    3. 回顾期最大量那天不能是阴线
    4. KDJ(9,3,3) J ≤ J_VAL
    5. 位置：回落碗中 / 靠近多空±duokong% / 靠近短期±short%
    6. 过滤 ST/*ST/退市、量=0、近30日 |J| 均值>80；缺市值剔除
    """

    webhook_key: str = "bowl_rebound"

    def run(self) -> list[str]:
        caps, names = self._load_market_cache()
        if not caps:
            logger.error("BowlReboundStrategy 市值缓存为空，整批跳过（缺市值不放行）")
            return []

        symbols = self.engine.get_local_symbols()
        selected: list[str] = []
        skipped_no_cap = 0

        for symbol in symbols:
            try:
                name = names.get(symbol, "")
                if _invalid_name(name):
                    continue

                mcap = caps.get(symbol)
                if mcap is None or mcap <= 0:
                    skipped_no_cap += 1
                    continue
                if mcap <= _CAP:
                    continue

                df = self.engine.get_ohlcv(symbol)
                if len(df) < _MIN_BARS:
                    continue

                if self._match(df, mcap):
                    selected.append(symbol)
            except Exception as exc:
                logger.warning(f"[{symbol}] 碗口反弹计算失败：{exc}")
                continue

        logger.info(
            f"BowlReboundStrategy 选出 {len(selected)} 只；缺市值剔除 {skipped_no_cap}"
        )
        return selected

    def _match(self, df: pd.DataFrame, mcap: float) -> bool:
        df = df.sort_values("date").reset_index(drop=True)
        latest = df.iloc[-1]
        if latest["volume"] is None or float(latest["volume"]) <= 0:
            return False
        if pd.isna(latest["close"]):
            return False

        close = df["close"].astype(float)
        open_ = df["open"].astype(float)
        volume = df["volume"].astype(float)

        short_term = _ema(_ema(close, 10), 10)
        bull_bear = (
            close.rolling(_M1, min_periods=1).mean()
            + close.rolling(_M2, min_periods=1).mean()
            + close.rolling(_M3, min_periods=1).mean()
            + close.rolling(_M4, min_periods=1).mean()
        ) / 4

        j = _kdj_j(df)

        # 近 30 日 |J| 均值过热
        j_tail = j.tail(30)
        if j_tail.abs().mean() > 80:
            return False

        i = len(df) - 1
        if not (short_term.iloc[i] > bull_bear.iloc[i]):
            return False
        if not (j.iloc[i] <= _J_VAL):
            return False

        c = float(close.iloc[i])
        st = float(short_term.iloc[i])
        bb = float(bull_bear.iloc[i])
        duokong = _DUOKONG_PCT / 100.0
        short_pct = _SHORT_PCT / 100.0

        fall_in_bowl = bb <= c <= st
        near_duokong = bb * (1 - duokong) <= c <= bb * (1 + duokong)
        near_short = st * (1 - short_pct) <= c <= st * (1 + short_pct)
        if not (fall_in_bowl or near_duokong or near_short):
            return False

        lookback = df.tail(_M)
        if lookback.empty:
            return False

        # 最大量那天不能是阴线
        max_idx = lookback["volume"].astype(float).idxmax()
        max_row = lookback.loc[max_idx]
        if float(max_row["close"]) < float(max_row["open"]):
            return False

        # 关键阳线：量≥前日×N 且阳线；市值已在外层按 CAP 过滤（整段用最新市值）
        # 需要前日量：在全序列上算 ratio，再限制到 lookback 窗口
        prev_vol = volume.shift(1)
        vol_ok = (volume >= prev_vol * _N) & prev_vol.notna() & (prev_vol > 0)
        yang = close > open_
        key = vol_ok & yang
        # 市值条件：有有效市值且 > CAP（已保证），关键期内统一视为达标
        key_lookback = key.loc[lookback.index]
        if not bool(key_lookback.any()):
            return False

        return True

    def _load_market_cache(self) -> tuple[dict[str, float], dict[str, str]]:
        """加载/刷新市值+名称缓存。缺源则空 dict（调用方整批剔除）。"""
        cache_path = Path(self.settings.db_path).resolve().parent / "market_cap_cache.json"
        today = _today_sh()

        if cache_path.exists():
            try:
                payload = json.loads(cache_path.read_text(encoding="utf-8"))
                if payload.get("date") == today and isinstance(payload.get("caps"), dict):
                    caps = {
                        str(k).zfill(6): float(v)
                        for k, v in payload["caps"].items()
                        if v is not None
                    }
                    names = {
                        str(k).zfill(6): str(v)
                        for k, v in (payload.get("names") or {}).items()
                    }
                    if caps:
                        logger.info(f"市值缓存命中 {cache_path}，{len(caps)} 只")
                        return caps, names
            except Exception as exc:
                logger.warning(f"读取市值缓存失败：{exc}")

        caps, names = self._fetch_market_caps()
        if caps:
            try:
                cache_path.write_text(
                    json.dumps(
                        {"date": today, "caps": caps, "names": names, "source": "eastmoney/tencent"},
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )
                logger.info(f"市值缓存已写入 {cache_path}，{len(caps)} 只")
            except Exception as exc:
                logger.warning(f"写入市值缓存失败：{exc}")
        return caps, names

    def _fetch_market_caps(self) -> tuple[dict[str, float], dict[str, str]]:
        caps: dict[str, float] = {}
        names: dict[str, str] = {}

        # 1) 东方财富全市场列表（海外可达）
        try:
            caps, names = self._fetch_eastmoney_clist()
            if caps:
                return caps, names
        except Exception as exc:
            logger.warning(f"eastmoney 市值拉取失败：{exc}")

        # 2) 腾讯行情批量（总市值字段）
        try:
            caps, names = self._fetch_tencent_caps()
            if caps:
                return caps, names
        except Exception as exc:
            logger.warning(f"tencent 市值拉取失败：{exc}")

        # 3) akshare spot（国内源，海外常失败）
        try:
            import akshare as ak

            df = ak.stock_zh_a_spot_em()
            code_col = "代码" if "代码" in df.columns else None
            cap_col = "总市值" if "总市值" in df.columns else None
            name_col = "名称" if "名称" in df.columns else None
            if code_col and cap_col:
                for _, row in df.iterrows():
                    code = str(row[code_col]).zfill(6)
                    try:
                        val = float(row[cap_col])
                    except (TypeError, ValueError):
                        continue
                    if val > 0:
                        caps[code] = val
                    if name_col and isinstance(row[name_col], str):
                        names[code] = row[name_col]
                if caps:
                    return caps, names
        except Exception as exc:
            logger.warning(f"akshare 市值拉取失败：{exc}")

        return {}, {}

    def _fetch_eastmoney_clist(self) -> tuple[dict[str, float], dict[str, str]]:
        url = "https://push2.eastmoney.com/api/qt/clist/get"
        fs = "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048"
        fields = "f12,f14,f20"
        caps: dict[str, float] = {}
        names: dict[str, str] = {}
        page = 1
        page_size = 100
        total = None
        session = requests.Session()
        session.headers.update(
            {
                "User-Agent": "Mozilla/5.0",
                "Referer": "https://quote.eastmoney.com/",
            }
        )

        while True:
            params = {
                "pn": page,
                "pz": page_size,
                "po": 1,
                "np": 1,
                "fltt": 2,
                "invt": 2,
                "fid": "f12",
                "fs": fs,
                "fields": fields,
            }
            resp = session.get(url, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json().get("data") or {}
            if total is None:
                total = int(data.get("total") or 0)
            diff = data.get("diff") or []
            if not diff:
                break
            for item in diff:
                code = str(item.get("f12") or "").zfill(6)
                if len(code) != 6:
                    continue
                raw = item.get("f20")
                try:
                    # fltt=2 时 f20 已是元；偶发 "-" 
                    if raw in (None, "-", ""):
                        continue
                    val = float(raw)
                except (TypeError, ValueError):
                    continue
                if val > 0:
                    caps[code] = val
                name = item.get("f14")
                if isinstance(name, str) and name.strip():
                    names[code] = name.strip()
            if total is not None and page * page_size >= total:
                break
            page += 1
            if page > 80:  # safety
                break
            time.sleep(0.05)

        logger.info(f"eastmoney 市值 {len(caps)} 只，名称 {len(names)}")
        return caps, names

    def _fetch_tencent_caps(self) -> tuple[dict[str, float], dict[str, str]]:
        """腾讯行情：字段 45 附近为总市值（元）。批量 50 只。"""
        symbols = self.engine.get_local_symbols()
        caps: dict[str, float] = {}
        names: dict[str, str] = {}

        def to_q(sym: str) -> str:
            if sym.startswith(("5", "6", "9")):
                return f"sh{sym}"
            if sym.startswith(("4", "8")):
                return f"bj{sym}"
            return f"sz{sym}"

        session = requests.Session()
        session.headers.update({"User-Agent": "Mozilla/5.0"})
        batch = 50
        for i in range(0, len(symbols), batch):
            chunk = symbols[i : i + batch]
            q = ",".join(to_q(s) for s in chunk)
            url = f"https://qt.gtimg.cn/q={q}"
            try:
                text = session.get(url, timeout=20).text
            except Exception:
                continue
            for line in text.split(";"):
                line = line.strip()
                if not line or "~" not in line:
                    continue
                # v_sh600000="1~名称~600000~..."
                try:
                    body = line.split("=", 1)[1].strip().strip('"')
                except IndexError:
                    continue
                parts = body.split("~")
                if len(parts) < 46:
                    continue
                code = parts[2].zfill(6) if parts[2].isdigit() else ""
                if not code:
                    continue
                name = parts[1]
                # 腾讯总市值：常见在 index 45，单位元；也可能是「亿」字符串——优先数字
                raw = parts[45]
                try:
                    val = float(raw)
                except (TypeError, ValueError):
                    continue
                if val > 0:
                    # 若数值小得离谱（<1e8），可能是「亿」单位
                    if val < 1e8:
                        val *= 1e8
                    caps[code] = val
                if name:
                    names[code] = name
            time.sleep(0.05)

        logger.info(f"tencent 市值 {len(caps)} 只")
        return caps, names
