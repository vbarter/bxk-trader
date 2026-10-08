#!/usr/bin/env python3
"""Build A-share heatmap.json for 巴小卡 /heatmap (Tencent :8080 only).

heatmap-0.11.3
- asof      = latest stock_daily date with >= MIN_BARS bars (or --asof).
- spot      = one market snapshot (Eastmoney clist f12/f14/f3/f20/f21/f124,
              fallback Tencent qt.gtimg.cn fields 30/32/44/45), cached in
              data/heatmap_spot_cache.json. Provides 流通市值 (float cap), name,
              and the day pct when the snapshot trade date == asof.
- chg_pct   = raw (不复权) spot pct for the same trade date only; no stock_daily
              fallback (stock_daily is hfq). No same-day spot -> exit 2, keep old file.
- mktcap    = total cap (spot same-day, else market_cap_cache.json).
- float_mktcap = 流通市值 (spot); area_default = "float" if coverage >= 95% else "sqrt".
- Industry = 申万一级 from data/sw_industry_map.csv.
Run from close_pm after bars are synced; push with ./scripts/push-to-cf.sh heatmap (local :8787).
"""
from __future__ import annotations

import argparse
import csv
import datetime
import json
import sqlite3
import sys
import time
import unicodedata
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "sequoia_v2.db"
SW = ROOT / "data" / "sw_industry_map.csv"
CAP = ROOT / "data" / "market_cap_cache.json"
SPOT = ROOT / "data" / "heatmap_spot_cache.json"
OUT = ROOT / "data" / "heatmap.json"
MIN_BARS = 3000
FLOAT_COVERAGE_MIN = 95.0
DB_PCT_GUARD = 45.0  # |pct| above this from stock_daily fallback = adjustment break, drop
TZ = datetime.timezone(datetime.timedelta(hours=8))
UA = {"User-Agent": "Mozilla/5.0", "Referer": "https://quote.eastmoney.com/"}


def log(msg: str) -> None:
    print(f"[build_heatmap] {msg}", flush=True)


def norm_name(name: str | None) -> str:
    s = unicodedata.normalize("NFKC", str(name or "")).replace(" ", "").replace("\u3000", "").strip()
    return s


def fmp_logo_url(code: str) -> str | None:
    """Public FMP CDN logo URL. Many A-shares 404 → frontend falls back to 首字."""
    if not code or len(code) != 6 or not code.isdigit():
        return None
    if code.startswith(("6", "9")) and not code.startswith("92"):
        suffix = "SH"
    elif code.startswith(("0", "3")):
        suffix = "SZ"
    elif code.startswith(("4", "8", "92")):
        suffix = "BJ"
    else:
        return None
    return f"https://financialmodelingprep.com/image-stock/{code}.{suffix}.png"


def first_han(name: str) -> str:
    for ch in name or "":
        if "\u4e00" <= ch <= "\u9fff":
            return ch
    return (name[:1] if name else "?") or "?"


def fnum(v) -> float | None:
    try:
        if v in (None, "", "-"):
            return None
        f = float(v)
        return f if f == f else None
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------- spot feeds
def fetch_eastmoney() -> dict:
    import requests

    url = "https://push2.eastmoney.com/api/qt/clist/get"
    fs = "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048"
    rows: dict[str, dict] = {}
    dates: dict[str, int] = defaultdict(int)
    s = requests.Session()
    s.headers.update(UA)
    page, total = 1, None
    while True:
        r = s.get(url, params={"pn": page, "pz": 100, "po": 1, "np": 1, "fltt": 2, "invt": 2,
                               "fid": "f12", "fs": fs, "fields": "f12,f14,f2,f3,f18,f20,f21,f124"}, timeout=20)
        r.raise_for_status()
        data = r.json().get("data") or {}
        if total is None:
            total = int(data.get("total") or 0)
        diff = data.get("diff") or []
        if not diff:
            break
        for it in diff:
            code = str(it.get("f12") or "").zfill(6)
            ts = fnum(it.get("f124"))
            d = datetime.datetime.fromtimestamp(ts, TZ).strftime("%Y-%m-%d") if ts else None
            if d:
                dates[d] += 1
            rows[code] = {"name": norm_name(it.get("f14")), "pct": fnum(it.get("f3")), "close": fnum(it.get("f2")),
                          "prev": fnum(it.get("f18")), "total": fnum(it.get("f20")), "float": fnum(it.get("f21")),
                          "date": d}
        page += 1
        if total and len(rows) >= total:
            break
        time.sleep(0.05)
    return {"source": "eastmoney", "rows": rows}


def tencent_symbol(code: str) -> str | None:
    if code.startswith("92") or code.startswith(("4", "8")):
        return "bj" + code
    if code.startswith(("6", "9")):
        return "sh" + code
    if code.startswith(("0", "3")):
        return "sz" + code
    return None


def fetch_tencent(codes: list[str]) -> dict:
    import requests

    syms = [s for s in (tencent_symbol(c) for c in codes) if s]
    rows: dict[str, dict] = {}
    s = requests.Session()
    s.headers.update({"User-Agent": "Mozilla/5.0"})
    for i in range(0, len(syms), 80):
        batch = syms[i:i + 80]
        for attempt in range(3):
            try:
                r = s.get("https://qt.gtimg.cn/q=" + ",".join(batch), timeout=15)
                r.raise_for_status()
                text = r.content.decode("gbk", errors="replace")
                break
            except Exception as exc:  # noqa: BLE001
                if attempt == 2:
                    log(f"tencent batch {i} failed: {exc}")
                    text = ""
                time.sleep(0.5)
        for line in text.split(";"):
            if '="' not in line:
                continue
            body = line.split('="', 1)[1].rstrip('"\n ')
            f = body.split("~")
            if len(f) < 46 or not f[2]:
                continue
            code = f[2].zfill(6)
            dt = f[30][:8] if len(f[30]) >= 8 else ""
            d = f"{dt[:4]}-{dt[4:6]}-{dt[6:8]}" if dt.isdigit() else None
            fl, tt = fnum(f[44]), fnum(f[45])
            rows[code] = {"name": norm_name(f[1]), "pct": fnum(f[32]), "close": fnum(f[3]), "prev": fnum(f[4]),
                          "total": tt * 1e8 if tt else None, "float": fl * 1e8 if fl else None, "date": d}
        time.sleep(0.03)
    return {"source": "tencent", "rows": rows}


def load_spot(codes: list[str], asof: str, no_fetch: bool) -> dict:
    cached = None
    if SPOT.is_file():
        try:
            cached = json.loads(SPOT.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            cached = None
    if cached and cached.get("trade_date") == asof and len(cached.get("rows") or {}) >= MIN_BARS and no_fetch:
        return cached
    if not no_fetch:
        for name, fn in (("eastmoney", fetch_eastmoney), ("tencent", lambda: fetch_tencent(codes))):
            try:
                snap = fn()
            except Exception as exc:  # noqa: BLE001
                log(f"{name} spot failed: {exc}")
                continue
            rows = snap.get("rows") or {}
            if len(rows) < MIN_BARS:
                log(f"{name} spot too few rows: {len(rows)}")
                continue
            cnt: dict[str, int] = defaultdict(int)
            for r in rows.values():
                if r.get("date"):
                    cnt[r["date"]] += 1
            trade_date = max(cnt.items(), key=lambda kv: kv[1])[0] if cnt else None
            snap.update({"trade_date": trade_date, "fetched_at": datetime.datetime.now(TZ).isoformat()})
            SPOT.write_text(json.dumps(snap, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
            log(f"spot {name} rows={len(rows)} trade_date={trade_date} -> {SPOT.name}")
            return snap
    if cached:
        log(f"using cached spot trade_date={cached.get('trade_date')} source={cached.get('source')}")
        return cached
    return {"source": None, "rows": {}, "trade_date": None}


# ---------------------------------------------------------------- main
def full_dates(con: sqlite3.Connection) -> list[str]:
    rows = con.execute(
        "SELECT date, SUM(CASE WHEN close IS NOT NULL THEN 1 ELSE 0 END) FROM stock_daily "
        "GROUP BY date ORDER BY date DESC LIMIT 40").fetchall()
    return [str(d) for d, nz in rows if nz and nz >= MIN_BARS]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--asof", help="YYYY-MM-DD (default: latest full stock_daily date)")
    ap.add_argument("--no-fetch", action="store_true", help="do not hit spot feeds; use cache")
    args = ap.parse_args()

    for p in (DB, SW):
        if not p.is_file():
            print(f"missing {p}", file=sys.stderr)
            return 1

    cap_obj: dict = {}
    if CAP.is_file():
        cap_obj = json.loads(CAP.read_text(encoding="utf-8"))
    caps: dict[str, float] = {}
    for k, v in (cap_obj.get("caps") or {}).items():
        fv = fnum(v)
        if fv and fv > 0:
            caps[str(k).zfill(6)] = fv
    names_cap = {str(k).zfill(6): norm_name(v) for k, v in (cap_obj.get("names") or {}).items()}

    sw: dict[str, dict[str, str]] = {}
    with SW.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            sym = (row.get("symbol") or "").zfill(6)
            if sym.strip("0") == "":
                continue
            sw[sym] = {
                "name": norm_name(row.get("name")),
                "sw_l1_code": (row.get("sw_l1_code") or "").strip(),
                "sw_l1_name": (row.get("sw_l1_name") or "未分类").strip() or "未分类",
            }

    con = sqlite3.connect(str(DB))
    fulls = full_dates(con)
    if not fulls:
        raise SystemExit("stock_daily has no full-coverage date")
    asof = args.asof or fulls[0]
    prev_full = next((d for d in fulls if d < asof), None)
    rows = con.execute(
        """
        WITH ranked AS (
          SELECT symbol, date, close,
                 LAG(close) OVER (PARTITION BY symbol ORDER BY date) AS prev_close,
                 LAG(date)  OVER (PARTITION BY symbol ORDER BY date) AS prev_date
          FROM stock_daily WHERE close IS NOT NULL AND date <= ?
        )
        SELECT symbol, close, prev_close, prev_date FROM ranked WHERE date = ?
        """, (asof, asof)).fetchall()
    con.close()
    codes = sorted({str(r[0]).zfill(6) for r in rows})
    log(f"asof={asof} prev_full={prev_full} bars={len(rows)}")

    spot = load_spot(codes, asof, args.no_fetch)
    srows: dict[str, dict] = spot.get("rows") or {}
    spot_same_day = spot.get("trade_date") == asof
    if not spot_same_day:
        log(f"ABORT: no raw spot snapshot for asof={asof} (spot trade_date={spot.get('trade_date')}); "
            f"keeping previous heatmap.json (displayed change must be 不复权)")
        return 2

    by_ind: dict[str, list[dict]] = defaultdict(list)
    skipped = 0
    n_spot_pct = n_db_pct = n_float = n_noname = 0
    for sym_raw, close, prev, prev_date in rows:
        sym = str(sym_raw).zfill(6)
        sp = srows.get(sym) or {}
        sp_ok = spot_same_day and sp.get("date") == asof
        chg = None
        if sp_ok and sp.get("pct") is not None:
            chg = float(sp["pct"])
            n_spot_pct += 1
        # No stock_daily fallback for the displayed change: stock_daily is hfq (Tencent hfq
        # rescaled; not multiplicative), so its day-over-day % differs from the raw (不复权)
        # change the page promises. Only same-day raw spot pct is published.
        if chg is None:
            skipped += 1
            continue
        total = (sp.get("total") if sp_ok else None) or caps.get(sym) or sp.get("total")
        if not total or total <= 0:
            skipped += 1
            continue
        flt = sp.get("float") if sp.get("float") and sp.get("float") > 0 else None
        if flt:
            flt = min(flt, total)
            n_float += 1
        meta = sw.get(sym) or {}
        name = meta.get("name") or sp.get("name") or names_cap.get(sym) or ""
        if not name:
            n_noname += 1
            name = sym
        ind_name = meta.get("sw_l1_name") or "未分类"
        by_ind[ind_name].append({
            "code": sym,
            "name": name,
            "short": first_han(name),
            "chg_pct": round(chg, 2),
            "mktcap": round(float(total), 2),
            "float_mktcap": round(float(flt), 2) if flt else None,
            "logo": fmp_logo_url(sym),
        })

    industries: list[dict] = []
    for ind_name, stocks in by_ind.items():
        stocks.sort(key=lambda s: -s["mktcap"])
        code = next((sw[s["code"]]["sw_l1_code"] for s in stocks if sw.get(s["code"], {}).get("sw_l1_code")), "")
        industries.append({
            "code": code,
            "name": ind_name,
            "mktcap": round(sum(s["mktcap"] for s in stocks), 2),
            "float_mktcap": round(sum((s["float_mktcap"] or 0) for s in stocks), 2),
            "count": len(stocks),
            "stocks": stocks,
        })
    industries.sort(key=lambda x: -x["mktcap"])

    total_stocks = sum(i["count"] for i in industries)
    float_cov = round(100.0 * n_float / total_stocks, 2) if total_stocks else 0.0
    area_default = "float" if float_cov >= FLOAT_COVERAGE_MIN else "sqrt"
    with_logo = sum(1 for ind in industries for s in ind["stocks"] if s.get("logo"))
    payload = {
        "version": "heatmap-0.11.3",
        "generated_at": datetime.datetime.now(TZ).isoformat(),
        "asof": asof,
        "tz": "Asia/Shanghai",
        "area_default": area_default,
        "area_modes": ["float", "sqrt", "total"],
        "float_coverage": float_cov,
        "mktcap_field": "total_mktcap",
        "float_field": "float_mktcap (eastmoney f21 / tencent #44)",
        "mktcap_source": f"spot={spot.get('source')}@{spot.get('trade_date')} cap_cache={cap_obj.get('date')}",
        "chg_source": f"spot_pct={n_spot_pct} db_close_vs_prev={n_db_pct} prev_full={prev_full}",
        "stock_count": total_stocks,
        "industry_count": len(industries),
        "skipped": skipped,
        "names_missing": n_noname,
        "logo_coverage": {"with_logo": with_logo, "total": total_stocks,
                          "pct": round(100.0 * with_logo / total_stocks, 1) if total_stocks else 0.0},
        "industries": industries,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    log(f"wrote {OUT} bytes={OUT.stat().st_size} asof={asof} stocks={total_stocks} industries={len(industries)} "
        f"skipped={skipped} spot_pct={n_spot_pct} db_pct={n_db_pct} float_cov={float_cov}% area_default={area_default} "
        f"names_missing={n_noname}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
