#!/usr/bin/env bash
# Isolated CI integration runtime. Requires Python, curl, tar and installed test dependencies.
set -euo pipefail
runtime=$(mktemp -d)
server_pid=''
cleanup() {
  if [ -n "$server_pid" ]; then kill "$server_pid" 2>/dev/null || true; wait "$server_pid" 2>/dev/null || true; fi
  rm -rf "$runtime"
}
trap cleanup EXIT
curl --fail --location --silent --show-error -o "$runtime/weed.tar.gz" https://github.com/seaweedfs/seaweedfs/releases/download/4.48/linux_amd64.tar.gz
printf '%s  %s\n' 4a7d108384d044d95212d1342cdda9533fa55842c1c9b41f606ca3c8a9561124 "$runtime/weed.tar.gz" | sha256sum -c -
tar -xzf "$runtime/weed.tar.gz" -C "$runtime"
python - "$runtime" <<'PY'
import json,pathlib,secrets,sys
p=pathlib.Path(sys.argv[1])/'s3.json'
p.write_text(json.dumps({'identities':[{'name':'ci','credentials':[{'accessKey':secrets.token_hex(16),'secretKey':secrets.token_hex(32)}],'actions':['Admin','Read','Write','List','Tagging']}]}))
p.chmod(0o600)
PY
"$runtime/weed" server -dir="$runtime" -ip=127.0.0.1 -ip.bind=127.0.0.1 -master.port=19333 -master.port.grpc=29333 -volume.port=18080 -volume.port.grpc=28080 -filer -filer.port=18888 -filer.port.grpc=28888 -s3 -s3.port=18333 -s3.port.grpc=28333 -s3.port.iceberg=0 -s3.port.lance=0 -s3.config="$runtime/s3.json" -master.telemetry=false -master.volumeSizeLimitMB=32 -volume.max=4 > "$runtime/server.log" 2>&1 &
server_pid=$!
python - <<'PY'
import socket,time
for attempt in range(60):
    try:
        with socket.create_connection(('127.0.0.1',18333),timeout=1):break
    except OSError:time.sleep(1)
else:raise SystemExit('SeaweedFS failed to start')
PY
NAMBADRIVE_TEST_S3_CONFIG="$runtime/s3.json" python -m pytest -q backend/tests/test_storage_integration.py
