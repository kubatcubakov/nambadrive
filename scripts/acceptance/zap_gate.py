"""Fail closed on missing/malformed ZAP output or any Medium/High finding."""

import json
from pathlib import Path

report = json.loads(Path("acceptance-reports/zap.json").read_text())
sites = report.get("site")
if not isinstance(sites, list) or not sites:
    raise SystemExit("ZAP did not produce a scanned site")
alerts = [alert for site in sites for alert in site.get("alerts", [])]
for alert in alerts:
    print(
        json.dumps(
            {
                "rule": alert["pluginid"],
                "risk": alert["riskcode"],
                "name": alert["name"],
            }
        )
    )
if any(int(alert["riskcode"]) >= 2 for alert in alerts):
    raise SystemExit("ZAP Medium/High finding requires remediation")
print("ZAP unauthenticated HTTPS passive baseline passed; Low/Info remain visible")
