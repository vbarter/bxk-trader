"""海龟市值查询：baostock 故障不得中断扫描，成功路径不读缓存。"""

import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd

from sequoia_x.core.config import Settings
from sequoia_x.data.engine import DataEngine
from sequoia_x.strategy.turtle_trade import TurtleTradeStrategy


class _Result:
    def __init__(self, rows: list[list[str]], error_code: str = "0", error_msg: str = "") -> None:
        self._rows = rows
        self._i = 0
        self.error_code = error_code
        self.error_msg = error_msg

    def next(self) -> bool:
        return self._i < len(self._rows)

    def get_row_data(self) -> list[str]:
        if self._i >= len(self._rows):
            return []
        row = self._rows[self._i]
        self._i += 1
        return row


def _strategy(tmp: str) -> TurtleTradeStrategy:
    settings = Settings(
        db_path=str(Path(tmp) / "test.db"),
        start_date="2024-01-01",
        feishu_webhook_url="https://example.com/hook",
    )
    return TurtleTradeStrategy(engine=DataEngine(settings), settings=settings)


def _write_cache(tmp: str, caps: dict[str, float], day: str = "2026-10-11") -> None:
    path = Path(tmp) / "market_cap_cache.json"
    path.write_text(
        json.dumps({"date": day, "caps": caps, "names": {}, "source": "eastmoney/tencent"}),
        encoding="utf-8",
    )


def _patch_bs(login_result: _Result, query) -> MagicMock:
    fake = MagicMock()
    fake.login.return_value = login_result
    fake.query_history_k_data_plus.side_effect = query
    return fake


def _cap(close: str, volume: str, turn: str) -> float:
    return float(volume) / (float(turn) / 100) * float(close)


def test_baostock_success_ignores_cache_and_keeps_circulating_cap() -> None:
    """baostock 正常时排序键是流通市值，缓存里的总市值不参与。"""
    with tempfile.TemporaryDirectory() as tmp:
        strategy = _strategy(tmp)
        _write_cache(tmp, {"000001": 9e11, "600000": 1.0})

        def query(code, *_args, **_kwargs):
            if code == "sz.000001":
                return _Result([["10", "1000000", "1"]])  # cap = 1e9
            return _Result([["10", "2000000", "1"]])  # cap = 2e9

        fake = _patch_bs(_Result([]), query)
        with _bs(fake):
            caps = strategy._get_market_caps(["000001", "600000"])

        assert caps["000001"] == _cap("10", "1000000", "1")
        assert caps["600000"] == _cap("10", "2000000", "1")
        assert caps["600000"] > caps["000001"]
        fake.query_history_k_data_plus.assert_called()
        fake.logout.assert_called_once()


def test_query_indexerror_falls_back_to_cache_without_raising() -> None:
    """history.py 对空/短报文 body_arr[1] 抛 IndexError 时，整批改走缓存。"""
    with tempfile.TemporaryDirectory() as tmp:
        strategy = _strategy(tmp)
        _write_cache(tmp, {"000001": 3.0e10, "600000": 8.0e10})

        def query(*_args, **_kwargs):
            raise IndexError("list index out of range")

        fake = _patch_bs(_Result([]), query)
        with _bs(fake):
            caps = strategy._get_market_caps(["000001", "600000"])

        assert caps == {"000001": 3.0e10, "600000": 8.0e10}
        assert fake.query_history_k_data_plus.call_count == 1
        fake.logout.assert_called_once()


def test_empty_row_does_not_indexerror_and_uses_cache_for_that_symbol() -> None:
    """next() 为 True 但 get_row_data() 为 []：只回退这一只，其余仍用 baostock。"""
    with tempfile.TemporaryDirectory() as tmp:
        strategy = _strategy(tmp)
        _write_cache(tmp, {"000001": 3.0e10, "600000": 1.0})

        def query(code, *_args, **_kwargs):
            if code == "sz.000001":
                return _Result([[]])
            return _Result([["10", "2000000", "1"]])

        fake = _patch_bs(_Result([]), query)
        with _bs(fake):
            caps = strategy._get_market_caps(["000001", "600000"])

        assert caps["000001"] == 3.0e10
        assert caps["600000"] == _cap("10", "2000000", "1")
        assert fake.query_history_k_data_plus.call_count == 2


def test_network_error_stops_session_and_cache_fills_the_rest() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        strategy = _strategy(tmp)
        _write_cache(tmp, {"000001": 1.0e10, "600000": 2.0e10, "300001": 4.0e10})
        calls: list[str] = []

        def query(code, *_args, **_kwargs):
            calls.append(code)
            if code == "sz.000001":
                return _Result([["10", "1000000", "1"]])
            return _Result([], error_code="10002007", error_msg="网络接收错误。")

        fake = _patch_bs(_Result([]), query)
        with _bs(fake):
            caps = strategy._get_market_caps(["000001", "600000", "300001"])

        assert calls == ["sz.000001", "sh.600000"]
        assert caps["000001"] == _cap("10", "1000000", "1")
        assert caps["600000"] == 2.0e10
        assert caps["300001"] == 4.0e10


def test_login_failure_uses_cache_and_does_not_query() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        strategy = _strategy(tmp)
        _write_cache(tmp, {"000001": 5.5e9})
        fake = _patch_bs(
            _Result([], error_code="10002002", error_msg="网络连接失败"),
            lambda *_a, **_k: None,
        )
        with _bs(fake):
            caps = strategy._get_market_caps(["000001"])
        assert caps == {"000001": 5.5e9}
        fake.query_history_k_data_plus.assert_not_called()
        fake.logout.assert_called_once()


def test_login_indexerror_uses_cache() -> None:
    """login() 解析短报文时 header_arr[2] IndexError，不得冒泡。"""
    with tempfile.TemporaryDirectory() as tmp:
        strategy = _strategy(tmp)
        _write_cache(tmp, {"600519": 2.0e12})
        fake = MagicMock()
        fake.login.side_effect = IndexError("list index out of range")
        with _bs(fake):
            caps = strategy._get_market_caps(["600519"])
        assert caps == {"600519": 2.0e12}
        fake.logout.assert_not_called()
        fake.query_history_k_data_plus.assert_not_called()


def test_clean_empty_result_does_not_use_cache() -> None:
    """error_code=0 且无行：baostock 正常说今天没 bar，排序键保持缺失，不拿总市值顶上。"""
    with tempfile.TemporaryDirectory() as tmp:
        strategy = _strategy(tmp)
        _write_cache(tmp, {"000001": 9.0e11})
        fake = _patch_bs(_Result([]), lambda *_a, **_k: _Result([]))
        with _bs(fake):
            caps = strategy._get_market_caps(["000001"])
        assert caps == {}


def test_zero_turn_does_not_use_cache() -> None:
    """换手率为 0 时旧逻辑不算市值。baostock 是通的，不能改用缓存总市值。"""
    with tempfile.TemporaryDirectory() as tmp:
        strategy = _strategy(tmp)
        _write_cache(tmp, {"000001": 9.0e11})
        fake = _patch_bs(_Result([]), lambda *_a, **_k: _Result([["10", "1000", "0"]]))
        with _bs(fake):
            caps = strategy._get_market_caps(["000001"])
        assert caps == {}


def test_no_cache_skips_failed_symbol_without_raising() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        strategy = _strategy(tmp)
        fake = MagicMock()
        fake.login.side_effect = BrokenPipeError("Broken pipe")
        with _bs(fake):
            caps = strategy._get_market_caps(["000001", "600000"])
        assert caps == {}


def test_run_survives_baostock_indexerror_and_sorts_by_cache() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        strategy = _strategy(tmp)
        _write_cache(tmp, {"000001": 1.0e10, "600000": 9.0e10})
        bars = _breakout_frame()

        def get_ohlcv(_symbol: str) -> pd.DataFrame:
            return bars.copy()

        def symbols() -> list[str]:
            return ["000001", "600000"]

        strategy.engine.get_local_symbols = symbols  # type: ignore[method-assign]
        strategy.engine.get_ohlcv = get_ohlcv  # type: ignore[method-assign]
        fake = MagicMock()
        fake.login.return_value = _Result([])
        fake.query_history_k_data_plus.side_effect = IndexError("list index out of range")
        with _bs(fake):
            selected = strategy.run()
        assert selected == ["600000", "000001"]


def _breakout_frame() -> pd.DataFrame:
    rows = []
    for i in range(25):
        px = 8.0
        rows.append(
            {
                "date": f"2026-01-{(i % 28) + 1:02d}",
                "open": px,
                "high": px,
                "low": px - 0.5,
                "close": px,
                "volume": 1.0,
                "turnover": 1.0,
            }
        )
    rows[-2]["close"] = 8.0
    rows[-1].update(
        {"open": 9.0, "high": 12.0, "low": 9.0, "close": 11.0, "volume": 1.0e8, "turnover": 2.0e8}
    )
    return pd.DataFrame(rows)


class _bs:
    def __init__(self, fake: MagicMock) -> None:
        self.fake = fake
        self._prev = None

    def __enter__(self) -> MagicMock:
        self._prev = sys.modules.get("baostock")
        sys.modules["baostock"] = self.fake
        return self.fake

    def __exit__(self, *_exc: object) -> None:
        if self._prev is None:
            sys.modules.pop("baostock", None)
        else:
            sys.modules["baostock"] = self._prev
