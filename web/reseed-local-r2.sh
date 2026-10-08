#!/usr/bin/env bash
set -euo pipefail
export NVM_DIR=/root/.nvm
. "$NVM_DIR/nvm.sh"
cd /root/dev/sequoia-x-web
systemctl stop sequoia-x-web || true
node bulk-seed-r2.mjs
rm -rf .wrangler/state/v3/r2
mkdir -p .wrangler/state/v3
cp -a .wrangler/state/r2 .wrangler/state/v3/r2
systemctl start sequoia-x-web
echo reseeded
