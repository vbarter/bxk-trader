#!/usr/bin/env python3
"""Hourly A-share disclosure news scanner → data/news_events.json.

Sources (MVP, fail-soft):
  - stock_notice_report (东财公告列表) keyword-classified into earnings/mna/legal
  - stock_info_global_cls (财联社) optional mna keyword supplement
  - stock_cg_lawsuit_cninfo optional legal (often flaky)
  - opinion OFF by default

Cron: 5 * * * * → scripts/run_news_hourly.sh
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
OUT_PATH = DATA_DIR / "news_events.json"
KEEP_DAYS = 45
MAX_EVENTS = 800
OPINION_ENABLED = False
SOURCE_NOTICE = "东财公告"
SOURCE_CLS = "财联社"
SOURCE_LAWSUIT = "巨潮诉讼仲裁"

EARN_RE = re.compile(r"年报|半年报|季报|业绩预告|业绩快报|盈利预告")
MNA_RE = re.compile(r"收购|重组|要约收购|股权转让|重大资产|吸收合并")
LEGAL_RE = re.compile(r"诉讼|仲裁|判决|处罚|立案|监管函|问询函")
CODE_RE = re.compile(r"(?<!\d)([036]\d{5})(?!\d)")

TZ_SH = timezone(timedelta(hours=8))


def warn(msg: str) -> None:
    print(f"[news][warn] {msg}", file=sys.stderr, flush=True)


def info(msg: str) -> None:
    print(f"[news] {msg}", flush=True)


def now_sh() -> datetime:
    return datetime.now(TZ_SH)


def iso_now() -> str:
    return now_sh().isoformat(timespec="seconds")


def trunc(text: str, n: int) -> str:
    text = re.sub(r"\s+", " ", (text or "").strip())
    if len(text) <= n:
        return text
    return text[: n - 1] + "…"


def event_id(source_name: str, source_url: str, title: str) -> str:
    raw = f"{source_name}|{source_url}|{title}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def normalize_code(value: Any) -> str:
    if value is None:
        return ""
    s = str(value).strip()
    if re.fullmatch(r"\d{6}", s):
        return s
    m = CODE_RE.search(s)
    return m.group(1) if m else ""


def classify_title(title: str) -> str | None:
    """Priority: legal > mna > earnings (more specific first)."""
    if LEGAL_RE.search(title):
        return "legal"
    if MNA_RE.search(title):
        return "mna"
    if EARN_RE.search(title):
        return "earnings"
    return None


def parse_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    s = str(value).strip()
    m = re.search(r"(\d{4})[-/]?(\d{2})[-/]?(\d{2})", s)
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def parse_datetime(value: Any, fallback_day: date | None = None) -> tuple[str, str, str]:
    """Return (iso datetime Shanghai, YYYY-MM-DD, time_precision).

    time_precision is "minute" only when the source string/datetime carries a real clock.
    Date-only values use day-start 00:00 and precision "day" — never invent 12:00.
    """
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=TZ_SH)
        dt = dt.astimezone(TZ_SH)
        # Midnight-only timestamps usually come from date columns (e.g. 公告日期) — treat as day.
        precision = (
            "day"
            if (dt.hour, dt.minute, dt.second, dt.microsecond) == (0, 0, 0, 0)
            else "minute"
        )
        if precision == "day":
            dt = datetime(dt.year, dt.month, dt.day, 0, 0, 0, tzinfo=TZ_SH)
        return dt.isoformat(timespec="seconds"), dt.date().isoformat(), precision
    if isinstance(value, date) and not isinstance(value, datetime):
        day = value
        dt = datetime(day.year, day.month, day.day, 0, 0, 0, tzinfo=TZ_SH)
        return dt.isoformat(timespec="seconds"), day.isoformat(), "day"
    s = str(value or "").strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M:%S", "%Y/%m/%d %H:%M"):
        try:
            dt = datetime.strptime(s[:19], fmt).replace(tzinfo=TZ_SH)
            precision = "day" if (dt.hour, dt.minute, dt.second) == (0, 0, 0) else "minute"
            if precision == "day":
                dt = datetime(dt.year, dt.month, dt.day, 0, 0, 0, tzinfo=TZ_SH)
            return dt.isoformat(timespec="seconds"), dt.date().isoformat(), precision
        except ValueError:
            continue
    # ISO-ish with T and clock
    m = re.match(r"^(\d{4}-\d{2}-\d{2})[T ](\d{2}):(\d{2})(?::(\d{2}))?", s)
    if m:
        sec = int(m.group(4) or 0)
        hour, minute = int(m.group(2)), int(m.group(3))
        precision = "day" if (hour, minute, sec) == (0, 0, 0) else "minute"
        dt = datetime(
            int(m.group(1)[0:4]), int(m.group(1)[5:7]), int(m.group(1)[8:10]),
            0 if precision == "day" else hour,
            0 if precision == "day" else minute,
            0 if precision == "day" else sec,
            tzinfo=TZ_SH,
        )
        return dt.isoformat(timespec="seconds"), dt.date().isoformat(), precision
    day = parse_date(value) or fallback_day or now_sh().date()
    dt = datetime(day.year, day.month, day.day, 0, 0, 0, tzinfo=TZ_SH)
    return dt.isoformat(timespec="seconds"), day.isoformat(), "day"


def normalize_stored_event(ev: dict[str, Any]) -> dict[str, Any]:
    """Backfill time_precision; rewrite legacy fake 12:00 date-only stamps to 00:00 day."""
    out = dict(ev)
    prec = out.get("time_precision")
    if prec in ("day", "minute"):
        if prec == "day":
            day = str(out.get("date") or "")[:10]
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
                out["datetime"] = f"{day}T00:00:00+08:00"
        return out
    raw = str(out.get("datetime") or "")
    day = str(out.get("date") or "")[:10]
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
        parsed_day = parse_date(raw) or parse_date(out.get("date"))
        day = parsed_day.isoformat() if parsed_day else now_sh().date().isoformat()
        out["date"] = day
    # Legacy East Money date-only fallback invented 12:00 — treat as day precision.
    if re.search(r"T12:00:00", raw) or re.search(r"\s12:00:00", raw):
        out["datetime"] = f"{day}T00:00:00+08:00"
        out["time_precision"] = "day"
        return out
    if re.search(r"T\d{2}:\d{2}", raw) or re.search(r"\s\d{2}:\d{2}", raw):
        # Clock present and not the legacy noon stub.
        if re.search(r"T00:00:00", raw) and not re.search(r"T00:00:00\.\d", raw):
            # Ambiguous midnight with no precision flag: keep as day (safe for notices).
            out["datetime"] = f"{day}T00:00:00+08:00"
            out["time_precision"] = "day"
        else:
            out["time_precision"] = "minute"
        return out
    out["datetime"] = f"{day}T00:00:00+08:00"
    out["time_precision"] = "day"
    return out


def make_event(
    *,
    company: str,
    code: str,
    title: str,
    summary: str,
    source_name: str,
    source_url: str,
    category: str,
    when: Any,
    tags: list[str] | None = None,
) -> dict[str, Any] | None:
    title = trunc(title, 80)
    if not title:
        return None
    source_url = (source_url or "").strip()
    if not source_url:
        return None
    dt_iso, day, precision = parse_datetime(when)
    code = normalize_code(code)
    company = trunc(company or "", 40)
    summary = trunc(summary or title, 120)
    return {
        "id": event_id(source_name, source_url, title),
        "datetime": dt_iso,
        "date": day,
        "time_precision": precision,
        "company": company,
        "code": code,
        "title": title,
        "summary": summary,
        "source_name": source_name,
        "source_url": source_url,
        "category": category,
        "tags": tags or [],
    }


def load_existing() -> list[dict[str, Any]]:
    if not OUT_PATH.exists():
        return []
    try:
        data = json.loads(OUT_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        warn(f"cannot read existing {OUT_PATH}: {e}")
        return []
    events = data.get("events") if isinstance(data, dict) else None
    if not isinstance(events, list):
        return []
    out: list[dict[str, Any]] = []
    for item in events:
        if isinstance(item, dict) and item.get("id") and item.get("source_url") and item.get("title"):
            out.append(normalize_stored_event(item))
    return out


def fetch_notice_day(day: date) -> list[dict[str, Any]]:
    import akshare as ak

    ds = day.strftime("%Y%m%d")
    info(f"notice fetch {ds}")
    try:
        df = ak.stock_notice_report(symbol="全部", date=ds)
    except Exception as e:
        warn(f"notice {ds} failed: {type(e).__name__}: {e}")
        return []
    if df is None or getattr(df, "empty", True):
        info(f"notice {ds}: empty")
        return []
    events: list[dict[str, Any]] = []
    for row in df.to_dict(orient="records"):
        title = str(row.get("公告标题") or "")
        category = classify_title(title)
        if not category:
            continue
        notice_type = str(row.get("公告类型") or "").strip()
        summary = title if not notice_type else f"{notice_type}：{title}"
        ev = make_event(
            company=str(row.get("名称") or ""),
            code=row.get("代码"),
            title=title,
            summary=summary,
            source_name=SOURCE_NOTICE,
            source_url=str(row.get("网址") or ""),
            category=category,
            when=row.get("公告日期") or day,
            tags=[notice_type] if notice_type else [],
        )
        if ev:
            events.append(ev)
    info(f"notice {ds}: kept {len(events)} / {len(df)}")
    return events


def _call_with_timeout(fn, timeout_s: float, *args, **kwargs):
    from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
    pool = ThreadPoolExecutor(max_workers=1)
    try:
        fut = pool.submit(fn, *args, **kwargs)
        return fut.result(timeout=timeout_s)
    except FuturesTimeout:
        raise TimeoutError(f"timed out after {timeout_s}s")
    finally:
        pool.shutdown(wait=False, cancel_futures=True)


def fetch_cls_mna() -> list[dict[str, Any]]:
    import akshare as ak

    info("cls fetch")
    try:
        df = _call_with_timeout(ak.stock_info_global_cls, 25, "全部")
    except TimeoutError as e:
        warn(f"cls {e}")
        return []
    except Exception as e:
        warn(f"cls failed: {type(e).__name__}: {e}")
        return []
    if df is None or getattr(df, "empty", True):
        info("cls: empty")
        return []
    # Flexible column names across akshare versions
    cols = {str(c): c for c in df.columns}
    title_col = cols.get("标题") or cols.get("内容") or list(df.columns)[0]
    time_col = cols.get("发布时间") or cols.get("时间") or cols.get("发布日期")
    url_col = cols.get("链接") or cols.get("网址") or cols.get("url")
    events: list[dict[str, Any]] = []
    for row in df.to_dict(orient="records"):
        title = str(row.get(title_col) or "")
        if not MNA_RE.search(title):
            continue
        url = str(row.get(url_col) or "") if url_col else ""
        if not url:
            # CLS items sometimes lack URL — synthesize stable anchor-less id host
            url = f"https://www.cls.cn/searchPage?keyword={title[:40]}"
        when = row.get(time_col) if time_col else now_sh()
        code_m = CODE_RE.search(title)
        ev = make_event(
            company="",
            code=code_m.group(1) if code_m else "",
            title=title,
            summary=title,
            source_name=SOURCE_CLS,
            source_url=url,
            category="mna",
            when=when,
            tags=["cls"],
        )
        if ev:
            events.append(ev)
    info(f"cls mna kept {len(events)} / {len(df)}")
    return events


def fetch_lawsuit() -> list[dict[str, Any]]:
    import akshare as ak

    end = now_sh().date()
    start = end - timedelta(days=30)
    info(f"lawsuit fetch {start}..{end}")
    try:
        df = _call_with_timeout(
            ak.stock_cg_lawsuit_cninfo,
            20,
            "全部",
            start.strftime("%Y%m%d"),
            end.strftime("%Y%m%d"),
        )
    except TimeoutError as e:
        warn(f"lawsuit {e}")
        return []
    except Exception as e:
        warn(f"lawsuit failed: {type(e).__name__}: {e}")
        return []
    if df is None or getattr(df, "empty", True):
        info("lawsuit: empty")
        return []
    cols = {str(c): c for c in df.columns}
    title_col = cols.get("案件名称") or cols.get("公告标题") or cols.get("标题")
    code_col = cols.get("证券代码") or cols.get("代码")
    name_col = cols.get("证券简称") or cols.get("名称")
    date_col = cols.get("公告日期") or cols.get("披露日期") or cols.get("日期")
    url_col = cols.get("网址") or cols.get("链接")
    events: list[dict[str, Any]] = []
    for row in df.to_dict(orient="records"):
        title = str(row.get(title_col) or "") if title_col else ""
        if not title:
            continue
        url = str(row.get(url_col) or "") if url_col else ""
        if not url:
            url = f"https://www.cninfo.com.cn/new/fulltextSearch?notations=&keyWord={title[:40]}"
        ev = make_event(
            company=str(row.get(name_col) or "") if name_col else "",
            code=row.get(code_col) if code_col else "",
            title=title,
            summary=title,
            source_name=SOURCE_LAWSUIT,
            source_url=url,
            category="legal",
            when=row.get(date_col) if date_col else end,
            tags=["lawsuit"],
        )
        if ev:
            events.append(ev)
    info(f"lawsuit kept {len(events)} / {len(df)}")
    return events


def merge_events(existing: list[dict[str, Any]], fresh: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for ev in existing + fresh:
        eid = str(ev.get("id") or "")
        if not eid:
            continue
        ev = normalize_stored_event(ev)
        # Prefer fresher same-id only if missing fields filled — else first wins then overwrite with newer datetime
        prev = by_id.get(eid)
        if prev is None:
            by_id[eid] = ev
            continue
        # Prefer minute-precision over day when same id; otherwise newer datetime wins.
        prev_prec = prev.get("time_precision")
        ev_prec = ev.get("time_precision")
        if prev_prec == "day" and ev_prec == "minute":
            by_id[eid] = ev
            continue
        if prev_prec == "minute" and ev_prec == "day":
            continue
        if str(ev.get("datetime") or "") >= str(prev.get("datetime") or ""):
            by_id[eid] = ev
    cutoff = (now_sh().date() - timedelta(days=KEEP_DAYS)).isoformat()
    events = [e for e in by_id.values() if str(e.get("date") or "") >= cutoff]
    if not OPINION_ENABLED:
        events = [e for e in events if e.get("category") != "opinion"]
    events.sort(key=lambda e: (str(e.get("datetime") or ""), str(e.get("id") or "")), reverse=True)
    return events[:MAX_EVENTS]


def build_by_day(events: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {}
    for ev in events:
        day = str(ev.get("date") or "")
        cat = str(ev.get("category") or "")
        if not day:
            continue
        bucket = out.setdefault(day, {"total": 0, "earnings": 0, "mna": 0, "legal": 0, "opinion": 0})
        bucket["total"] += 1
        if cat in bucket:
            bucket[cat] += 1
    return dict(sorted(out.items()))


def count_cats(events: list[dict[str, Any]]) -> dict[str, int]:
    counts = {"earnings": 0, "mna": 0, "legal": 0, "opinion": 0, "total": len(events)}
    for ev in events:
        cat = ev.get("category")
        if cat in counts:
            counts[cat] += 1
    return counts


def trading_lookback_days(n_calendar: int = 10) -> list[date]:
    """Calendar lookback (includes weekends; notice API returns empty off-days)."""
    today = now_sh().date()
    return [today - timedelta(days=i) for i in range(n_calendar)]


def main() -> int:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    seed = "--seed" in sys.argv
    lookback = 10 if seed else 2
    existing = load_existing()
    info(f"start seed={seed} lookback={lookback} existing={len(existing)}")

    fresh: list[dict[str, Any]] = []
    for day in trading_lookback_days(lookback):
        fresh.extend(fetch_notice_day(day))
        time.sleep(0.4)

    # Optional supplements — soft fail; skip unless --with-optional (CLS often hangs)
    if "--with-optional" in sys.argv:
        try:
            fresh.extend(fetch_cls_mna())
        except Exception as e:
            warn(f"cls unexpected: {e}")
        try:
            fresh.extend(fetch_lawsuit())
        except Exception as e:
            warn(f"lawsuit unexpected: {e}")
    else:
        info("skip optional CLS/lawsuit (pass --with-optional to enable)")

    merged = merge_events(existing, fresh)
    counts = count_cats(merged)
    payload = {
        "generated_at": iso_now(),
        "scanned_at": iso_now(),
        "opinion_enabled": OPINION_ENABLED,
        "keep_days": KEEP_DAYS,
        "note": "小时扫描 · 披露优先。财报、并购、法务以公告为准；舆论可选且非事实。仅供观察，不构成投资建议。",
        "counts": counts,
        "events": merged,
        "by_day": build_by_day(merged),
    }
    tmp = OUT_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(OUT_PATH)
    info(f"wrote {OUT_PATH} events={counts}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
