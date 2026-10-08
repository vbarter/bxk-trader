#!/usr/bin/env python3
"""LLM Top5 rerank helpers (feature_ver=v1.1, prompt_ver=v1.2).

Builds compact candidate features from latest.json + details/*.json, calls an
OpenAI-compatible chat/completions API, validates structured JSON output.

Prompt v1.4: role=技术分析师/精选5只/次日买再下一日卖/追求高收益 at system start; v1.3 base: model default gpt-6-astra; output MUST include strategy_review
THEN top5 with reason≤40 + explain 80–150 人话. Server-side strategy summary blocks are passed into the user payload.
Features stay v1.1 (full union drop ST; code/why/industry_group/week_oc);
prompt wire uses compressed rows (why trim, woc short, denser strategy_summaries).

When LLM_RERANK is off, or API key/model/call fails / incomplete JSON, callers
fall back to rule-order Top5 (strategies display order, unique first 5).
Read/request timeouts auto-retry LLM_TIMEOUT_RETRIES times (default 2) per call
before that failure bubbles up to pause (序3 Option B; no rule_order Top5).
"""

from __future__ import annotations

import json
import os
import re
import socket
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

FEATURE_VER = "v1.1"
PROMPT_VER = "v1.4"
FALLBACK_NO_EXPLAIN = "规则排序、暂无解释"
LABEL_EXPLAIN = "推荐理由"
REASON_MAX = 40
EXPLAIN_MIN = 80
EXPLAIN_MAX = 150
WEEK_OC_BARS = 3  # compressed for gpt-6-astra reliability (~300 cands)
DEFAULT_TIMEOUT_S = 360  # shared two-phase budget; env LLM_TIMEOUT_S overrides (≥300)
DEFAULT_TIMEOUT_RETRIES = 2  # extra attempts on read/request timeout before fail→pause (序3)
DEFAULT_TEMPERATURE = 0.3
# OpenAI-compatible root that already includes /v1 (chat path = {base}/chat/completions).
# tu-zi: https://api.tu-zi.com/v1  (also accept https://api.tu-zi.com → auto-append /v1)
DEFAULT_BASE_URL = "https://api.tu-zi.com/v1"
DEFAULT_MODEL = "gpt-6.1-sol"
SAMPLE_CODES_PER_STRATEGY = 3  # denser strategy_summaries for prompt size

# Class name -> (UI display name, frozen short blurb ≤40 字)
STRATEGY_META: dict[str, tuple[str, str]] = {
    "MaVolumeStrategy": ("均线放量", "5日线上穿20日线且放量确认"),
    "TurtleTradeStrategy": ("海龟突破", "20日新高+成交额过亿+阳线过滤"),
    "HighTightFlagStrategy": ("高窄旗形", "急涨后窄幅整理再突破"),
    "LimitUpShakeoutStrategy": ("涨停洗盘", "涨停后回踩确认再启动"),
    "UptrendLimitDownStrategy": ("上升跌停", "上升趋势中跌停反包"),
    "RpsBreakoutStrategy": ("RPS突破", "相对强度强势突破"),
    "PrivatePlacementStrategy": ("定增监控", "定增公告相关监控信号"),
    "BowlReboundStrategy": ("碗口反弹", "上升趋势回踩碗口近异动"),
}


def warn(msg: str) -> None:
    print(f"[llm_rerank] {msg}", file=sys.stderr, flush=True)


def info(msg: str) -> None:
    print(f"[llm_rerank] {msg}", flush=True)


def llm_rerank_enabled() -> bool:
    return os.environ.get("LLM_RERANK", "").strip() in {"1", "true", "TRUE", "yes", "YES"}


def normalize_base_url(url: str) -> str:
    """Normalize OpenAI-compatible base URL to .../v1 (no trailing slash).

    Accepts either site root (https://api.tu-zi.com) or versioned
    (https://api.tu-zi.com/v1). Avoids /v1/v1 duplication.
    """
    u = (url or "").strip().rstrip("/")
    if not u:
        return DEFAULT_BASE_URL.rstrip("/")
    # Already versioned
    if u.endswith("/v1") or "/v1/" in u + "/":
        # collapse accidental trailing /v1/v1
        while u.endswith("/v1/v1"):
            u = u[: -len("/v1")]
        if not u.endswith("/v1"):
            # e.g. https://host/v1/foo — keep as given up to /v1
            idx = u.find("/v1")
            u = u[: idx + 3]
        return u
    return u + "/v1"


def resolve_api_config(model_override: str | None = None) -> dict[str, Any]:
    """Resolve OpenAI-compatible API settings from env (no secrets logged).

    model_override: pick a specific model (dual-model picks); json_mode default
    then follows that model (astra off, others e.g. claude on).
    """
    key = (
        os.environ.get("LLM_API_KEY")
        or os.environ.get("OPENAI_API_KEY")
        or os.environ.get("OPENAI_KEY")
        or ""
    ).strip()
    base = normalize_base_url(
        os.environ.get("LLM_BASE_URL")
        or os.environ.get("OPENAI_BASE_URL")
        or DEFAULT_BASE_URL
    )
    model = (
        model_override
        or os.environ.get("LLM_MODEL")
        or os.environ.get("OPENAI_MODEL")
        or DEFAULT_MODEL
    ).strip()
    try:
        timeout = float(os.environ.get("LLM_TIMEOUT_S") or DEFAULT_TIMEOUT_S)
    except ValueError:
        timeout = float(DEFAULT_TIMEOUT_S)
    # Ops: 15:05 read timeouts at 150s with ~285 cands; floor 60, prefer ≥300 via env/default
    timeout = max(timeout, 60.0)
    try:
        temperature = float(os.environ.get("LLM_TEMPERATURE") or DEFAULT_TEMPERATURE)
    except ValueError:
        temperature = DEFAULT_TEMPERATURE
    temperature = min(max(temperature, 0.0), 0.3)
    # gpt-6-astra via tu-zi hangs on response_format=json_object (read timeout);
    # default OFF for astra, ON otherwise. Explicit LLM_JSON_MODE overrides.
    json_env = os.environ.get("LLM_JSON_MODE")
    if json_env is not None and json_env.strip() != "":
        json_mode = json_env.strip() not in {"0", "false", "FALSE", "no", "NO"}
    else:
        json_mode = not any(x in model.lower() for x in ("astra", "sol", "gpt-6.1"))
    return {
        "api_key": key,
        "base_url": base,
        "model": model,
        "timeout": timeout,
        "temperature": temperature,
        "json_mode": json_mode,
    }


def strategy_ui_name(class_name: str) -> str:
    meta = STRATEGY_META.get(class_name)
    return meta[0] if meta else class_name


def strategy_blurb(class_name: str) -> str:
    meta = STRATEGY_META.get(class_name)
    return meta[1] if meta else "规则策略命中"


def is_st_or_delisted(name: str | None) -> bool:
    """Drop ST / *ST / S*ST / 退市 names (light clean only)."""
    if not name:
        return False
    raw = str(name).strip().replace(" ", "")
    if "退市" in raw:
        return True
    if "ＳＴ" in raw or "＊ＳＴ" in raw:
        return True
    # A-share risk markers at name start: ST / *ST / S*ST (ASCII or fullwidth star)
    if re.match(r"^(?:\*|＊)?ST", raw, flags=re.IGNORECASE):
        return True
    if re.match(r"^S(?:\*|＊)ST", raw, flags=re.IGNORECASE):
        return True
    return False


def _short_date(d: Any) -> str:
    s = str(d or "").strip()
    if len(s) >= 10 and s[4] == "-" and s[7] == "-":
        return s[5:7] + s[8:10]  # MMDD
    return s[-4:] if len(s) >= 4 else s


def _round_px(v: Any) -> float | int | None:
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    # keep ints as ints; else 2dp
    if abs(f - round(f)) < 1e-9:
        return int(round(f))
    return round(f, 2)


def week_oc_from_ohlcv(ohlcv: list[dict[str, Any]] | None, n: int = WEEK_OC_BARS) -> list[dict[str, Any]]:
    """Last n bars as compact {d,o,c} (short date) for prompt size."""
    if not ohlcv:
        return []
    tip = ohlcv[-n:]
    out: list[dict[str, Any]] = []
    for bar in tip:
        out.append(
            {
                "d": _short_date(bar.get("date")),
                "o": _round_px(bar.get("open")),
                "c": _round_px(bar.get("close")),
            }
        )
    return out


def build_why(hit_strategies: list[str]) -> str:
    """Short hit tag for candidate rows (blurbs live in strategy_summaries)."""
    parts: list[str] = []
    for cls in hit_strategies:
        ui = strategy_ui_name(cls)
        if ui and ui not in parts:
            parts.append(ui)
    return "+".join(parts) if parts else "规则并集候选"


def union_codes_from_latest(latest: dict[str, Any]) -> list[str]:
    """Full rule-scan union in strategies display order (first appearance)."""
    seen: list[str] = []
    for strategy in latest.get("strategies") or []:
        for code in strategy.get("symbols") or []:
            c = str(code).zfill(6)
            if c not in seen:
                seen.append(c)
    return seen


def hits_by_code(latest: dict[str, Any]) -> dict[str, list[str]]:
    mapping: dict[str, list[str]] = {}
    for strategy in latest.get("strategies") or []:
        name = str(strategy.get("name") or "")
        for code in strategy.get("symbols") or []:
            c = str(code).zfill(6)
            mapping.setdefault(c, [])
            if name and name not in mapping[c]:
                mapping[c].append(name)
    return mapping


def build_strategy_summaries(
    latest: dict[str, Any],
    *,
    sample_n: int = SAMPLE_CODES_PER_STRATEGY,
) -> list[dict[str, Any]]:
    """Server-side strategy summary blocks for prompt_ver=v1.2 (not model-invented)."""
    out: list[dict[str, Any]] = []
    for strategy in latest.get("strategies") or []:
        cls = str(strategy.get("name") or "")
        if not cls:
            continue
        codes_raw = strategy.get("symbols") or []
        codes: list[str] = []
        for code in codes_raw:
            c = str(code).zfill(6)
            if c not in codes:
                codes.append(c)
        ui = strategy_ui_name(cls)
        blurb = strategy_blurb(cls)
        if len(blurb) > 40:
            blurb = blurb[:40]
        out.append(
            {
                "strategy_id": cls,
                "strategy": ui,
                "n_hits": len(codes),
                "sample_codes": codes[: max(0, int(sample_n))],
                "rule_blurb": blurb,
            }
        )
    return out


def rule_order_top5(latest: dict[str, Any]) -> list[dict[str, str]]:
    names = latest.get("names") or {}
    codes = union_codes_from_latest(latest)[:5]
    out: list[dict[str, str]] = []
    for code in codes:
        name = names.get(code)
        if not isinstance(name, str) or not name.strip():
            name = code
        out.append({"code": code, "name": name.strip()})
    return out


def multi_hit_top5(latest: dict[str, Any]) -> list[dict[str, str]]:
    """Prefer hit_count>=2 in strategies display-order union; fill with singles.

    序5 (2026-10-02): SHADOW ONLY by default. write_daily_picks PICK_MODE=shadow
    writes data/daily_picks/_shadow/*.multi_hit.json with track=multi_hit_shadow.
    Cutting MAIN to multi_hit requires ALLOW_MULTI_HIT_MAIN=1 (default OFF).
    Do NOT change PROMPT_VER / prompt text here for this order.

    - Union order = strategy list order in latest.json (MaVolume→…→BowlRebound).
    - Drop ST / delisted names via is_st_or_delisted.
    - Prefer codes with >=2 strategy hits (stable relative order), then singles.
    - Return at most 5 {code,name} dicts. Caller sets source=multi_hit.
    """
    names = latest.get("names") or {}
    hits = hits_by_code(latest)
    union = union_codes_from_latest(latest)

    cleaned: list[str] = []
    for code in union:
        name = names.get(code)
        if not isinstance(name, str) or not name.strip():
            name = code
        if is_st_or_delisted(name):
            continue
        cleaned.append(code)

    multi = [c for c in cleaned if len(hits.get(c) or []) >= 2]
    singles = [c for c in cleaned if c not in multi]
    picked = (multi + singles)[:5]

    out: list[dict[str, str]] = []
    for code in picked:
        name = names.get(code)
        if not isinstance(name, str) or not name.strip():
            name = code
        out.append({"code": code, "name": name.strip()})
    return out


def build_candidates(
    latest: dict[str, Any],
    details_dir: Path,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Build v1.1 feature rows. Returns (candidates, stats)."""
    names = latest.get("names") or {}
    quotes = latest.get("quotes") or {}
    meta = latest.get("meta") or {}
    hits = hits_by_code(latest)
    union = union_codes_from_latest(latest)

    dropped_st: list[str] = []
    candidates: list[dict[str, Any]] = []

    for code in union:
        name = names.get(code) or ""
        if not name:
            # try details / meta map name
            det_path = details_dir / f"{code}.json"
            if det_path.is_file():
                try:
                    det0 = json.loads(det_path.read_text(encoding="utf-8"))
                    name = det0.get("name") or ""
                except (OSError, json.JSONDecodeError):
                    pass
        if is_st_or_delisted(str(name) if name else None):
            dropped_st.append(code)
            continue

        hit_list = hits.get(code) or []
        m = meta.get(code) or {}
        industry_group = m.get("industry_group") or "未分类"
        board = m.get("board")
        q = quotes.get(code) or {}
        chg_pct = q.get("chg_pct")

        week_oc: list[dict[str, Any]] = []
        det_name = name
        det_path = details_dir / f"{code}.json"
        if det_path.is_file():
            try:
                det = json.loads(det_path.read_text(encoding="utf-8"))
                week_oc = week_oc_from_ohlcv(det.get("ohlcv_60d"))
                if not det_name:
                    det_name = det.get("name") or code
                if not board:
                    board = det.get("board")
                # preferred: industry_group already from latest.meta; details may lack it
            except (OSError, json.JSONDecodeError) as exc:
                warn(f"detail read failed {code}: {exc}")

        row: dict[str, Any] = {
            "code": code,
            "why": build_why(hit_list) if hit_list else "规则并集候选",
            "industry_group": industry_group,
            "week_oc": week_oc,
            "name": (det_name or code),
            "strategies": [strategy_ui_name(s) for s in hit_list],
            "n_hit": len(hit_list),
        }
        if board:
            row["board"] = board
        if isinstance(chg_pct, (int, float)):
            row["chg_pct"] = round(float(chg_pct), 4)

        candidates.append(row)

    stats = {
        "union_count": len(union),
        "candidate_count": len(candidates),
        "dropped_st_count": len(dropped_st),
        "dropped_st": dropped_st,
        "feature_ver": FEATURE_VER,
    }
    return candidates, stats


def compact_strategy_summaries(summaries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Denser strategy blocks for the wire prompt (keep UI name + n_hits + tiny sample)."""
    out: list[dict[str, Any]] = []
    for s in summaries:
        out.append(
            {
                "strategy": s.get("strategy"),
                "n": int(s.get("n_hits") or 0),
                "s": list(s.get("sample_codes") or [])[:SAMPLE_CODES_PER_STRATEGY],
                "b": s.get("rule_blurb") or "",
            }
        )
    return out


def compact_candidates_for_prompt(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Shorter candidate rows for gpt-6-astra: trim why/week_oc and drop redundant keys."""
    out: list[dict[str, Any]] = []
    for c in candidates:
        why = str(c.get("why") or "")
        if len(why) > 24:
            why = why[:24]
        woc = c.get("week_oc") or []
        # already compact {d,o,c}; keep as list of [d,o,c] arrays (fewer keys)
        woc_arr: list[list[Any]] = []
        for bar in woc:
            if isinstance(bar, dict):
                woc_arr.append([bar.get("d") or bar.get("date"), bar.get("o", bar.get("open")), bar.get("c", bar.get("close"))])
            elif isinstance(bar, (list, tuple)) and len(bar) >= 3:
                woc_arr.append([bar[0], bar[1], bar[2]])
        row: dict[str, Any] = {
            "code": c.get("code"),
            "why": why,
            "ig": c.get("industry_group") or "未分类",
            "woc": woc_arr,
            "nh": int(c.get("n_hit") or 0),
        }
        chg = c.get("chg_pct")
        if isinstance(chg, (int, float)):
            row["chg"] = round(float(chg), 2)
        out.append(row)
    return out


def build_messages(
    candidates: list[dict[str, Any]],
    strategy_summaries: list[dict[str, Any]] | None = None,
) -> list[dict[str, str]]:
    """Prompt v1.2: System forces strategy_review THEN top5; pass strategy summaries."""
    system = (
        "扮演股票技术分析师。这些股票是根据A股收盘数据，进行相关指标过滤筛选出来的股票代码，我将给出相关股票过去一段时间的开盘价，收盘价，成交量等信息，请你再帮我精选出5只股票，这5只股票我会第二天买入，第三天卖出。追求高收益。"
        "你是 A 股观察助手。先根据策略摘要与候选特征做 strategy_review，"
        "再只从候选中选出 Top5。禁止编造代码或新闻。"
        "输出仅 JSON，字段为 strategy_review、top5、rejected_note。"
        "推理顺序必须：1) 逐策略复盘命中质量（人数是否虚胖、近周开收是否过热/结构散、"
        "多命中是否更可信），给每策略一句结论 + score 1–5；"
        "2) 再从全量候选排 Top5（须 ⊆ 候选）；"
        "3) Top5 应体现复盘结论（压低虚胖策略堆、抬多命中/形态更干净者）；"
        "持有假设：信号日收盘选出→次日开盘买→再下一交易日开盘卖；"
        "软约束：Top5 尽量同 industry_group(ig) ≤2 只；勿声称未提供新闻/内幕。"
        "候选字段：code/why/ig/woc(近周[d,o,c])/nh/chg；策略摘要：strategy/n/s/b。"
        "人话推荐理由硬约束：1)只用输入字段事实，缺的不补；2)每只须给 reason≤40字（chip摘要）与 explain 80–150字正文，二者同向；3)explain须点策略中文名+近周开收形态词（抬升/收回/横盘/下探等）；4)结尾须含「不构成买卖建议」或「短观察窗」之一；5)禁止新闻/舆情/内幕/庄家/政策落地/目标价/建议买入卖出/必涨/抄底；持有语境：收盘选出→次日开买→再下一日开卖，短观察窗非中线故事。"
    )
    summaries = strategy_summaries or []
    dense_sums = compact_strategy_summaries(summaries)
    dense_cands = compact_candidates_for_prompt(candidates)
    user_obj = {
        "task": "strategy_review_then_top5",
        "feature_ver": FEATURE_VER,
        "prompt_ver": PROMPT_VER,
        "candidate_count": len(dense_cands),
        "strategy_summaries": dense_sums,
        "output_schema": {
            "strategy_review": [
                {"strategy": "海龟突破", "score": 3, "note": "≤40字：人数/过热/可信度"}
            ],
            "top5": [{"rank": 1, "code": "000000", "reason": "≤40字：策略名+形态", "explain": "80–150字人话正文"}],
            "rejected_note": "可选一句",
        },
        "candidates": dense_cands,
    }
    user = (
        "先对 strategy_summaries 中 n>0 的策略做 strategy_review（score 1–5 整数，note≤40字；strategy 用中文名），"
        "再从 candidates 全量重排恰好 5 只；code 必须属于 candidates。"
        "人话推荐理由硬约束：1)只用输入字段事实，缺的不补；2)每只须给 reason≤40字（chip摘要）与 explain 80–150字正文，二者同向；3)explain须点策略中文名+近周开收形态词（抬升/收回/横盘/下探等）；4)结尾须含「不构成买卖建议」或「短观察窗」之一；5)禁止新闻/舆情/内幕/庄家/政策落地/目标价/建议买入卖出/必涨/抄底；持有语境：收盘选出→次日开买→再下一日开卖，短观察窗非中线故事。"
        "\n"
        + json.dumps(user_obj, ensure_ascii=False, separators=(",", ":"))
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def build_strategy_review_messages(
    candidates: list[dict[str, Any]],
    strategy_summaries: list[dict[str, Any]],
) -> list[dict[str, str]]:
    """Phase-1 prompt: strategy_review only (tiny sample rows for heat context)."""
    dense_sums = compact_strategy_summaries(strategy_summaries)
    by_code = {c["code"]: c for c in compact_candidates_for_prompt(candidates)}
    samples: list[dict[str, Any]] = []
    seen: set[str] = set()
    for s in strategy_summaries:
        for code in list(s.get("sample_codes") or [])[:SAMPLE_CODES_PER_STRATEGY]:
            c = str(code).zfill(6)
            if c in seen or c not in by_code:
                continue
            seen.add(c)
            samples.append(by_code[c])
    system = (
        "扮演股票技术分析师。这些股票是根据A股收盘数据，进行相关指标过滤筛选出来的股票代码，我将给出相关股票过去一段时间的开盘价，收盘价，成交量等信息，请你再帮我精选出5只股票，这5只股票我会第二天买入，第三天卖出。追求高收益。"
        "你是 A 股观察助手。只做 strategy_review，不要输出 top5。"
        "根据策略摘要与少量样本近周开收，判断人数是否虚胖、是否过热/结构散、多命中是否更可信。"
        "输出仅 JSON：{\"strategy_review\":[{\"strategy\":\"中文名\",\"score\":1-5,\"note\":\"≤40字\"}]}。"
        "须覆盖所有 n>0 的策略；禁止编造新闻/内幕。"
    )
    user_obj = {
        "task": "strategy_review_only",
        "feature_ver": FEATURE_VER,
        "prompt_ver": PROMPT_VER,
        "strategy_summaries": dense_sums,
        "sample_candidates": samples,
        "candidate_count_total": len(candidates),
    }
    user = (
        "对 strategy_summaries 中 n>0 的策略逐条复盘（score 1–5，note≤40字；strategy 用中文名）。"
        "sample_candidates 仅供感受近周开收，不要据此选股。\n"
        + json.dumps(user_obj, ensure_ascii=False, separators=(",", ":"))
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def build_top5_messages(
    candidates: list[dict[str, Any]],
    strategy_summaries: list[dict[str, Any]],
    strategy_review: list[dict[str, Any]],
) -> list[dict[str, str]]:
    """Phase-2 prompt: top5 only, conditioned on prior strategy_review."""
    dense_sums = compact_strategy_summaries(strategy_summaries)
    dense_cands = compact_candidates_for_prompt(candidates)
    system = (
        "扮演股票技术分析师。这些股票是根据A股收盘数据，进行相关指标过滤筛选出来的股票代码，我将给出相关股票过去一段时间的开盘价，收盘价，成交量等信息，请你再帮我精选出5只股票，这5只股票我会第二天买入，第三天卖出。追求高收益。"
        "你是 A 股观察助手。已完成 strategy_review，现在只从候选中选出 Top5。"
        "禁止编造代码或新闻。输出仅 JSON，字段为 top5、rejected_note。"
        "Top5 须 ⊆ 候选，恰好 5 只，并体现复盘结论（压低虚胖策略堆、抬多命中/形态更干净者）；"
        "持有假设：信号日收盘选出→次日开盘买→再下一交易日开盘卖；"
        "软约束：同 industry_group(ig) ≤2 只。"
        "候选字段：code/why/ig/woc(近周[d,o,c])/nh/chg。"
        "人话推荐理由硬约束：1)只用输入字段事实，缺的不补；2)每只须给 reason≤40字（chip摘要）与 explain 80–150字正文，二者同向；3)explain须点策略中文名+近周开收形态词（抬升/收回/横盘/下探等）；4)结尾须含「不构成买卖建议」或「短观察窗」之一；5)禁止新闻/舆情/内幕/庄家/政策落地/目标价/建议买入卖出/必涨/抄底；持有语境：收盘选出→次日开买→再下一日开卖，短观察窗非中线故事。"
    )
    user_obj = {
        "task": "top5_from_strategy_review",
        "feature_ver": FEATURE_VER,
        "prompt_ver": PROMPT_VER,
        "candidate_count": len(dense_cands),
        "strategy_summaries": dense_sums,
        "strategy_review": strategy_review,
        "output_schema": {
            "top5": [{"rank": 1, "code": "000000", "reason": "≤40字：策略名+形态", "explain": "80–150字人话正文"}],
            "rejected_note": "可选一句",
        },
        "candidates": dense_cands,
    }
    user = (
        "已有 strategy_review。从 candidates 全量重排恰好 5 只；code 必须属于 candidates。"
        "人话推荐理由硬约束：1)只用输入字段事实，缺的不补；2)每只须给 reason≤40字（chip摘要）与 explain 80–150字正文，二者同向；3)explain须点策略中文名+近周开收形态词（抬升/收回/横盘/下探等）；4)结尾须含「不构成买卖建议」或「短观察窗」之一；5)禁止新闻/舆情/内幕/庄家/政策落地/目标价/建议买入卖出/必涨/抄底；持有语境：收盘选出→次日开买→再下一日开卖，短观察窗非中线故事。"
        "\n"
        + json.dumps(user_obj, ensure_ascii=False, separators=(",", ":"))
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _extract_json_object(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        raise ValueError("no JSON object in model response")
    obj = json.loads(m.group(0))
    if not isinstance(obj, dict):
        raise ValueError("JSON root is not object")
    return obj


def validate_strategy_review(
    payload: dict[str, Any],
    strategy_summaries: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Require strategy_review covering hit strategies (n_hits>0). Incomplete → raise (full fallback)."""
    reviews = payload.get("strategy_review")
    if not isinstance(reviews, list) or not reviews:
        raise ValueError("missing or empty strategy_review (prompt_ver=v1.2 requires it before top5)")
    required_ui = {
        str(s.get("strategy") or "")
        for s in strategy_summaries
        if int(s.get("n_hits") or 0) > 0 and s.get("strategy")
    }
    out: list[dict[str, Any]] = []
    seen_ui: set[str] = set()
    for i, item in enumerate(reviews):
        if not isinstance(item, dict):
            raise ValueError(f"strategy_review[{i}] not object")
        name = str(item.get("strategy") or "").strip()
        if not name:
            raise ValueError(f"strategy_review[{i}] missing strategy")
        score_raw = item.get("score")
        try:
            score = int(score_raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"strategy_review[{i}] score not int") from exc
        if score < 1 or score > 5:
            raise ValueError(f"strategy_review[{i}] score out of 1–5: {score}")
        note = str(item.get("note") or "").strip()
        if len(note) > 40:
            note = note[:40]
        out.append({"strategy": name, "score": score, "note": note})
        seen_ui.add(name)
    # Soft coverage check: at least cover required hit strategies by UI name.
    # Allow extra zero-hit reviews; missing required → fail whole payload (no partial top5).
    missing = sorted(required_ui - seen_ui)
    if missing:
        raise ValueError(f"strategy_review missing hit strategies: {','.join(missing)}")
    return out


def validate_top5(payload: dict[str, Any], allowed: set[str]) -> list[dict[str, str]]:
    top5 = payload.get("top5")
    if not isinstance(top5, list) or len(top5) != 5:
        raise ValueError(f"top5 must be length 5, got {type(top5).__name__} len={getattr(top5, '__len__', lambda: '?')()}")
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for i, item in enumerate(top5):
        if not isinstance(item, dict):
            raise ValueError(f"top5[{i}] not object")
        code = str(item.get("code") or "").zfill(6)
        if code not in allowed:
            raise ValueError(f"unknown/out-of-pool code: {code}")
        if code in seen:
            raise ValueError(f"duplicate code: {code}")
        seen.add(code)
        reason = str(item.get("reason") or "").strip()
        if len(reason) > REASON_MAX:
            reason = reason[:REASON_MAX]
        explain = str(item.get("explain") or "").strip()
        if not explain:
            raise ValueError(f"top5[{i}] missing explain (prompt_ver={PROMPT_VER})")
        if len(explain) > EXPLAIN_MAX:
            explain = explain[:EXPLAIN_MAX]
        if len(explain) < EXPLAIN_MIN:
            warn(f"top5[{i}] explain short ({len(explain)}<{EXPLAIN_MIN}): {code}")
        rank = item.get("rank", i + 1)
        try:
            rank_i = int(rank)
        except (TypeError, ValueError):
            rank_i = i + 1
        out.append({"rank": str(rank_i), "code": code, "reason": reason, "explain": explain})
    # normalize ranks 1..5 by order
    normalized: list[dict[str, str]] = []
    for i, row in enumerate(out):
        normalized.append(
            {
                "rank": str(i + 1),
                "code": row["code"],
                "reason": row["reason"],
                "explain": row["explain"],
            }
        )
    return normalized


def _timeout_retries() -> int:
    """Extra attempts after a timed-out LLM call (default 2 → up to 3 tries)."""
    raw = (os.environ.get("LLM_TIMEOUT_RETRIES") or str(DEFAULT_TIMEOUT_RETRIES)).strip()
    try:
        n = int(raw)
    except ValueError:
        n = DEFAULT_TIMEOUT_RETRIES
    return max(0, min(n, 2))


def _is_timeout_exc(exc: BaseException) -> bool:
    if isinstance(exc, (TimeoutError, socket.timeout)):
        return True
    reason = getattr(exc, "reason", None)
    if isinstance(reason, (TimeoutError, socket.timeout)):
        return True
    msg = str(exc).lower()
    return "timed out" in msg or "timeout" in msg


def token_limit_param(model: str) -> str:
    """Name of the output-token cap for this model.

    tu-zi gpt-6-astra (and OpenAI reasoning-style gpt-5+/o-series) reject
    `max_tokens` with HTTP 400 unsupported_parameter since 2026-09-28 and need
    `max_completion_tokens`. Other models (e.g. deepseek) keep `max_tokens`.
    LLM_TOKEN_PARAM=max_tokens|max_completion_tokens overrides.
    """
    env = (os.environ.get("LLM_TOKEN_PARAM") or "").strip()
    if env in {"max_tokens", "max_completion_tokens"}:
        return env
    m = (model or "").lower()
    if "astra" in m or "sol" in m or re.match(r"^(gpt-[5-9]|o[1-9])", m):
        return "max_completion_tokens"
    return "max_tokens"


def sends_temperature(model: str) -> bool:
    """Whether to send `temperature` for this model.

    tu-zi gpt-6-astra (2026-09-28) answers any temperature != 1 with a
    misleading HTTP 400 service_error (服务暂时不可用); omitting it works.
    Same model rule as token_limit_param. LLM_SEND_TEMPERATURE=1|0 overrides.
    """
    env = (os.environ.get("LLM_SEND_TEMPERATURE") or "").strip()
    if env in {"1", "0"}:
        return env == "1"
    if re.match(r"^claude-(opus|sonnet|fable)-5", (model or "").lower()):
        return False  # tu-zi 400: "`temperature` is deprecated for this model"
    return token_limit_param(model) == "max_tokens"


def phase_token_caps(model: str) -> tuple[int, int]:
    """(phase1, phase2) output caps. claude-* truncates to empty at 800/1600
    (finish_reason=length, probe 2026-09-28); 2000/4000 works."""
    if (model or "").lower().startswith("claude-"):
        return 2000, 4000
    return 800, 1600


def call_chat_completions(
    messages: list[dict[str, str]],
    *,
    api_key: str,
    base_url: str,
    model: str,
    temperature: float,
    timeout: float,
    json_mode: bool = True,
    max_tokens: int | None = None,
) -> tuple[str, object]:
    url = f"{base_url.rstrip('/')}/chat/completions"
    body: dict[str, Any] = {
        "model": model,
        "messages": messages,
    }
    if sends_temperature(model):
        body["temperature"] = temperature
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    if max_tokens is not None and int(max_tokens) > 0:
        body[token_limit_param(model)] = int(max_tokens)
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    max_attempts = 1 + _timeout_retries()
    raw = ""
    for attempt in range(1, max_attempts + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8")
            break
        except urllib.error.HTTPError as exc:
            err_body = ""
            try:
                err_body = exc.read().decode("utf-8", errors="replace")[:500]
            except Exception:
                pass
            raise RuntimeError(f"HTTP {exc.code}: {err_body}") from exc
        except Exception as exc:
            if _is_timeout_exc(exc) and attempt < max_attempts:
                warn(
                    f"LLM read/request timeout attempt {attempt}/{max_attempts}: {exc}; "
                    f"retrying in {min(2.0 * attempt, 5.0):.0f}s"
                )
                time.sleep(min(2.0 * attempt, 5.0))
                continue
            raise RuntimeError(f"request failed: {exc}") from exc
    else:
        raise RuntimeError("request failed: exhausted timeout retries")

    parsed = json.loads(raw)
    choices = parsed.get("choices") or []
    if not choices:
        raise RuntimeError("empty choices in API response")
    choice0 = choices[0] if isinstance(choices[0], dict) else {}
    finish_reason = choice0.get("finish_reason")
    msg = choice0.get("message") if isinstance(choice0.get("message"), dict) else {}
    content = msg.get("content")
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError(f"empty message content (finish_reason={finish_reason!r})")
    return content, finish_reason


def format_pick_error(err: object, api_key: str = "") -> str:
    """Short, key-free failure reason for pause_reason.

    'HTTP 400: {"error":{"code":"unsupported_parameter","message":"..."}}'
      -> 'HTTP 400 unsupported_parameter: ...'
    """
    text = str(err or "").strip() or "unknown error"
    m = re.match(r"^HTTP (\d{3}):\s*(.*)$", text, re.S)
    if m:
        status, body = m.group(1), m.group(2).strip()
        code, message = "", body
        try:
            obj = json.loads(body)
            e = obj.get("error") if isinstance(obj, dict) else None
            if isinstance(e, dict):
                code = str(e.get("code") or e.get("type") or "").strip()
                message = str(e.get("message") or "").strip() or body
            elif isinstance(obj, dict) and obj.get("message"):
                message = str(obj.get("message"))
        except (ValueError, TypeError):
            # Body may be truncated (500 chars) -> pull fields by regex.
            mc = re.search(r'"code"\s*:\s*"([^"]*)"', body)
            mm = re.search(r'"message"\s*:\s*"((?:[^"\\]|\\.)*)', body)
            if mc:
                code = mc.group(1).strip()
            if mm:
                message = mm.group(1).strip()
        text = f"HTTP {status} {code}: {message}" if code else f"HTTP {status}: {message}"
    if api_key:
        text = text.replace(api_key, "***")
    text = re.sub(r"sk-[A-Za-z0-9_\-]{6,}", "sk-***", text)
    text = re.sub(r"(?i)(bearer\s+)[A-Za-z0-9._\-]+", r"\1***", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:300]



def _dump_llm_failure(
    phase: str,
    content: str | None,
    finish_reason: object,
    exc: BaseException,
    *,
    limit: int = 1200,
) -> None:
    """Log a short, key-free snippet of the assistant content on parse/validate failure."""
    text = content if isinstance(content, str) else ""
    snippet = text[:limit]
    snippet = re.sub(r"sk-[A-Za-z0-9_\-]{6,}", "sk-***", snippet)
    snippet = re.sub(r"(?i)(bearer\s+)[A-Za-z0-9._\-]+", r"\1***", snippet)
    warn(
        f"{phase} failure dump finish_reason={finish_reason!r} "
        f"err={format_pick_error(exc)} content_len={len(text)} "
        f"content[:{limit}]={snippet!r}"
    )


def rerank_top5(
    latest: dict[str, Any],
    details_dir: Path,
    model: str | None = None,
) -> dict[str, Any]:
    """Attempt LLM rerank (prompt_ver=v1.2). Returns result dict with ok flag.

    On success:
      ok=True, symbols=[{code,name,reason,explain}], source=llm_rerank, model,
      feature_ver, prompt_ver, strategy_review, candidate_count, rejected_note?
    On failure (incl. incomplete JSON / missing strategy_review):
      ok=False, error=<key-free reason>, source=paused, retryable=bool
      Caller retries retryable failures, then pauses the day (序3 Option B /
      0.12.4): NEVER silently write source=rule_order as a successful Top5.
      multi_hit remains shadow-only (ALLOW_MULTI_HIT_MAIN=0).
      Test hook: LLM_FORCE_FAIL=1|true|all|<model-substr> raises forced_failure.
    """
    cfg = resolve_api_config(model)
    if not cfg["api_key"]:
        return {
            "ok": False,
            "error": "API key missing (LLM_API_KEY/OPENAI_API_KEY not set)",
            "retryable": False,
            "source": "paused",
            "source_track": "paused",
            "fallback_policy": "pause_no_rule_order",
            "model": cfg["model"],
            "feature_ver": FEATURE_VER,
            "prompt_ver": PROMPT_VER,
        }

    candidates, stats = build_candidates(latest, details_dir)
    strategy_summaries = build_strategy_summaries(latest)
    info(
        f"features ready feature_ver={FEATURE_VER} prompt_ver={PROMPT_VER} "
        f"model={cfg['model']} union={stats['union_count']} "
        f"candidates={stats['candidate_count']} dropped_st={stats['dropped_st_count']} "
        f"strategies={len(strategy_summaries)} timeout_s={cfg['timeout']}"
    )
    if len(candidates) < 5:
        return {
            "ok": False,
            "error": f"no candidates: fewer than 5 after ST drop ({len(candidates)})",
            "retryable": False,
            "source": "paused",
            "source_track": "paused",
            "fallback_policy": "pause_no_rule_order",
            "model": cfg["model"],
            "feature_ver": FEATURE_VER,
            "prompt_ver": PROMPT_VER,
            "candidate_count": stats["candidate_count"],
            "stats": stats,
        }

    # Two-phase by default (single-shot timed out at 300s with ~285 cands).
    # LLM_RERANK_PHASES=1 forces legacy single-shot; =2 (default) strategy_review then top5.
    phases_raw = (os.environ.get("LLM_RERANK_PHASES") or "2").strip()
    use_two_phase = phases_raw not in {"1", "single", "oneshot"}
    budget = float(cfg["timeout"])
    try:
        import time as _time

        t_budget0 = _time.perf_counter()
        p1_tokens, p2_tokens = phase_token_caps(cfg["model"])
        _ff = (os.environ.get("LLM_FORCE_FAIL") or "").strip().lower()
        if _ff not in {"", "0"} and (
            _ff in {"1", "true", "all"}
            or any(t.strip() and t.strip() in cfg["model"].lower() for t in _ff.split(","))
        ):
            # Test hook: simulate an API failure without calling the API.
            raise RuntimeError(
                'HTTP 400: {"error":{"code":"forced_failure","message":"LLM_FORCE_FAIL test"}}'
            )
        if use_two_phase:
            # Allocate ~30% to review, rest to top5; never starve phase2 below 120s when budget≥300
            p1_cap = min(max(budget * 0.30, 60.0), 120.0)
            if budget >= 300:
                p1_cap = min(p1_cap, budget - 180.0)
            p1_cap = max(45.0, p1_cap)
            info(
                f"two-phase start budget_s={budget:.0f} phase1_cap_s={p1_cap:.0f} "
                f"candidates={len(candidates)}"
            )
            msg1 = build_strategy_review_messages(candidates, strategy_summaries)
            content1, fr1 = call_chat_completions(
                msg1,
                api_key=cfg["api_key"],
                base_url=cfg["base_url"],
                model=cfg["model"],
                temperature=cfg["temperature"],
                timeout=p1_cap,
                json_mode=bool(cfg.get("json_mode", True)),
                max_tokens=p1_tokens,
            )
            try:
                payload1 = _extract_json_object(content1)
                strategy_review = validate_strategy_review(payload1, strategy_summaries)
            except Exception as exc:
                _dump_llm_failure("phase1", content1, fr1, exc)
                raise
            used = _time.perf_counter() - t_budget0
            p2_cap = max(60.0, budget - used)
            info(
                f"phase1 ok reviews={len(strategy_review)} used_s={used:.1f} phase2_cap_s={p2_cap:.0f}"
            )
            msg2 = build_top5_messages(candidates, strategy_summaries, strategy_review)
            content2, fr2 = call_chat_completions(
                msg2,
                api_key=cfg["api_key"],
                base_url=cfg["base_url"],
                model=cfg["model"],
                temperature=cfg["temperature"],
                timeout=p2_cap,
                json_mode=bool(cfg.get("json_mode", True)),
                max_tokens=p2_tokens,
            )
            try:
                payload = _extract_json_object(content2)
                allowed = {c["code"] for c in candidates}
                top5 = validate_top5(payload, allowed)
            except Exception as exc:
                _dump_llm_failure("phase2", content2, fr2, exc)
                raise
            info(f"phase2 ok top5={[r['code'] for r in top5]} total_s={_time.perf_counter()-t_budget0:.1f}")
        else:
            messages = build_messages(candidates, strategy_summaries)
            content, fr = call_chat_completions(
                messages,
                api_key=cfg["api_key"],
                base_url=cfg["base_url"],
                model=cfg["model"],
                temperature=cfg["temperature"],
                timeout=budget,
                json_mode=bool(cfg.get("json_mode", True)),
            )
            try:
                payload = _extract_json_object(content)
                strategy_review = validate_strategy_review(payload, strategy_summaries)
                allowed = {c["code"] for c in candidates}
                top5 = validate_top5(payload, allowed)
            except Exception as exc:
                _dump_llm_failure("oneshot", content, fr, exc)
                raise
    except Exception as exc:
        reason = format_pick_error(exc, cfg["api_key"])
        warn(f"LLM rerank attempt failed: {reason}")
        return {
            "ok": False,
            "error": reason,
            "retryable": True,
            "source": "paused",
            "source_track": "paused",
            "fallback_policy": "pause_no_rule_order",
            "model": cfg["model"],
            "feature_ver": FEATURE_VER,
            "prompt_ver": PROMPT_VER,
            "candidate_count": stats["candidate_count"],
            "stats": stats,
        }

    names = latest.get("names") or {}
    # enrich names from candidates
    name_by_code = {c["code"]: c.get("name") or names.get(c["code"]) or c["code"] for c in candidates}
    symbols: list[dict[str, str]] = []
    for row in top5:
        code = row["code"]
        entry = {
            "code": code,
            "name": str(name_by_code.get(code) or code),
            "reason": row["reason"],
        }
        if row.get("explain"):
            entry["explain"] = row["explain"]
        symbols.append(entry)

    result: dict[str, Any] = {
        "ok": True,
        "symbols": symbols,
        "source": "llm_rerank",
        "model": cfg["model"],
        "feature_ver": FEATURE_VER,
        "prompt_ver": PROMPT_VER,
        "strategy_review": strategy_review,
        "candidate_count": stats["candidate_count"],
        "stats": stats,
    }
    note = payload.get("rejected_note")
    if isinstance(note, str) and note.strip():
        result["rejected_note"] = note.strip()[:200]
    return result


if __name__ == "__main__":
    # Dry feature build only (no API call unless LLM_RERANK_DRY_CALL=1)
    root = Path(__file__).resolve().parents[1]
    latest_path = root / "data" / "latest.json"
    details_dir = root / "data" / "details"
    latest = json.loads(latest_path.read_text(encoding="utf-8"))
    cands, stats = build_candidates(latest, details_dir)
    print(json.dumps({"stats": stats, "sample": cands[:2]}, ensure_ascii=False, indent=2))
    print(f"rule_top5={[x['code'] for x in rule_order_top5(latest)]}")
