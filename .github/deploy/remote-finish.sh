#!/bin/bash
# Restore snapshotted secret files, build, start sequoia-x-web.
# Backend is cron (.venv/bin/python), not a systemd unit: uv sync only.
# Never restart bxkuo@line-1, nats, or nginx. Never wrangler deploy.
set -euo pipefail

RUN_ID=${1:?run id}
MODE=${2:?ok or fail}
if [[ ! "$RUN_ID" =~ ^[0-9]+-[0-9]+$ ]]; then
  echo "bad run id" >&2
  exit 1
fi
if [[ "$MODE" != "ok" && "$MODE" != "fail" ]]; then
  echo "bad mode" >&2
  exit 1
fi

BACKEND=/root/dev/Sequoia-X
WEB=/root/dev/sequoia-x-web
STAGE=/root/.bxk-deploy-preserve/$RUN_ID

if [[ ! -d "$STAGE" || ! -f "$STAGE/stopped" ]]; then
  echo "sequoia-x-web was not stopped by this run"
  exit 0
fi

start_unit() {
  systemctl start sequoia-x-web
  systemctl is-active --quiet sequoia-x-web
}

# If build or verify fails, bring the unit back before exiting.
cleanup_start() {
  if [[ -f "$STAGE/stopped" ]]; then
    systemctl start sequoia-x-web || true
  fi
}
trap cleanup_start EXIT

restore_root() {
  local root="$1"
  local dest="$2"
  local f base
  while IFS= read -r -d '' f; do
    base=$(basename -- "$f")
    cp -a -- "$f" "$root/$base"
  done < <(find "$dest" -mindepth 1 -maxdepth 1 -type f -print0)
}

verify_root() {
  local label="$1"
  local root="$2"
  local dest="$3"
  local f base live
  while IFS= read -r -d '' f; do
    base=$(basename -- "$f")
    live="$root/$base"
    if [[ ! -f "$live" ]] || ! cmp -s -- "$f" "$live"; then
      echo "secret mismatch: ${label}/${base}" >&2
      return 1
    fi
    echo "preserved ${label}/${base}"
  done < <(find "$dest" -mindepth 1 -maxdepth 1 -type f -print0)
}

restore_root "$BACKEND" "$STAGE/backend"
restore_root "$WEB" "$STAGE/web"
verify_root backend "$BACKEND" "$STAGE/backend"
verify_root web "$WEB" "$STAGE/web"

if [[ "$MODE" == "fail" ]]; then
  echo "rsync did not finish; secret files restored, skipping build" >&2
  exit 1
fi

export PATH="/root/.local/bin:/usr/local/bin:${PATH:-/usr/bin:/bin}"
if ! command -v uv >/dev/null 2>&1; then
  echo "uv not found; backend build is uv sync" >&2
  exit 1
fi
(cd "$BACKEND" && uv sync --frozen)

export NVM_DIR=/root/.nvm
if [[ ! -s "$NVM_DIR/nvm.sh" ]]; then
  echo "nvm.sh missing" >&2
  exit 1
fi
set +u
set +e
# shellcheck disable=SC1091
. "$NVM_DIR/nvm.sh"
set -e
set -u
if ! command -v npm >/dev/null 2>&1; then
  echo "npm not on PATH after nvm" >&2
  exit 1
fi

cd "$WEB"
export CI=1
rolled_back=0
if [[ -d node_modules ]]; then
  rm -rf node_modules.bxk-prev
  mv node_modules node_modules.bxk-prev
  rolled_back=1
fi
if ! npm ci --no-audit --no-fund; then
  echo "npm ci failed" >&2
  rm -rf node_modules
  if [[ "$rolled_back" == "1" ]]; then
    mv node_modules.bxk-prev node_modules
  fi
  exit 1
fi
rm -rf node_modules.bxk-prev

trap - EXIT
rm -f "$STAGE/stopped"
start_unit
rm -rf "$STAGE"
echo "sequoia-x-web is active"
