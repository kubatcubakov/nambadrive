#!/usr/bin/env bash
# Only ephemeral CI containers and generated test TLS. No identity/session credentials.
set -euo pipefail
runtime=$(mktemp -d)
network="nd-zap-${RANDOM}-${RANDOM}"
containers=()
cleanup() {
  for container in "${containers[@]}"; do docker rm -f "$container" >/dev/null 2>&1 || true; done
  docker network rm "$network" >/dev/null 2>&1 || true
  sudo rm -rf "$runtime"
}
trap cleanup EXIT
mkdir -p "$runtime/tls" "$runtime/audit" "$runtime/templates" acceptance-reports
openssl req -x509 -newkey rsa:2048 -sha256 -nodes -days 1 \
  -subj '/CN=edge' -addext 'subjectAltName=DNS:edge' \
  -keyout "$runtime/tls/server.key" -out "$runtime/tls/server.crt" >/dev/null 2>&1
cp deploy/common/nginx/app.conf.template "$runtime/templates/"
sudo chown -R 101:101 "$runtime/tls"
sudo chmod 700 "$runtime/tls"
sudo chmod 400 "$runtime/tls/server.key"
sudo chown 10001:10001 "$runtime/audit"
sudo chmod 750 "$runtime/audit"
# ZAP writes reports using its UID; these contain no real accounts or cookies.
sudo chown 1000:1000 acceptance-reports
sudo chmod 750 acceptance-reports
docker network create --internal "$network" >/dev/null
backend="$network-backend"
containers+=("$backend")
docker run -d --name "$backend" --network "$network" --network-alias backend \
  --read-only --cap-drop ALL --security-opt no-new-privileges --pids-limit 256 \
  --tmpfs /tmp:rw,noexec,nosuid,size=512m --memory 2g \
  -v "$runtime/audit:/var/log/nambadrive" \
  -e NAMBADRIVE_COOKIE_SECURE=true -e NAMBADRIVE_PUBLIC_URL=https://edge:8443 \
  nambadrive/backend:ci >/dev/null
frontend="$network-frontend"
containers+=("$frontend")
docker run -d --name "$frontend" --network "$network" --network-alias frontend \
  --read-only --cap-drop ALL --security-opt no-new-privileges --pids-limit 128 \
  --tmpfs /tmp:rw,noexec,nosuid,size=64m --memory 128m nambadrive/frontend:ci >/dev/null
edge="$network-edge"
containers+=("$edge")
docker run -d --name "$edge" --network "$network" --network-alias edge \
  --read-only --cap-drop ALL --security-opt no-new-privileges --pids-limit 128 \
  --tmpfs /tmp:rw,noexec,nosuid,size=64m \
  --tmpfs /etc/nginx/conf.d:rw,noexec,nosuid,uid=101,gid=101 \
  --tmpfs /var/cache/nginx:rw,noexec,nosuid,uid=101,gid=101 \
  --tmpfs /var/run:rw,noexec,nosuid,uid=101,gid=101 --memory 128m \
  -v "$runtime/tls:/tls:ro" -v "$runtime/templates:/etc/nginx/templates:ro" \
  -v "$PWD/deploy/common/nginx/proxy-private.conf:/etc/nginx/proxy-private.conf:ro" \
  -e APP_DOMAIN=edge -e OFFICE_DOMAIN=office.example.test \
  -e 'NGINX_ENVSUBST_FILTER=^(APP_DOMAIN|OFFICE_DOMAIN)$' nambadrive/gateway:ci >/dev/null
# Stock nginx.conf has a root-only PID path. The gateway profile supplies /var/run tmpfs.
for attempt in $(seq 1 60); do
  if docker exec "$edge" wget --no-check-certificate -qO- https://edge:8443/api/v1/health/live >/dev/null 2>&1; then break; fi
  sleep 1
done
docker exec "$edge" wget --no-check-certificate -qO- https://edge:8443/api/v1/health/live >/dev/null
set +e
docker run --rm --network "$network" --memory 2g --pids-limit 256 \
  -v "$PWD/acceptance-reports:/zap/wrk:rw" \
  ghcr.io/zaproxy/zaproxy:stable@sha256:781a2bdaea47324e7bab583e2263f21d257b0aee61ed51521a5be45f5f5081ef \
  zap-baseline.py -t https://edge:8443 -m 1 -T 5 -J zap.json -r zap.html -s
status=$?
set -e
sudo chown -R "$(id -u):$(id -g)" acceptance-reports
# 2 means passive WARN findings; the JSON severity gate below still rejects Medium/High.
# Tool/startup failures and configured FAIL are never accepted.
if [ "$status" -ne 0 ] && [ "$status" -ne 2 ]; then exit "$status"; fi
python scripts/acceptance/zap_gate.py
