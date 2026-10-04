#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")/../deploy/aio"
[ -f .env ] || cp .env.example .env
echo "Review deploy/aio/.env and replace CHANGE_ME before starting."
docker compose up -d --build
