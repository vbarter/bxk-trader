#!/usr/bin/env python3
"""Rule-based loss review (下跌复盘) for settled watch-calendar stocks.

Only when per-stock ret < 0 (R+1 open buy → R+2 open sell, 不复权).
Writes review: {tags, factors, reasons, asof}.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Callable

# Writer Chinese labels
TAG_LABELS: dict[str, str] = {
    "gap_down_sell": "卖日出跳空",
    "open_fade": "买日高开回吐",
    "chase_signal": "信号日追高",
    "market_drag": "大盘拖累",
    "weak_vs_index": "弱于大盘",
    "industry_drag": "板块拖累",
    "volume_fade": "量能转弱",
    "strategy_limit": "策略局限",
    "other_weak": "走势偏弱",
}

SEVERITY: dict[str, int] = {
    "gap_down_sell": 100,
    "open_fade": 90,
    "chase_signal": 85,
    "market_drag": 80,
    "weak_vs_index": 75,
    "industry_drag": 70,
    "volume_fade": 60,
    "strategy_limit": 40,
    "other_weak": 10,
}

# Strategy name → detail code (English class + Chinese labels)
STRATEGY_DETAIL: dict[str, str] = {
    "TurtleTradeStrategy": "turtle_chase",
    "海龟突破": "turtle_chase",
    "MaVolumeStrategy": "ma_vol_pullback",
    "均线放量": "ma_vol_pullback",
    "HighTightFlagStrategy": "htf_fail",
    "高窄旗形": "htf_fail",
    "LimitUpShakeoutStrategy": "limit_wash_fail",
    "涨停洗盘": "limit_wash_fail",
    "UptrendLimitDownStrategy": "uptrend_ld",
    "上升趋势跌停": "uptrend_ld",
    "上升跌停反包": "uptrend_ld",
    "RpsBreakoutStrategy": "rps_meanrev",
    "RPS突破": "rps_meanrev",
    "RPS 相对强度突破": "rps_meanrev",
    "BowlReboundStrategy": "bowl_fail",
    "碗口反弹": "bowl_fail",
}

STRATEGY_REASON: dict[str, str] = {
    "turtle_chase": "突破类信号在弱市里易假突破后回撤。",
    "ma_vol_pullback": "放量上攻后，次段常见回踩。",
    "htf_fail": "旗形若突破失败，回吐往往较快。",
    "limit_wash_fail": "涨停洗盘后若未延续，买开容易被动。",
    "uptrend_ld": "该信号偏错杀观察，反弹延续性本来偏弱。",
    "rps_meanrev": "高位动量一旦中断，回撤往往偏大。",
    "bowl_fail": "碗口回踩后若未反弹，弱势可能延续。",
}

REASON_TEMPLATES: dict[str, str] = {
    "gap_down_sell": "卖出日相对买日收盘低开约 {gap}，开盘价已吃掉部分预期。",
    "open_fade": "买入日相对信号日收盘高开约 {open_gap}，随后走势回吐，持仓收益为负。",
    "chase_signal": "信号日涨约 {signal_chg}，偏追高入池，次段开买后更容易回撤。",
    "market_drag": "同期指数约 {idx}，个股约 {ret}，下跌与大盘拖累同向。",
    "weak_vs_index": "个股约 {ret}，指数约 {idx}，明显弱于大盘。",
    "industry_drag": "同行业样本同期约 {ind}，个股约 {ret}，板块偏弱拖累。",
    "volume_fade": "买入日成交量约为信号日的 {vol_ratio}，量能转弱。",
    "other_weak": "持仓区间收益约 {ret}，未命中更具体的规则因子。",
}


def fmt_pct(frac: float, digits: int = 1) -> str:
    """Format decimal fraction as signed percent string, e.g. -2.8%."""
    s = f"{frac * 100:+.{digits}f}%"
    return s.replace("+-", "-")


def fmt_vol_ratio(ratio: float) -> str:
    return f"{ratio * 100:.0f}%"


def is_chi_next(code: str) -> bool:
    return code.startswith(("300", "301", "688"))


def resolve_strategy_detail(strategies: list[str] | None) -> tuple[str | None, str | None]:
    if not strategies:
        return None, None
    for name in strategies:
        detail = STRATEGY_DETAIL.get(str(name).strip())
        if detail:
            return detail, str(name).strip()
    return None, None


def _safe_div(a: float | None, b: float | None) -> float | None:
    if a is None or b is None or b == 0:
        return None
    return a / b - 1.0


def evaluate_factors(
    *,
    code: str,
    ret: float,
    buy_open: float,
    sell_open: float,
    r_close: float | None,
    r_prev_close: float | None,
    r_volume: float | None,
    buy_close: float | None,
    buy_volume: float | None,
    idx_ret: float | None,
    industry_ret: float | None,
    industry_n: int | None,
    strategies: list[str] | None,
) -> list[dict[str, Any]]:
    """Return hit factors sorted by severity desc (may include strategy_limit)."""
    hits: list[dict[str, Any]] = []

    # gap_down_sell: sell_open / R+1_close - 1 <= -2%
    if buy_close is not None and buy_close != 0:
        gap = sell_open / buy_close - 1.0
        if gap <= -0.02:
            hits.append(
                {
                    "code": "gap_down_sell",
                    "gap": round(gap, 6),
                    "gap_fmt": fmt_pct(gap),
                }
            )

    # open_fade: buy_open / R_close - 1 >= +1.5% and ret < 0
    if r_close is not None and r_close != 0:
        open_gap = buy_open / r_close - 1.0
        if open_gap >= 0.015 and ret < 0:
            hits.append(
                {
                    "code": "open_fade",
                    "open_gap": round(open_gap, 6),
                    "open_gap_fmt": fmt_pct(open_gap),
                }
            )

    # chase_signal: R day chg >= +7% (chi-next/STAR >= +9%)
    signal_chg = _safe_div(r_close, r_prev_close)
    if signal_chg is not None:
        thr = 0.09 if is_chi_next(code) else 0.07
        if signal_chg >= thr:
            hits.append(
                {
                    "code": "chase_signal",
                    "signal_chg": round(signal_chg, 6),
                    "signal_chg_fmt": fmt_pct(signal_chg),
                }
            )

    # market_drag / weak_vs_index (skip if idx missing)
    if idx_ret is not None:
        if idx_ret <= -0.008 and ret <= idx_ret + 0.005:
            hits.append(
                {
                    "code": "market_drag",
                    "idx_ret": round(idx_ret, 6),
                    "stock_ret": round(ret, 6),
                    "idx_fmt": fmt_pct(idx_ret),
                    "ret_fmt": fmt_pct(ret),
                }
            )
        if ret - idx_ret <= -0.02:
            hits.append(
                {
                    "code": "weak_vs_index",
                    "idx_ret": round(idx_ret, 6),
                    "stock_ret": round(ret, 6),
                    "idx_fmt": fmt_pct(idx_ret),
                    "ret_fmt": fmt_pct(ret),
                }
            )

    # industry_drag: sample >= 5, ind_ret <= -1%, stock not above mean+0.5%
    if (
        industry_ret is not None
        and industry_n is not None
        and industry_n >= 5
        and industry_ret <= -0.01
        and ret <= industry_ret + 0.005
    ):
        hits.append(
            {
                "code": "industry_drag",
                "ind_ret": round(industry_ret, 6),
                "stock_ret": round(ret, 6),
                "n": industry_n,
                "ind_fmt": fmt_pct(industry_ret),
                "ret_fmt": fmt_pct(ret),
            }
        )

    # volume_fade
    if (
        r_volume is not None
        and buy_volume is not None
        and r_volume > 0
        and ret < 0
    ):
        vol_ratio = buy_volume / r_volume
        if vol_ratio <= 0.7:
            hits.append(
                {
                    "code": "volume_fade",
                    "vol_ratio": round(vol_ratio, 6),
                    "vol_ratio_fmt": fmt_vol_ratio(vol_ratio),
                }
            )

    # strategy_limit (at most one)
    detail, _src = resolve_strategy_detail(strategies)
    if detail is not None:
        hits.append({"code": "strategy_limit", "detail": detail})

    hits.sort(key=lambda f: SEVERITY.get(f["code"], 0), reverse=True)

    # other_weak only if nothing else (except we add after selection if empty)
    return hits


def select_tags(hits: list[dict[str, Any]], *, ret: float) -> list[dict[str, Any]]:
    """Pick up to 3 factors; strategy_limit may displace volume_fade/other_weak."""
    if ret >= 0:
        return []
    if not hits:
        return [{"code": "other_weak", "stock_ret": round(ret, 6), "ret_fmt": fmt_pct(ret)}]

    by_code = {f["code"]: f for f in hits}
    ranked = sorted(hits, key=lambda f: SEVERITY.get(f["code"], 0), reverse=True)
    chosen = ranked[:3]

    if "strategy_limit" in by_code and not any(f["code"] == "strategy_limit" for f in chosen):
        # Displace volume_fade or other_weak if present
        for soft in ("other_weak", "volume_fade"):
            idx = next((i for i, f in enumerate(chosen) if f["code"] == soft), None)
            if idx is not None:
                chosen[idx] = by_code["strategy_limit"]
                break
        chosen.sort(key=lambda f: SEVERITY.get(f["code"], 0), reverse=True)

    # Ensure at most one strategy_limit
    seen_sl = False
    deduped: list[dict[str, Any]] = []
    for f in chosen:
        if f["code"] == "strategy_limit":
            if seen_sl:
                continue
            seen_sl = True
        deduped.append(f)
    return deduped[:3]


def render_reason(factor: dict[str, Any], *, ret: float) -> str | None:
    code = factor["code"]
    slots: dict[str, str] = {"ret": fmt_pct(ret)}

    if code == "gap_down_sell":
        gap = factor.get("gap_fmt") or (
            fmt_pct(factor["gap"]) if factor.get("gap") is not None else None
        )
        if not gap:
            return None
        slots["gap"] = gap
    elif code == "open_fade":
        og = factor.get("open_gap_fmt") or (
            fmt_pct(factor["open_gap"]) if factor.get("open_gap") is not None else None
        )
        if not og:
            return None
        slots["open_gap"] = og
    elif code == "chase_signal":
        sc = factor.get("signal_chg_fmt") or (
            fmt_pct(factor["signal_chg"]) if factor.get("signal_chg") is not None else None
        )
        if not sc:
            return None
        slots["signal_chg"] = sc
    elif code in ("market_drag", "weak_vs_index"):
        idx = factor.get("idx_fmt")
        if not idx and factor.get("idx_ret") is not None:
            idx = fmt_pct(factor["idx_ret"])
        if not idx:
            return None
        slots["idx"] = idx
        slots["ret"] = factor.get("ret_fmt") or fmt_pct(ret)
    elif code == "industry_drag":
        ind = factor.get("ind_fmt")
        if not ind and factor.get("ind_ret") is not None:
            ind = fmt_pct(factor["ind_ret"])
        if not ind:
            return None
        slots["ind"] = ind
        slots["ret"] = factor.get("ret_fmt") or fmt_pct(ret)
    elif code == "volume_fade":
        vr = factor.get("vol_ratio_fmt")
        if not vr and factor.get("vol_ratio") is not None:
            vr = fmt_vol_ratio(factor["vol_ratio"])
        if not vr:
            return None
        slots["vol_ratio"] = vr
    elif code == "strategy_limit":
        detail = factor.get("detail")
        return STRATEGY_REASON.get(detail, "该类策略在弱延续时常见回撤。")
    elif code == "other_weak":
        slots["ret"] = factor.get("ret_fmt") or fmt_pct(ret)
    else:
        return None

    template = REASON_TEMPLATES.get(code)
    if not template:
        return None
    try:
        return template.format(**slots)
    except KeyError:
        return None


def build_review(
    *,
    code: str,
    ret: float,
    buy_open: float,
    sell_open: float,
    r_close: float | None = None,
    r_prev_close: float | None = None,
    r_volume: float | None = None,
    buy_close: float | None = None,
    buy_volume: float | None = None,
    idx_ret: float | None = None,
    industry_ret: float | None = None,
    industry_n: int | None = None,
    strategies: list[str] | None = None,
    asof: str | None = None,
) -> dict[str, Any] | None:
    """Build review block for a losing stock, or None if ret >= 0."""
    if ret >= 0:
        return None

    hits = evaluate_factors(
        code=code,
        ret=ret,
        buy_open=buy_open,
        sell_open=sell_open,
        r_close=r_close,
        r_prev_close=r_prev_close,
        r_volume=r_volume,
        buy_close=buy_close,
        buy_volume=buy_volume,
        idx_ret=idx_ret,
        industry_ret=industry_ret,
        industry_n=industry_n,
        strategies=strategies,
    )
    selected = select_tags(hits, ret=ret)
    tag_labels = [TAG_LABELS.get(f["code"], f["code"]) for f in selected]
    reasons: list[str] = []
    for f in selected[:2]:
        line = render_reason(f, ret=ret)
        if line:
            reasons.append(line)

    return {
        "tags": tag_labels,
        "factors": selected,
        "reasons": reasons,
        "asof": asof or date.today().isoformat(),
    }


def industry_horizon_return(
    peers: list[dict[str, Any]],
    buy_date: str,
    sell_date: str,
    get_open: Callable[[str, str], float | None],
) -> tuple[float | None, int]:
    """Equal-weight open→open return for peers with both opens. Returns (ret, n)."""
    rets: list[float] = []
    for peer in peers:
        code = peer.get("code") or peer.get("symbol")
        if not code:
            continue
        code = str(code).zfill(6)
        b = get_open(code, buy_date)
        s = get_open(code, sell_date)
        if b is None or s is None or b == 0:
            continue
        rets.append(s / b - 1.0)
    if not rets:
        return None, 0
    return sum(rets) / len(rets), len(rets)
