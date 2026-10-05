"""Fail closed on missing/malformed ZAP output or any Medium/High finding."""

import json
from pathlib import Path


def validate_report(report):
    sites = report.get("site")
    if not isinstance(sites, list) or not sites:
        raise ValueError("ZAP did not produce a scanned site")
    alerts = []
    for site in sites:
        if (
            site.get("@name") != "https://edge:8443"
            or site.get("@ssl") != "true"
            or not isinstance(site.get("alerts"), list)
        ):
            raise ValueError("ZAP report must describe the expected HTTPS site")
        for alert in site["alerts"]:
            if (
                str(alert.get("riskcode")) not in {"0", "1", "2", "3"}
                or not isinstance(alert.get("name"), str)
                or "pluginid" not in alert
            ):
                raise ValueError("Malformed ZAP alert")
            alerts.append(alert)
    return alerts


def main():
    report = json.loads(Path("acceptance-reports/zap.json").read_text())
    alerts = validate_report(report)
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


if __name__ == "__main__":
    main()
