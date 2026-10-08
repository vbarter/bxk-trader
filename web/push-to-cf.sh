#!/usr/bin/env bash
set -euo pipefail

: "${INGEST_TOKEN:?Set INGEST_TOKEN before running this script}"

WORKER_URL="${SEQUOIA_X_WORKER_URL:-https://sequoia-x-web.YOUR_SUBDOMAIN.workers.dev}"
DATA_KIND="${1:-latest}"

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
  *)
    echo "Usage: $0 [latest|watch_calendar|news_events]" >&2
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
