#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "$0")" && pwd)"
cd "$root"

tmp="$(mktemp)"
trap 'rm -f "$tmp" "$tmp.tar.gz"' EXIT

cat handoff/part_*.b64 > "$tmp"
base64 -d "$tmp" > "$tmp.tar.gz"

expected="f9f8859d5a404599b04945cd9a1d1f77b8bc85cd688e7849f10995cf23f1c5c8"
actual="$(sha256sum "$tmp.tar.gz" | awk '{print $1}')"

if [[ "$actual" != "$expected" ]]; then
  echo "Checksum mismatch: $actual" >&2
  exit 1
fi

tar -xzf "$tmp.tar.gz" -C "$root"
echo "NambaDrive handoff unpacked successfully."
echo "Read AGENTS.md and START_HERE_CODEX.md, then continue from Phase 2."
