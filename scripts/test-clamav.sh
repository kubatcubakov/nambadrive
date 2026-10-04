#!/usr/bin/env bash
# Deterministic real-engine CI test using an isolated EICAR test signature.
# Production requires freshclam's official databases, never this test database.
set -euo pipefail
runtime=$(mktemp -d)
server_pid=''
cleanup() {
  if [ -n "$server_pid" ]; then kill "$server_pid" 2>/dev/null || true; wait "$server_pid" 2>/dev/null || true; fi
  rm -rf "$runtime"
}
trap cleanup EXIT
printf '%s\n' '44d88612fea8a8f36de82e1278abb02f:68:NambaDrive.Test.EICAR' > "$runtime/test.hdb"
sed -e "s|DatabaseDirectory /var/lib/clamav|DatabaseDirectory $runtime|" -e 's/TCPSocket 3310/TCPSocket 13310/' -e 's/TCPAddr 0.0.0.0/TCPAddr 127.0.0.1/' -e "s/User clamav/User $(id -un)/" deploy/aio/clamav/clamd.conf > "$runtime/clamd.conf"
clamd --config-file="$runtime/clamd.conf" > "$runtime/server.log" 2>&1 &
server_pid=$!
python - <<'PY'
import socket,time
for attempt in range(60):
    try:
        with socket.create_connection(('127.0.0.1',13310),timeout=1):break
    except OSError:time.sleep(1)
else:raise SystemExit('ClamAV failed to start')
PY
NAMBADRIVE_TEST_CLAMAV=1 python -m pytest -q backend/tests/test_clamav_integration.py
