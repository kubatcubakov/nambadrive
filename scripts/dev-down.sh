#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")/../deploy/aio"
docker compose down
