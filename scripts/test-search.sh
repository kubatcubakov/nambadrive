#!/usr/bin/env bash
# Disposable CI engines only; never reuse production data or expose ports publicly.
set -euo pipefail
runtime=$(mktemp -d)
search_container="nd-search-ci-${RANDOM}-${RANDOM}"
tika_pid=''
cleanup() {
  if [ -n "$tika_pid" ]; then kill "$tika_pid" 2>/dev/null || true; fi
  docker rm -f "$search_container" >/dev/null 2>&1 || true
  rm -rf "$runtime"
}
trap cleanup EXIT
curl -fsSL --retry 3 https://downloads.apache.org/tika/4.1.0/tika-server-standard-4.1.0.zip -o "$runtime/tika.zip"
printf '%s  %s\n' c932f84c569fb02df4f72ab060d6f2cf77b6797417040202401bc256e18a8f6f0ebc25d12d6dce222cb9328abfcb388cfa6511d7382c765a45687240a8a4bd7e "$runtime/tika.zip" | sha512sum -c -
unzip -q "$runtime/tika.zip" -d "$runtime/tika"
java -jar "$runtime/tika/tika-server-standard-4.1.0.jar" --config deploy/common/tika/config.json --host 127.0.0.1 --port 19998 >"$runtime/tika.log" 2>&1 &
tika_pid=$!
# Security plugin disabled ONLY in this isolated, data-free engine contract test.
# App-level ACL checks are tested below; production TLS/auth are separate hardening gates.
docker run -d --name "$search_container" -p 127.0.0.1:19200:9200 \
  -e discovery.type=single-node -e DISABLE_SECURITY_PLUGIN=true \
  -e DISABLE_INSTALL_DEMO_CONFIG=true -e OPENSEARCH_JAVA_OPTS='-Xms512m -Xmx512m' \
  opensearchproject/opensearch:3.9.0 >/dev/null
for attempt in $(seq 1 90); do
  if curl -fsS http://127.0.0.1:19200 >/dev/null && curl -fsS http://127.0.0.1:19998/tika >/dev/null; then break; fi
  sleep 2
done
curl -fsS http://127.0.0.1:19200 >/dev/null
curl -fsS http://127.0.0.1:19998/tika >/dev/null
NAMBADRIVE_TEST_TIKA_URL=http://127.0.0.1:19998 \
NAMBADRIVE_TEST_OPENSEARCH_URL=http://127.0.0.1:19200 \
python -m pytest -q backend/tests/test_search_integration.py
