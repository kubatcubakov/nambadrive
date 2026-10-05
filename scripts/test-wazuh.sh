#!/usr/bin/env bash
# Disposable CI-only manager, no published ports or production agent enrollment.
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd)
name="nambadrive-wazuh-${RANDOM}"
trap 'docker rm -f "$name" >/dev/null 2>&1 || true' EXIT
docker run -d --name "$name" --network none --entrypoint /bin/bash wazuh/wazuh-manager:4.14.8 -lc 'sleep infinity' >/dev/null
docker cp "$root/deploy/wazuh/nambadrive_rules.xml" "$name:/var/ossec/etc/rules/nambadrive_rules.xml"
docker exec "$name" chown wazuh:wazuh /var/ossec/etc/rules/nambadrive_rules.xml
docker exec "$name" /var/ossec/bin/wazuh-control start
python3 "$root/scripts/wazuh_samples.py" | while IFS=$'\t' read -r rule level sample; do
  printf '%s\n' "$sample" | docker exec -i "$name" /var/ossec/bin/wazuh-logtest -U "$rule:$level:json"
done
