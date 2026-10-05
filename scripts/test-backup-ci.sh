#!/usr/bin/env bash
# Linux isolated runner only. PostgreSQL 17 is installed by the CI job.
set -euo pipefail
runtime=$(mktemp -d)
trap 'rm -rf "$runtime"' EXIT
curl --fail --location --silent --show-error -o "$runtime/weed.tar.gz" https://github.com/seaweedfs/seaweedfs/releases/download/4.48/linux_amd64.tar.gz
printf '%s  %s\n' 4a7d108384d044d95212d1342cdda9533fa55842c1c9b41f606ca3c8a9561124 "$runtime/weed.tar.gz" | sha256sum -c -
tar -xzf "$runtime/weed.tar.gz" -C "$runtime"
PG_BIN=/usr/lib/postgresql/17/bin WEED_BIN="$runtime/weed" python scripts/test-backup.py
