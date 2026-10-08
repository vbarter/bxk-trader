#!/bin/sh
# Manual full daily pipeline (main.py + export_details + local Worker latest/details).
#
# Cron note (2026-09): the weekday 19:15 crontab entry was REMOVED to avoid
# duplicate full scans. Automated scan+export now runs at Asia/Shanghai 15:05
# via ./scripts/run_close_pm.sh (also regenerates + pushes watch_calendar).
# AM settle (buy opens) is ./scripts/run_settle_am.sh at 09:35.
# This script remains for manual / ad-hoc runs. Feishu behavior unchanged.
#
# CF frozen 2026-09-23 — Tencent-only. Reversible: SKIP_CF=0 to also push CF.
set -eu
cd /root/dev/Sequoia-X

export SKIP_CF="${SKIP_CF:-1}"

.venv/bin/python main.py

if ! .venv/bin/python scripts/export_details.py; then
  echo "[warn] detail export partially failed" >&2
fi

if ! .venv/bin/python scripts/write_daily_picks.py; then
  echo "[warn] write_daily_picks failed" >&2
fi

if [ -f .ingest_token ]; then
  INGEST_TOKEN=$(cat .ingest_token)
  # Local Tencent worker (:8787 behind nginx :8080) — primary
  SEQUOIA_X_WORKER_URL="${SEQUOIA_X_WORKER_URL_LOCAL:-${SEQUOIA_X_WORKER_URL:-http://127.0.0.1:8787}}" \
    INGEST_TOKEN="$INGEST_TOKEN" ./scripts/push-to-cf.sh latest \
    || echo "[warn] local latest ingest failed" >&2
  SEQUOIA_X_WORKER_URL="${SEQUOIA_X_WORKER_URL_LOCAL:-${SEQUOIA_X_WORKER_URL:-http://127.0.0.1:8787}}" \
    INGEST_TOKEN="$INGEST_TOKEN" ./scripts/push-details-to-cf.sh \
    || echo "[warn] local detail ingest partially failed" >&2
  if [ "${SKIP_CF}" = "0" ]; then
    SEQUOIA_X_WORKER_URL="${SEQUOIA_X_WORKER_URL_CF:-https://sequoia-x-web.YOUR_SUBDOMAIN.workers.dev}" \
      INGEST_TOKEN="$INGEST_TOKEN" ./scripts/push-to-cf.sh latest \
      || echo "[warn] CF latest ingest failed" >&2
    SEQUOIA_X_WORKER_URL="${SEQUOIA_X_WORKER_URL_CF:-https://sequoia-x-web.YOUR_SUBDOMAIN.workers.dev}" \
      INGEST_TOKEN="$INGEST_TOKEN" ./scripts/push-details-to-cf.sh \
      || echo "[warn] CF detail ingest partially failed" >&2
  else
    echo "[run_daily] SKIP_CF=${SKIP_CF}: skipped CF ingest (Tencent :8787/:8080 only)"
  fi
else
  echo "[warn] .ingest_token missing; skipped ingest" >&2
fi

# Optional: watch calendar is owned by run_settle_am / run_close_pm crons.
# .venv/bin/python scripts/export_watch_calendar.py
# INGEST_TOKEN=$(cat .ingest_token) ./scripts/push-to-cf.sh watch_calendar
