#!/bin/sh
# Settle AM — Asia/Shanghai 09:35 weekdays (cron: 35 9 * * 1-5)
#
# Open+5min settle for watch calendar (open→open cadence):
#   - skip non-trading days
#   - light-sync today's opens for watch symbols
#       * buy opens when buy_date=today (yesterday's R picks)
#       * sell opens when sell_date=today (R = day-before-yesterday) → settle
#   - regenerate data/watch_calendar.json (settle when both opens exist)
#   - push watch_calendar to local Tencent Worker (:8787 / nginx :8080)
#   - CF frozen 2026-09-23 (Tencent-only); no CF push here
# Does NOT run full strategy scan (that is run_close_pm.sh at 15:05).
# Feishu: not involved here.
#
# Log: /root/dev/Sequoia-X/log_settle_am.txt
set -eu
cd /root/dev/Sequoia-X

# multi_hit track removed 2026-09-28 (PM). Single switch to bring it back:
# MULTI_HIT_ENABLED=1 in .env (also restore web src/index.ts from
# index.ts.bak.pre_rm_multihit_20260928 for the UI). Default 0 = llm only.
if [ -z "${MULTI_HIT_ENABLED:-}" ] && [ -f .env ]; then
  MULTI_HIT_ENABLED="$(grep -E '^MULTI_HIT_ENABLED=' .env | tail -1 | cut -d= -f2 | tr -d '[:space:]"')"
fi
export MULTI_HIT_ENABLED="${MULTI_HIT_ENABLED:-0}"

echo "===== settle_am start $(date -Iseconds) ====="
echo "[settle_am] MULTI_HIT_ENABLED=${MULTI_HIT_ENABLED}"

if ! .venv/bin/python scripts/is_trading_day.py; then
  echo "[settle_am] skip: non-trading day"
  echo "===== settle_am end $(date -Iseconds) ====="
  exit 0
fi

# Refresh today's opens for recent daily_picks (+ Theo fallback).
# Exit 2 = no bars yet → still try calendar regen (may stay pending).
sync_rc=0
.venv/bin/python scripts/sync_watch_today.py || sync_rc=$?
if [ "$sync_rc" -ne 0 ] && [ "$sync_rc" -ne 2 ]; then
  echo "[warn] sync_watch_today failed rc=$sync_rc" >&2
fi

.venv/bin/python scripts/export_watch_calendar.py

# Finalize calendar payload (pick_source; multi_hit track only if MULTI_HIT_ENABLED=1).
if ! .venv/bin/python scripts/build_dual_track_calendar.py; then
  echo "[warn] build_dual_track_calendar failed" >&2
  .venv/bin/python scripts/dual_basis.py || echo "[warn] dual_basis fallback failed" >&2
elif [ -f scripts/patch_calendar_pick_source.py ]; then
  if ! .venv/bin/python scripts/patch_calendar_pick_source.py; then
    echo "[warn] patch_calendar_pick_source failed" >&2
  fi
fi

if [ -f .ingest_token ]; then
  INGEST_TOKEN=$(cat .ingest_token)
  # Local Tencent worker (:8787 behind nginx :8080) — primary (matches cron SEQUOIA_X_WORKER_URL)
  SEQUOIA_X_WORKER_URL="${SEQUOIA_X_WORKER_URL_LOCAL:-${SEQUOIA_X_WORKER_URL:-http://127.0.0.1:8787}}" \
    INGEST_TOKEN="$INGEST_TOKEN" ./scripts/push-to-cf.sh watch_calendar \
    || echo "[warn] local watch_calendar ingest failed" >&2
else
  echo "[warn] .ingest_token missing; skipped ingest" >&2
fi

echo "===== settle_am end $(date -Iseconds) ====="
