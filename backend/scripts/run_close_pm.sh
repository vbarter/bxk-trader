#!/bin/sh
# Close scan PM — Asia/Shanghai 15:05 weekdays (cron: 5 15 * * 1-5)
#
# Post-close pipeline (replaces the old 19:15 run_daily cron):
#   - skip non-trading days
#   - full strategy scan via main.py (writes data/latest.json)
#   - export_details.py: quotes/names/meta/details for ALL unique strategy symbols (not a fixed pool)
#   - write_daily_picks.py: Top5 for signal day R
#       * LLM Top5 (source=llm_rerank, pick_status=ok); 3 attempts (backoff 20s/60s)
#       * all attempts fail / key missing / no candidates / LLM_RERANK off → day PAUSED
#         (symbols=[], pick_status=paused, pause_reason, attempts). No rule_order fallback.
#       * PICK_MODE=shadow (default): main LLM + _shadow/*.multi_hit.json (not CF)
#       * ALLOW_MULTI_HIT_MAIN=0 (default): blocks PICK_MODE=multi_hit main cutover
#       * MIN_VALID_STOCKS=4000: skip picks write if stock_daily coverage too low
#   - export_watch_calendar.py (open→open; does not require close to settle past days)
#   - build_heatmap.py: /heatmap data for today's close (spot pct + 流通市值)
#   - push latest + details + watch_calendar + heatmap to local Tencent Worker (:8787 / nginx :8080)
#   - CF ingest gated by SKIP_CF (default 1 = frozen 2026-09-23, Tencent-only; set SKIP_CF=0 to resume)
#
# Manual full runs can still use ./scripts/run_daily.sh (kept on purpose; not on cron).
# Log: /root/dev/Sequoia-X/log_close_pm.txt
set -eu
cd /root/dev/Sequoia-X

# Load .env if present (does not override already-exported vars)
if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
fi

# Enable LLM Top5 rerank for close_pm (failure → paused day, never rule_order)
export LLM_RERANK="${LLM_RERANK:-1}"
# Dual model: gpt (gpt-6.1-sol) active; Claude (claude-opus-5-5) paused via
# ENABLE_CLAUDE=0 / PICK_MODELS=gpt (historical Claude picks kept, no new API).
export ENABLE_CLAUDE="${ENABLE_CLAUDE:-0}"
export PICK_MODELS="${PICK_MODELS:-gpt}"  # Claude paused: ENABLE_CLAUDE=0 → gpt only
# 序5 (2026-10-02): multi_hit is SHADOW ONLY by default.
#   PICK_MODE=shadow → main = dual-model LLM Top5; also writes
#   data/daily_picks/_shadow/YYYY-MM-DD.multi_hit.json (track=multi_hit_shadow).
#   Never pushes shadow into watch_calendar live Top5 / latest home picks.
# Hard gate: PICK_MODE=multi_hit as MAIN requires ALLOW_MULTI_HIT_MAIN=1 (default OFF).
# MULTI_HIT_ENABLED remains legacy (old dual-track calendar UI); do NOT reintroduce that UI.
export ALLOW_MULTI_HIT_MAIN="${ALLOW_MULTI_HIT_MAIN:-0}"
export MULTI_HIT_ENABLED="${MULTI_HIT_ENABLED:-0}"
# Default shadow (unknown / unset → shadow). Respect explicit PICK_MODE from env.
export PICK_MODE="${PICK_MODE:-shadow}"
# 序2: coverage gate — skip normal Top5 write if stock_daily < threshold.
export MIN_VALID_STOCKS="${MIN_VALID_STOCKS:-4000}"

# CF frozen 2026-09-23 — Tencent-only. Reversible: SKIP_CF=0
export SKIP_CF="${SKIP_CF:-1}"

echo "===== close_pm start $(date -Iseconds) ====="
echo "[close_pm] LLM_RERANK=${LLM_RERANK} PICK_MODE=${PICK_MODE} PICK_MODELS=${PICK_MODELS} ENABLE_CLAUDE=${ENABLE_CLAUDE} ALLOW_MULTI_HIT_MAIN=${ALLOW_MULTI_HIT_MAIN} MULTI_HIT_ENABLED=${MULTI_HIT_ENABLED} MIN_VALID_STOCKS=${MIN_VALID_STOCKS}"

if ! .venv/bin/python scripts/is_trading_day.py; then
  echo "[close_pm] skip: non-trading day"
  echo "===== close_pm end $(date -Iseconds) ====="
  exit 0
fi

.venv/bin/python main.py

# --- baostock blacklist / lag fallback (10001011 etc.) ---
# If today's stock_daily coverage is below MIN_VALID_STOCKS, try backup feeds
# before details/picks so the coverage gate can pass.
_cov_day="$(date +%F)"
_cov_n="$(.venv/bin/python -c "
import sqlite3
from pathlib import Path
day='${_cov_day}'
db=Path('data/sequoia_v2.db')
n=0
if db.exists():
    with sqlite3.connect(db) as c:
        n=c.execute('SELECT COUNT(DISTINCT symbol) FROM stock_daily WHERE date=?', (day,)).fetchone()[0]
print(n)
")"
echo "[close_pm] coverage ${_cov_day}=${_cov_n} (MIN_VALID_STOCKS=${MIN_VALID_STOCKS:-4000})"
_cov_backup=0
if [ "${_cov_n}" -lt "${MIN_VALID_STOCKS:-4000}" ]; then
  _cov_backup=1
  echo "[close_pm] coverage low; trying backup feeds (tencent fqkline hfq -> sina (hfq-scaled) -> akshare hfq)"
  if ! .venv/bin/python scripts/sync_today_tencent.py; then
    echo "[warn] sync_today_tencent failed or too few rows" >&2
  fi
  _cov_n="$(.venv/bin/python -c "
import sqlite3
from pathlib import Path
day='${_cov_day}'
with sqlite3.connect(Path('data/sequoia_v2.db')) as c:
    print(c.execute('SELECT COUNT(DISTINCT symbol) FROM stock_daily WHERE date=?', (day,)).fetchone()[0])
")"
  echo "[close_pm] after tencent coverage=${_cov_n}"
  if [ "${_cov_n}" -lt "${MIN_VALID_STOCKS:-4000}" ]; then
    if ! .venv/bin/python scripts/sync_today_sina.py; then
      echo "[warn] sync_today_sina failed or too few rows" >&2
    fi
    _cov_n="$(.venv/bin/python -c "
import sqlite3
from pathlib import Path
day='${_cov_day}'
with sqlite3.connect(Path('data/sequoia_v2.db')) as c:
    print(c.execute('SELECT COUNT(DISTINCT symbol) FROM stock_daily WHERE date=?', (day,)).fetchone()[0])
")"
    echo "[close_pm] after sina coverage=${_cov_n}"
  fi
  if [ "${_cov_n}" -lt "${MIN_VALID_STOCKS:-4000}" ] && [ -f scripts/sync_today_akshare.py ]; then
    if ! .venv/bin/python scripts/sync_today_akshare.py "${_cov_day}"; then
      echo "[warn] sync_today_akshare failed or too few rows" >&2
    fi
    _cov_n="$(.venv/bin/python -c "
import sqlite3
from pathlib import Path
day='${_cov_day}'
with sqlite3.connect(Path('data/sequoia_v2.db')) as c:
    print(c.execute('SELECT COUNT(DISTINCT symbol) FROM stock_daily WHERE date=?', (day,)).fetchone()[0])
")"
    echo "[close_pm] after akshare coverage=${_cov_n}"
  fi
  if [ "${_cov_n}" -ge "${MIN_VALID_STOCKS:-4000}" ]; then
    echo "[close_pm] coverage recovered via backup feed (tencent hfq / sina raw->hfq scaled to DB base, per-row upsert); keep existing latest.json"
  else
    echo "[warn] coverage still below gate after backups: ${_cov_n}" >&2
  fi
fi

# 2026-09-29: the first main.py scan ran before the signal-day bars existed
# (09-28 scanned 09-24 data). If a backup feed filled today, rescan now.
if [ "${_cov_backup}" = "1" ] && [ "${_cov_n}" -ge "${MIN_VALID_STOCKS:-4000}" ]; then
  echo "[close_pm] rescan after backup feed (SKIP_SYNC=1 main.py) so strategies see ${_cov_day}"
  if ! SKIP_SYNC=1 .venv/bin/python main.py; then
    echo "[warn] rescan failed; write_daily_picks scan-date guard will pause the day" >&2
  fi
fi


if ! .venv/bin/python scripts/export_details.py; then
  echo "[warn] detail export partially failed" >&2
fi

if ! .venv/bin/python scripts/write_daily_picks.py; then
  echo "[warn] write_daily_picks failed" >&2
fi

.venv/bin/python scripts/export_watch_calendar.py

# Finalize calendar payload (pick_source; multi_hit track only if MULTI_HIT_ENABLED=1).
if ! .venv/bin/python scripts/build_dual_track_calendar.py; then
  echo "[warn] build_dual_track_calendar failed" >&2
  .venv/bin/python scripts/dual_basis.py || echo "[warn] dual_basis fallback failed" >&2
elif ! .venv/bin/python scripts/patch_calendar_pick_source.py; then
  echo "[warn] patch_calendar_pick_source failed" >&2
fi

# Heatmap (/heatmap) — rebuild for today's close once bars are synced (heatmap-0.11.3).
# Non-fatal: on failure the previous heatmap.json stays in place.
_heatmap_ok=0
if .venv/bin/python scripts/build_heatmap.py; then
  _heatmap_ok=1
else
  echo "[warn] build_heatmap failed; keeping previous heatmap.json" >&2
fi

if [ -f .ingest_token ]; then
  INGEST_TOKEN=$(cat .ingest_token)
  # Local Tencent worker (:8787 behind nginx :8080) — primary
  SEQUOIA_X_WORKER_URL="${SEQUOIA_X_WORKER_URL_LOCAL:-http://127.0.0.1:8787}" \
    INGEST_TOKEN="$INGEST_TOKEN" ./scripts/push-to-cf.sh latest \
    || echo "[warn] local latest ingest failed" >&2
  SEQUOIA_X_WORKER_URL="${SEQUOIA_X_WORKER_URL_LOCAL:-http://127.0.0.1:8787}" \
    INGEST_TOKEN="$INGEST_TOKEN" ./scripts/push-details-to-cf.sh \
    || echo "[warn] local detail ingest partially failed" >&2
  SEQUOIA_X_WORKER_URL="${SEQUOIA_X_WORKER_URL_LOCAL:-http://127.0.0.1:8787}" \
    INGEST_TOKEN="$INGEST_TOKEN" ./scripts/push-to-cf.sh watch_calendar \
    || echo "[warn] local watch_calendar ingest failed" >&2
  if [ "${_heatmap_ok}" = "1" ]; then
    SEQUOIA_X_WORKER_URL="${SEQUOIA_X_WORKER_URL_LOCAL:-http://127.0.0.1:8787}" \
      INGEST_TOKEN="$INGEST_TOKEN" ./scripts/push-to-cf.sh heatmap \
      || echo "[warn] local heatmap ingest failed" >&2
  fi
  # CF (frozen 2026-09-23; SKIP_CF=1 default). Set SKIP_CF=0 to resume dual-push.
  if [ "${SKIP_CF:-1}" = "0" ]; then
    SEQUOIA_X_WORKER_URL="${SEQUOIA_X_WORKER_URL_CF:-https://sequoia-x-web.YOUR_SUBDOMAIN.workers.dev}" \
      INGEST_TOKEN="$INGEST_TOKEN" ./scripts/push-to-cf.sh latest \
      || echo "[warn] CF latest ingest failed" >&2
    SEQUOIA_X_WORKER_URL="${SEQUOIA_X_WORKER_URL_CF:-https://sequoia-x-web.YOUR_SUBDOMAIN.workers.dev}" \
      INGEST_TOKEN="$INGEST_TOKEN" ./scripts/push-details-to-cf.sh \
      || echo "[warn] CF detail ingest partially failed" >&2
    SEQUOIA_X_WORKER_URL="${SEQUOIA_X_WORKER_URL_CF:-https://sequoia-x-web.YOUR_SUBDOMAIN.workers.dev}" \
      INGEST_TOKEN="$INGEST_TOKEN" ./scripts/push-to-cf.sh watch_calendar \
      || echo "[warn] CF watch_calendar ingest failed" >&2
  else
    echo "[close_pm] SKIP_CF=${SKIP_CF:-1}: skipped CF ingest (Tencent :8787/:8080 only)"
  fi
else
  echo "[warn] .ingest_token missing; skipped ingest" >&2
fi

echo "===== close_pm end $(date -Iseconds) ====="
