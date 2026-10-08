#!/usr/bin/env bash
# Push JSON to Worker ingest API.
# Default target: local Tencent Worker (:8787). CF frozen 2026-09-23 (SKIP_CF=1).
# To hit CF: SKIP_CF=0 SEQUOIA_X_WORKER_URL=https://....workers.dev ./scripts/push-to-cf.sh ...
set -euo pipefail

: "${INGEST_TOKEN:?Set INGEST_TOKEN before running this script}"

WORKER_URL="${SEQUOIA_X_WORKER_URL:-http://127.0.0.1:8787}"
SKIP_CF="${SKIP_CF:-1}"
DATA_KIND="${1:-latest}"

# Safety: block accidental CF / workers.dev when freeze is on
if [ "${SKIP_CF}" = "1" ] && echo "${WORKER_URL}" | grep -Eqi 'workers\.dev|cloudflare'; then
  echo "[push-to-cf] SKIP_CF=1: refusing CF URL ${WORKER_URL} (frozen 2026-09-23, Tencent-only)" >&2
  exit 0
fi

case "${DATA_KIND}" in
  latest)
    DATA_FILE="/root/dev/Sequoia-X/data/latest.json"
    INGEST_PATH="/api/ingest"
    ;;
  watch_calendar)
    DATA_FILE="/root/dev/Sequoia-X/data/watch_calendar.json"
    INGEST_PATH="/api/ingest/watch_calendar"
    ;;
  news_events)
    DATA_FILE="/root/dev/Sequoia-X/data/news_events.json"
    INGEST_PATH="/api/ingest/news_events"
    ;;
  heatmap)
    DATA_FILE="/root/dev/Sequoia-X/data/heatmap.json"
    INGEST_PATH="/api/ingest/heatmap"
    ;;
  *)
    echo "Usage: $0 [latest|watch_calendar|news_events|heatmap]" >&2
    exit 2
    ;;
esac

[[ -r "${DATA_FILE}" ]] || { echo "Cannot read ${DATA_FILE}" >&2; exit 1; }

curl --fail-with-body --silent --show-error \
  --request PUT \
  --header "Authorization: Bearer ${INGEST_TOKEN}" \
  --header "Content-Type: application/json" \
  --data-binary "@${DATA_FILE}" \
  "${WORKER_URL%/}${INGEST_PATH}"
echo
