#!/bin/sh
# Hourly news scan — Asia/Shanghai (cron: 5 * * * *)
# Pull disclosure/news → data/news_events.json → local Tencent Worker (:8787 / :8080)
# CF frozen 2026-09-23 — Tencent-only. Reversible: SKIP_CF=0 to also push CF.
set -eu
cd /root/dev/Sequoia-X

export SKIP_CF="${SKIP_CF:-1}"

echo "===== news_hourly start $(date -Iseconds) ====="

SEED_FLAG=""
if [ "${1:-}" = "--seed" ]; then
  SEED_FLAG="--seed"
fi

if ! .venv/bin/python scripts/run_news_hourly.py $SEED_FLAG; then
  echo "[warn] news scan failed" >&2
  echo "===== news_hourly end $(date -Iseconds) ====="
  exit 1
fi

if [ -f .ingest_token ]; then
  INGEST_TOKEN=$(cat .ingest_token)
  # Local Tencent worker (:8787 behind nginx :8080) — primary
  SEQUOIA_X_WORKER_URL="${SEQUOIA_X_WORKER_URL_LOCAL:-${SEQUOIA_X_WORKER_URL:-http://127.0.0.1:8787}}" \
    INGEST_TOKEN="$INGEST_TOKEN" ./scripts/push-to-cf.sh news_events \
    || echo "[warn] local news_events ingest failed" >&2
  if [ "${SKIP_CF}" = "0" ]; then
    SEQUOIA_X_WORKER_URL="${SEQUOIA_X_WORKER_URL_CF:-https://sequoia-x-web.YOUR_SUBDOMAIN.workers.dev}" \
      INGEST_TOKEN="$INGEST_TOKEN" ./scripts/push-to-cf.sh news_events \
      || echo "[warn] CF news_events ingest failed" >&2
  else
    echo "[news_hourly] SKIP_CF=${SKIP_CF}: skipped CF ingest (Tencent :8787/:8080 only)"
  fi
else
  echo "[warn] .ingest_token missing; skipped ingest" >&2
fi

echo "===== news_hourly end $(date -Iseconds) ====="
