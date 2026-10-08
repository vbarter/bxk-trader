#!/bin/bash
# Stop only sequoia-x-web and snapshot live secret files before rsync.
# Paths and the unit name come from this repo (web/reseed-local-r2.sh,
# backend/scripts/run_*.sh). Do not stop any other unit.
set -euo pipefail

RUN_ID=${1:?run id}
if [[ ! "$RUN_ID" =~ ^[0-9]+-[0-9]+$ ]]; then
  echo "bad run id" >&2
  exit 1
fi

BACKEND=/root/dev/Sequoia-X
WEB=/root/dev/sequoia-x-web
STAGE=/root/.bxk-deploy-preserve/$RUN_ID

if [[ ! -d "$BACKEND" || ! -d "$WEB" ]]; then
  echo "live directories missing" >&2
  exit 1
fi
if ! command -v systemctl >/dev/null 2>&1; then
  echo "systemctl not found" >&2
  exit 1
fi

mkdir -p /root/.bxk-deploy-preserve
chmod 700 /root/.bxk-deploy-preserve
mkdir -p "$STAGE/backend" "$STAGE/web"
chmod 700 "$STAGE" "$STAGE/backend" "$STAGE/web"

preserve_root() {
  local root="$1"
  local dest="$2"
  local f base
  while IFS= read -r -d '' f; do
    base=$(basename -- "$f")
    if [[ "$base" == ".env.example" ]]; then
      continue
    fi
    cp -a -- "$f" "$dest/$base"
  done < <(find "$root" -mindepth 1 -maxdepth 1 -type f \( \
    -name '.env' -o -name '.env.*' -o \
    -name '.dev.vars' -o -name '.dev.vars*' -o \
    -name '.qbs.env' -o \
    -name '.ingest_token' -o -name 'INGEST_TOKEN.txt' -o \
    -name '*.pem' -o -name '*.key' -o -name '*.p12' -o -name '*.pfx' -o \
    -name 'id_rsa*' -o -name '*.secret' \
    \) -print0)
}

preserve_root "$BACKEND" "$STAGE/backend"
preserve_root "$WEB" "$STAGE/web"

# Marker first: if stop works and the SSH session then dies, finish still
# sees this file and starts the unit again.
touch "$STAGE/stopped"
if ! systemctl stop sequoia-x-web; then
  rm -rf "$STAGE"
  echo "systemctl stop sequoia-x-web failed" >&2
  exit 1
fi
