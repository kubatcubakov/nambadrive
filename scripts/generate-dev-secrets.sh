#!/usr/bin/env sh
set -eu

if ! command -v openssl >/dev/null 2>&1; then
  echo "openssl is required" >&2
  exit 1
fi

printf 'POSTGRES_PASSWORD=%s\n' "$(openssl rand -base64 32 | tr -d '\n')"
printf 'NAMBADRIVE_CSRF_SECRET=%s\n' "$(openssl rand -hex 32)"
