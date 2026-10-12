"""海龟交易策略：20日新高突破 + 成交额过亿 + 动量阳线过滤。"""

import json
from datetime import date
from pathlib import Path

import pandas as pd

from sequoia_x.core.logger import get_logger
from sequoia_x.strategy.base import BaseStrategy

logger = get_logger(__name__)

# baostock 100020xx：网络错误 / 连接失败 / Broken pipe 之后的接收失败。
_BS_NET_ERR_PREFIX = "100020"


class TurtleTradeStrategy(BaseStrategy):
    """海龟交易策略（A股防诱多改良版）。

    选股条件（向量化，严禁 iterrows）：
    1. 突破新高：今日 close > 前20个交易日 high 的最大值
    2. 流动性：今日 turnover > 100,000,000
    3. 防诱多过滤：今日必须是实体阳线（今日 close > 今日 open），且必须真涨（今日 close > 昨日 close）

    Attributes:
        webhook_key: 路由到 'turtle' 专属飞书机器人。
    """

    webhook_key: str = "turtle"
    _MIN_BARS: int = 21  # 至少需要 21 根 K 线（20日窗口 + 当日）

    def _get_market_caps(self, symbols: list[str]) -> dict[str, float]:
        """流通市值：不复权收盘价 × 流通股本。baostock 失败时用本地缓存补，不中断扫描。

        流通股本 = 成交量 / (换手率% / 100)
        流通市值 = 流通股本 × 不复权收盘价

        baostock 正常返回时，结果与原先逐只查询一致，不读缓存。
        登录失败、连接断开（含 query 内部 IndexError）、或单只空行/短行时，
        失败的代码改用 data/market_cap_cache.json 的总市值排序；缓存也没有则
        该只排序键为 0（与原先缺市值相同），并打 warning。
        """
        if not symbols:
            return {}

        market_caps, failed = self._query_baostock_caps(symbols)
        if not failed:
            return market_caps

        cached = self._caps_from_local_cache(failed)
        market_caps.update(cached)
        still = [s for s in failed if s not in market_caps]
        if still:
            preview = ",".join(still[:20])
            suffix = f" 等{len(still)}只" if len(still) > 20 else ""
            logger.warning(
                f"TurtleTradeStrategy 市值不可用，跳过市值排序：{preview}{suffix}"
            )
        return market_caps

    def _query_baostock_caps(self, symbols: list[str]) -> tuple[dict[str, float], list[str]]:
        """返回 (成功的流通市值, 需要回退的代码)。干净的空结果不算失败。"""
        import baostock as bs

        today_str = date.today().strftime("%Y-%m-%d")
        market_caps: dict[str, float] = {}
        failed: list[str] = []
        logged_in = False
        try:
            try:
                lg = bs.login()
            except Exception as exc:
                logger.warning(f"TurtleTradeStrategy baostock 登录异常，市值改走缓存：{exc}")
                return {}, list(symbols)
            logged_in = True
            if str(getattr(lg, "error_code", "0")) != "0":
                logger.warning(
                    "TurtleTradeStrategy baostock 登录失败："
                    f"{getattr(lg, 'error_code', '')} {getattr(lg, 'error_msg', '')}，市值改走缓存"
                )
                return {}, list(symbols)

            session_dead = False
            for symbol in symbols:
                try:
                    outcome, cap = self._baostock_cap_one(bs, symbol, today_str)
                except Exception as exc:
                    logger.warning(
                        f"[{symbol}] baostock 市值查询异常，剩余股票改走缓存：{exc}"
                    )
                    failed.append(symbol)
                    session_dead = True
                    break
                if outcome == "ok" and cap is not None:
                    market_caps[symbol] = cap
                elif outcome == "empty":
                    continue
                elif outcome == "dead":
                    failed.append(symbol)
                    session_dead = True
                    break
                else:
                    failed.append(symbol)
            if session_dead:
                seen = set(market_caps) | set(failed)
                failed.extend(s for s in symbols if s not in seen)
        finally:
            if logged_in:
                try:
                    bs.logout()
                except Exception as exc:
                    logger.warning(f"TurtleTradeStrategy baostock logout 失败：{exc}")
        return market_caps, failed

    def _baostock_cap_one(
        self, bs: object, symbol: str, today_str: str
    ) -> tuple[str, float | None]:
        """单只查询。返回 ok / empty / bad_row / dead。"""
        try:
            rs = bs.query_history_k_data_plus(  # type: ignore[attr-defined]
                self.engine._to_baostock_code(symbol),
                "close,volume,turn",
                start_date=today_str,
                end_date=today_str,
                frequency="d",
                adjustflag="3",  # 不复权，真实价格
            )
        except Exception as exc:
            # 连接断开后的残包会在 baostock history.py 里对 header_arr/body_arr 下标，
            # 抛 IndexError，不会回到我们自己的 row[0]。
            logger.warning(f"[{symbol}] baostock 市值查询异常，剩余股票改走缓存：{exc}")
            return "dead", None

        if rs is None:
            logger.warning(f"[{symbol}] baostock 市值查询返回空，剩余股票改走缓存")
            return "dead", None

        code = str(getattr(rs, "error_code", "0"))
        if code != "0":
            msg = getattr(rs, "error_msg", "")
            logger.warning(f"[{symbol}] baostock 市值查询失败 {code} {msg}")
            if code.startswith(_BS_NET_ERR_PREFIX):
                return "dead", None
            return "bad_row", None

        while rs.next():
            try:
                row = rs.get_row_data() or []
            except Exception as exc:
                logger.warning(f"[{symbol}] baostock 市值行读取失败：{exc}")
                return "bad_row", None
            if len(row) < 3:
                # next() 在 data 非空时仍返回 True；空记录 [] 会让 row[0] IndexError。
                logger.warning(
                    f"[{symbol}] baostock 市值结果为空或字段不足（len={len(row)}），跳过"
                )
                return "bad_row", None
            try:
                close = float(row[0])
                volume = float(row[1])
                turn = float(row[2])
            except (TypeError, ValueError, IndexError):
                continue
            if turn > 0:
                circulating_shares = volume / (turn / 100)
                return "ok", circulating_shares * close
        # 有行但换手率为 0 / 无法解析，或根本没行：旧逻辑不写市值。
        # 不算失败，不用总市值缓存顶上，排序键仍是 0。
        return "empty", None

    def _caps_from_local_cache(self, symbols: list[str]) -> dict[str, float]:
        """market_cap_cache.json 的总市值。只补 baostock 失败的代码。"""
        if not symbols:
            return {}
        cache_path = Path(self.settings.db_path).resolve().parent / "market_cap_cache.json"
        wanted = {s.zfill(6): s for s in symbols}
        if not cache_path.exists():
            logger.warning(f"TurtleTradeStrategy 市值缓存不存在：{cache_path}")
            return {}
        try:
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeError) as exc:
            logger.warning(f"TurtleTradeStrategy 读取市值缓存失败：{exc}")
            return {}
        raw = payload.get("caps") if isinstance(payload, dict) else None
        if not isinstance(raw, dict):
            logger.warning(f"TurtleTradeStrategy 市值缓存缺少 caps：{cache_path}")
            return {}

        out: dict[str, float] = {}
        for key, val in raw.items():
            code = str(key).zfill(6)
            symbol = wanted.get(code)
            if symbol is None:
                continue
            try:
                num = float(val)
            except (TypeError, ValueError):
                continue
            if num > 0:
                out[symbol] = num
        cache_date = payload.get("date") if isinstance(payload, dict) else None
        logger.warning(
            f"TurtleTradeStrategy baostock 市值失败，使用缓存 {cache_path} "
            f"date={cache_date} 补齐 {len(out)}/{len(symbols)} 只（缓存为总市值，仅失败路径）"
        )
        return out

    def run(self) -> list[str]:
        """
        遍历全市场，返回满足海龟突破条件的股票代码列表。
        """
        symbols = self.engine.get_local_symbols()
        candidates: list[str] = []

        for symbol in symbols:
            try:
                df = self.engine.get_ohlcv(symbol)
                if len(df) < self._MIN_BARS:
                    continue

                # 向量化：前20日 high 的滚动最大值（不含当日，shift(1) 后取 rolling(20)）
                df["high_20"] = df["high"].shift(1).rolling(20).max()

                last = df.iloc[-1]
                prev = df.iloc[-2]  # 获取昨日数据，用于对比

                if pd.isna(last["high_20"]):
                    continue

                # 核心条件 1：突破前 20 天最高点
                breakout = last["close"] > last["high_20"]
                # 核心条件 2：流动性过亿
                liquid = last["turnover"] > 100_000_000

                # 【新增防守条件】拒绝郑州煤电式的高开低走大阴线！
                is_yang = last["close"] > last["open"]   # 实体必须是阳线（红柱）
                is_up = last["close"] > prev["close"]    # 必须是真涨，不能是假阳线

                if breakout and liquid and is_yang and is_up:
                    candidates.append(symbol)

            except Exception as exc:
                logger.warning(f"[{symbol}] TurtleTradeStrategy 计算失败：{exc}")
                continue

        # 按流通市值从大到小排序
        if candidates:
            market_caps = self._get_market_caps(candidates)
            candidates.sort(key=lambda s: market_caps.get(s, 0), reverse=True)

        logger.info(f"TurtleTradeStrategy 选出 {len(candidates)} 只股票")
        return candidates