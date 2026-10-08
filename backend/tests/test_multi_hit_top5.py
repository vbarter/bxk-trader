#!/usr/bin/env python3
"""Unit sample: multi_hit_top5 prefer doubles, fill singles, drop ST."""
from __future__ import annotations

import sys
from pathlib import Path

# Allow import from same dir as llm_rerank.py
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from llm_rerank import multi_hit_top5, rule_order_top5  # noqa: E402


def sample_latest() -> dict:
    return {
        "names": {
            "000001": "平安银行",
            "000002": "万科A",
            "600000": "浦发银行",
            "600519": "贵州茅台",
            "000003": "ST示例",
            "300001": "特锐德",
            "300002": "神州泰岳",
        },
        "strategies": [
            {
                "name": "MaVolumeStrategy",
                "symbols": ["000001", "000003", "000002"],
            },
            {
                "name": "TurtleTradeStrategy",
                "symbols": ["000001", "600000"],
            },
            {
                "name": "HighTightFlagStrategy",
                "symbols": ["600519", "300001"],
            },
            {
                "name": "BowlReboundStrategy",
                "symbols": ["300002", "000002"],
            },
        ],
    }


def main() -> int:
    latest = sample_latest()
    picks = multi_hit_top5(latest)
    codes = [p["code"] for p in picks]
    assert "000003" not in codes, f"ST leaked: {codes}"
    # 000001 hit Ma+Turtle; 000002 hit Ma+Bowl — doubles first in union order
    assert codes[0] == "000001", codes
    assert codes[1] == "000002", codes
    # then singles in union order: 600000 (turtle), 600519 (htf), 300001 (htf)
    assert codes[2:] == ["600000", "600519", "300001"], codes
    assert len(codes) == 5
    assert len(set(codes)) == 5
    rule = [p["code"] for p in rule_order_top5(latest)]
    # rule_order does NOT drop ST in current impl — document difference
    print("multi_hit_top5 OK", codes)
    print("rule_order_top5  ", rule)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
