"""Sequoia-X V2 主程序入口。

两种运行模式：
  python main.py               # 日常模式：2进程增量补数据 + 跑策略 + 飞书推送（2~3分钟）
  python main.py --backfill    # 回填模式：baostock 拉全市场历史K线（首次/补数据用，约12分钟）
"""

import argparse
import json
import sys
from dotenv import load_dotenv
load_dotenv()

from datetime import datetime, timezone
from pathlib import Path

import socket
socket.setdefaulttimeout(10.0)

from sequoia_x.core.config import get_settings
from sequoia_x.core.logger import get_logger
from sequoia_x.data.engine import DataEngine
from sequoia_x.notify.feishu import FeishuNotifier
from sequoia_x.strategy.base import BaseStrategy
from sequoia_x.strategy.high_tight_flag import HighTightFlagStrategy
from sequoia_x.strategy.limit_up_shakeout import LimitUpShakeoutStrategy
from sequoia_x.strategy.ma_volume import MaVolumeStrategy
from sequoia_x.strategy.turtle_trade import TurtleTradeStrategy
from sequoia_x.strategy.uptrend_limit_down import UptrendLimitDownStrategy
from sequoia_x.strategy.rps_breakout import RpsBreakoutStrategy
from sequoia_x.strategy.private_placement import PrivatePlacementStrategy
from sequoia_x.strategy.bowl_rebound import BowlReboundStrategy


def main() -> None:
    parser = argparse.ArgumentParser(description="Sequoia-X V2 选股系统")
    parser.add_argument(
        "--backfill",
        action="store_true",
        help="回填模式：通过 baostock 拉取全市场历史 K 线（约12分钟）",
    )
    args = parser.parse_args()

    try:
        # 1. 初始化配置
        settings = get_settings()

        # 2. 初始化日志
        logger = get_logger(__name__)
        logger.info("Sequoia-X V2 启动")

        # 3. 初始化数据引擎
        engine = DataEngine(settings)

        if args.backfill:
            # ── 回填模式：单线程保守拉历史 K 线，自动多轮重跑 ──
            logger.info("进入回填模式...")
            all_symbols = engine.get_all_symbols()
            engine.backfill(all_symbols)
            logger.info("Sequoia-X V2 回填模式运行完成")
            return

        # ── 日常模式：单次 API 补今天 + 策略 + 推送 ──
        import os
        if os.environ.get("SKIP_SYNC") == "1":
            logger.info("跳过快照同步 (SKIP_SYNC=1)")
            count = 0
        else:
            logger.info("开始拉取最新快照...")
            count = engine.sync_today_bulk()
            logger.info(f"快照同步完成，写入 {count} 只股票")

        # 4. 策略列表（新增策略在此追加即可）
        strategies: list[BaseStrategy] = [
            MaVolumeStrategy(engine=engine, settings=settings),
            TurtleTradeStrategy(engine=engine, settings=settings),
            HighTightFlagStrategy(engine=engine, settings=settings),
            LimitUpShakeoutStrategy(engine=engine, settings=settings),
            UptrendLimitDownStrategy(engine=engine, settings=settings),
            RpsBreakoutStrategy(engine=engine, settings=settings),
            PrivatePlacementStrategy(engine=engine, settings=settings),
            BowlReboundStrategy(engine=engine, settings=settings),
        ]

        # 5. 遍历策略并收集结果
        # Record what the scan actually saw (2026-09-29): the 09-28 close_pm scan ran
        # before any 09-28 bar was in stock_daily and silently scanned 09-24 data.
        import sqlite3 as _sq
        from zoneinfo import ZoneInfo as _ZI
        scan_calendar_day = datetime.now(_ZI("Asia/Shanghai")).date().isoformat()
        try:
            with _sq.connect(settings.db_path) as _c:
                scan_day_rows = int(_c.execute(
                    "SELECT COUNT(DISTINCT symbol) FROM stock_daily WHERE date=?", (scan_calendar_day,)
                ).fetchone()[0])
                scan_data_max_date = _c.execute("SELECT MAX(date) FROM stock_daily").fetchone()[0]
        except Exception:
            scan_day_rows, scan_data_max_date = None, None
        logger.info(f"scan data: day={scan_calendar_day} rows={scan_day_rows} max_date={scan_data_max_date}")

        strategy_results: list[tuple[BaseStrategy, list[str]]] = []
        for strategy in strategies:
            strategy_name = type(strategy).__name__
            logger.info(f"执行策略：{strategy_name}")

            selected: list[str] = strategy.run()
            logger.info(f"{strategy_name} 选出 {len(selected)} 只股票")
            strategy_results.append((strategy, selected))
            import gc
            gc.collect()

        # 6. 先导出只读消费端使用的结果，通知失败不会影响该文件。
        output_path = Path("data/latest.json")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", encoding="utf-8") as output_file:
            json.dump(
                {
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                    "mode": "daily",
                    "scan_calendar_day": scan_calendar_day,
                    "scan_day_rows": scan_day_rows,
                    "scan_data_max_date": scan_data_max_date,
                    "strategies": [
                        {"name": type(strategy).__name__, "symbols": selected}
                        for strategy, selected in strategy_results
                    ],
                },
                output_file,
                ensure_ascii=False,
                indent=2,
            )
            output_file.write("\n")
        logger.info(f"选股结果已导出：{output_path}")

        # 7. 有结果则推送至对应机器人；通知异常只记录，不中断日常任务。
        notifier = FeishuNotifier(settings)
        for strategy, selected in strategy_results:
            strategy_name = type(strategy).__name__

            if selected:
                try:
                    notifier.send(
                        symbols=selected,
                        strategy_name=strategy_name,
                        webhook_key=strategy.webhook_key,
                    )
                except Exception:
                    logger.exception(f"{strategy_name} 飞书通知异常，已跳过")
            else:
                logger.info(f"{strategy_name} 无选股结果，跳过推送")

    except Exception:
        try:
            _logger = get_logger(__name__)
            _logger.exception("主流程发生未捕获异常，程序终止")
        except Exception:
            import traceback
            traceback.print_exc()
        sys.exit(1)

    logger.info("Sequoia-X V2 运行完成")


if __name__ == "__main__":
    main()
