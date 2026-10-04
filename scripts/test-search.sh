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
curl -fsSL --retry 3 https://downloads.apache.org/tika/3.3.2/tika-server-standard-3.3.2.jar -o "$runtime/tika.jar"
printf '%s  %s\n' fb1f2fe57ac458b09d44d41d816f582e1d2fc93488acff6275caf414d8d5ef94e42166edc0b488dc2fb6ef3aa21fab62b107c43b9060385ff6d675e393c2c9e9 "$runtime/tika.jar" | sha512sum -c -
java -jar "$runtime/tika.jar" --host 127.0.0.1 --port 19998 >"$runtime/tika.log" 2>&1 &
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
