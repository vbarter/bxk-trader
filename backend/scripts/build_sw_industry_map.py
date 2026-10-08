#!/usr/bin/env python3
"""Build Shenwan industry map cache for Sequoia-X industry view.

Source of truth: akshare 申万 APIs (NOT Tonghuashun *_ths).
Output: data/sw_industry_map.csv
  symbol,name,sw_l1_code,sw_l1_name,sw_l2_code,sw_l2_name,industry_group
"""

from __future__ import annotations

import csv
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import akshare as ak
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
OUT_CSV = DATA_DIR / "sw_industry_map.csv"
SH = ZoneInfo("Asia/Shanghai")


def industry_group(sw_l1_name: str, sw_l2_name: str | None, sw_l2_code: str | None) -> str:
    l2_name = sw_l2_name or ""
    l2_code = (sw_l2_code or "").replace(".SI", "")
    if "半导体" in l2_name or l2_code == "801081":
        return "半导体"
    return sw_l1_name or "未分类"


def pad_symbol(value: object) -> str:
    text = str(value).strip()
    if text.endswith(".0") and text.replace(".", "", 1).isdigit():
        text = text[:-2]
    digits = "".join(ch for ch in text if ch.isdigit())
    if len(digits) >= 6:
        return digits[-6:].zfill(6)
    return digits.zfill(6) if digits else text


def main() -> int:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    print(f"akshare={getattr(ak, '__version__', 'unknown')}", flush=True)

    l1 = ak.sw_index_first_info()
    l2 = ak.sw_index_second_info()
    print(f"L1={len(l1)} L2={len(l2)}", flush=True)

    # Map L1 name -> code (and keep order)
    l1_code_by_name: dict[str, str] = {}
    l1_order: list[str] = []
    for _, row in l1.iterrows():
        code = str(row["行业代码"]).strip()
        name = str(row["行业名称"]).strip()
        l1_code_by_name[name] = code
        l1_order.append(name)

    rows: dict[str, dict[str, str]] = {}
    errors = 0
    for index, (_, row) in enumerate(l2.iterrows(), start=1):
        l2_code_raw = str(row["行业代码"]).strip()
        l2_name = str(row["行业名称"]).strip()
        parent_name = str(row.get("上级行业", "")).strip()
        l2_code = l2_code_raw.replace(".SI", "")
        l1_name = parent_name or ""
        l1_code = l1_code_by_name.get(l1_name, "")
        try:
            cons = ak.index_component_sw(symbol=l2_code)
        except Exception as exc:  # noqa: BLE001
            errors += 1
            print(f"[warn] {l2_code} {l2_name}: {exc}", file=sys.stderr, flush=True)
            time.sleep(0.4)
            continue
        if cons is None or cons.empty:
            print(f"[warn] empty cons {l2_code} {l2_name}", file=sys.stderr, flush=True)
            continue
        code_col = "证券代码" if "证券代码" in cons.columns else cons.columns[0]
        name_col = "证券名称" if "证券名称" in cons.columns else (
            cons.columns[1] if len(cons.columns) > 1 else None
        )
        for _, crow in cons.iterrows():
            symbol = pad_symbol(crow[code_col])
            if len(symbol) != 6:
                continue
            name = str(crow[name_col]).strip() if name_col is not None else ""
            group = industry_group(l1_name, l2_name, l2_code_raw)
            # Prefer first hit; if duplicate across L2, keep existing unless current is 半导体
            prev = rows.get(symbol)
            if prev and prev["industry_group"] == "半导体" and group != "半导体":
                continue
            rows[symbol] = {
                "symbol": symbol,
                "name": name,
                "sw_l1_code": l1_code,
                "sw_l1_name": l1_name,
                "sw_l2_code": l2_code_raw if l2_code_raw.endswith(".SI") else f"{l2_code}.SI",
                "sw_l2_name": l2_name,
                "industry_group": group,
            }
        if index == 1 or index % 10 == 0 or index == len(l2):
            print(f"[{index}/{len(l2)}] mapped={len(rows)} errors={errors}", flush=True)
        time.sleep(0.05)

    # Unclassified from A-share universe
    try:
        universe = ak.stock_info_a_code_name()
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] stock_info_a_code_name failed: {exc}", file=sys.stderr, flush=True)
        universe = pd.DataFrame()

    unclassified = 0
    if not universe.empty:
        code_col = "code" if "code" in universe.columns else universe.columns[0]
        name_col = "name" if "name" in universe.columns else universe.columns[1]
        for _, urow in universe.iterrows():
            symbol = pad_symbol(urow[code_col])
            if len(symbol) != 6 or symbol in rows:
                continue
            rows[symbol] = {
                "symbol": symbol,
                "name": str(urow[name_col]).strip(),
                "sw_l1_code": "",
                "sw_l1_name": "未分类",
                "sw_l2_code": "",
                "sw_l2_name": "",
                "industry_group": "未分类",
            }
            unclassified += 1

    ordered = sorted(rows.values(), key=lambda item: item["symbol"])
    with OUT_CSV.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "symbol",
                "name",
                "sw_l1_code",
                "sw_l1_name",
                "sw_l2_code",
                "sw_l2_name",
                "industry_group",
            ],
        )
        writer.writeheader()
        writer.writerows(ordered)

    semi = sum(1 for item in ordered if item["industry_group"] == "半导体")
    elec = sum(1 for item in ordered if item["industry_group"] == "电子")
    mapped = sum(1 for item in ordered if item["industry_group"] != "未分类")
    built = datetime.now(SH).strftime("%Y-%m-%d %H:%M:%S CST")
    print(
        f"Wrote {OUT_CSV} rows={len(ordered)} mapped={mapped} unclassified={unclassified} "
        f"semi={semi} elec_view={elec} l1={len(l1_order)} l2={len(l2)} errors={errors} built={built}",
        flush=True,
    )
    return 0 if errors == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
