#!/usr/bin/env python3
"""Fill today OHLCV via Sina Market_Center when baostock/tencent-fqkline fail.

Spot = 不复权 → converted to the DB hfq base (2026-09-27):
  k = last DB close (hfq) / sina settlement (prev raw close); prices*k; volume 股→手.
  Exact except on an ex-dividend day. Only fills missing (symbol,date) rows; no date-wide DELETE.
"""
from __future__ import annotations

import json
import sqlite3
import sys
import time
import urllib.request
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / 'data' / 'sequoia_v2.db'
TODAY = date.today().strftime('%Y-%m-%d')
MIN_ROWS = 4000
PAGE_SIZE = 80
NODE = 'hs_a'


def fetch_page(page: int) -> list:
    url = (
        'https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/'
        f'Market_Center.getHQNodeData?page={page}&num={PAGE_SIZE}'
        f'&sort=symbol&asc=1&node={NODE}&symbol=&_s_r_a=page'
    )
    req = urllib.request.Request(
        url,
        headers={
            'User-Agent': 'Mozilla/5.0',
            'Referer': 'https://finance.sina.com.cn/',
        },
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        raw = resp.read().decode('utf-8', errors='replace').strip()
    if not raw or raw in ('null', '[]'):
        return []
    data = json.loads(raw)
    if not isinstance(data, list):
        return []
    return data


def to_row(item: dict):
    code = str(item.get('code') or '').zfill(6)
    if not code.isdigit() or len(code) != 6:
        return None
    sym = str(item.get('symbol') or '')
    if sym.startswith('bj'):
        return None

    def num(v):
        if v in (None, '', '-'):
            return None
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    open_ = num(item.get('open'))
    high = num(item.get('high'))
    low = num(item.get('low'))
    close = num(item.get('trade'))
    prev = num(item.get('settlement'))
    vol = num(item.get('volume'))
    amt = num(item.get('amount'))
    if close is None or close <= 0:
        return None
    if vol is not None and vol <= 0:
        return None
    return (code, TODAY, open_, high, low, close, vol, amt, prev)


def main() -> int:
    print(f'[sync_today_sina] {TODAY}: fetching node={NODE}', flush=True)
    t0 = time.time()
    rows = []
    seen = set()
    page = 1
    empty_streak = 0
    while page <= 200:
        try:
            items = fetch_page(page)
        except Exception as exc:
            print(f'[sync_today_sina] page {page} fail: {exc}', flush=True)
            empty_streak += 1
            if empty_streak >= 3 and page > 1:
                break
            time.sleep(1.0)
            page += 1
            continue
        if not items:
            empty_streak += 1
            if empty_streak >= 2:
                break
            page += 1
            continue
        empty_streak = 0
        for item in items:
            row = to_row(item)
            if row is None or row[0] in seen:
                continue
            seen.add(row[0])
            rows.append(row)
        print(f'  page {page} got={len(items)} cumulative_ok={len(rows)}', flush=True)
        if len(items) < PAGE_SIZE:
            break
        page += 1
        time.sleep(0.15)
    print(f'[sync_today_sina] fetched ok={len(rows)} in {time.time()-t0:.1f}s', flush=True)
    if len(rows) < MIN_ROWS:
        print(f'[sync_today_sina] too few (<{MIN_ROWS}); abort', flush=True)
        return 1
    with sqlite3.connect(DB_PATH) as conn:
        out = []
        no_k = 0
        for code, d, o, h, l, c, vol, amt, prev in rows:
            last = conn.execute(
                'SELECT close FROM stock_daily WHERE symbol=? AND date<? AND close>0 ORDER BY date DESC LIMIT 1',
                (code, TODAY)).fetchone()
            if last and prev and prev > 0:
                k = float(last[0]) / prev
            else:
                k = 1.0  # new listing: hfq == raw until first dividend
                no_k += 1
            f = lambda x: round(x * k, 6) if x is not None else None
            out.append((code, d, f(o), f(h), f(l), f(c), round(vol / 100.0, 2) if vol else vol, amt))
        print(f'[sync_today_sina] hfq-scaled {len(out)} rows (k=1 for {no_k} without prior bar)', flush=True)
        conn.executemany(
            'INSERT INTO stock_daily (symbol, date, open, high, low, close, volume, turnover) '
            'VALUES (?, ?, ?, ?, ?, ?, ?, ?) '
            'ON CONFLICT(symbol, date) DO NOTHING',  # keep tencent-hfq rows (exact on ex-div days); only fill gaps
            out,
        )
        conn.commit()
        n = conn.execute('SELECT COUNT(*) FROM stock_daily WHERE date = ?', (TODAY,)).fetchone()[0]
        n_close = conn.execute(
            'SELECT COUNT(*) FROM stock_daily WHERE date = ? AND close > 0', (TODAY,)
        ).fetchone()[0]
    print(f'[sync_today_sina] wrote {n} rows for {TODAY} (close>0={n_close})', flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
