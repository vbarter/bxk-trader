#!/usr/bin/env bash
# Push detail JSON files to Worker.
# Default target: local Tencent Worker (:8787). CF frozen 2026-09-23 (SKIP_CF=1).
set -euo pipefail

: "${INGEST_TOKEN:?Set INGEST_TOKEN before running this script}"

WORKER_URL="${SEQUOIA_X_WORKER_URL:-http://127.0.0.1:8787}"
SKIP_CF="${SKIP_CF:-1}"
DETAILS_DIR="/root/dev/Sequoia-X/data/details"

if [ "${SKIP_CF}" = "1" ] && echo "${WORKER_URL}" | grep -Eqi 'workers\.dev|cloudflare'; then
  echo "[push-details] SKIP_CF=1: refusing CF URL ${WORKER_URL} (frozen 2026-09-23, Tencent-only)" >&2
  exit 0
fi

shopt -s nullglob
files=("${DETAILS_DIR}"/*.json)
if (( ${#files[@]} == 0 )); then
  echo "[warn] no detail files found in ${DETAILS_DIR}" >&2
  exit 1
fi

failed=0
uploaded=0
for file in "${files[@]}"; do
  code="$(basename "${file}" .json)"
  if curl --fail-with-body --silent --show-error \
    --request PUT \
    --header "Authorization: Bearer ${INGEST_TOKEN}" \
    --header "Content-Type: application/json" \
    --data-binary "@${file}" \
    "${WORKER_URL%/}/api/details/${code}" >/dev/null; then
    ((uploaded += 1))
  else
    echo "[warn] failed to upload ${code}" >&2
    ((failed += 1))
  fi
  if (( uploaded % 25 == 0 && uploaded > 0 )); then
    echo "Uploaded ${uploaded}/${#files[@]} detail files"
  fi
done

echo "Uploaded ${uploaded}/${#files[@]} detail files; failed=${failed}"
(( failed == 0 ))
