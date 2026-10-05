"""Actual container SCA gate on a disposable CI runner; no production runtime."""

import json
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[2]
images = json.loads((root / "deploy/common/images.lock.json").read_text())
scanner = images.pop("trivy")
# Scan the actual deployed derivatives including their inherited base files, not unused
# upstream images which the profile no longer runs (patched gateway and UID-drop helper).
images.pop("nginx")
images.pop("postgres")
images.pop("redis")
images.pop("opensearch")
reports = root / "container-reports"
reports.mkdir(exist_ok=True)
# Caller builds the application/runtime derivatives before scanning them.
images.update(
    gateway="nambadrive/gateway:ci",
    redis="nambadrive/redis:ci",
    opensearch="nambadrive/opensearch:ci",
    backend="nambadrive/backend:ci",
    frontend="nambadrive/frontend:ci",
    tika="nambadrive/tika:ci",
    database="nambadrive/postgres:ci",
    office="nambadrive/office:ci",
)
failed = False
for name, image in images.items():
    if name in {"python", "node", "java"}:
        continue  # Included and scanned inside built application images.
    subprocess.run(["docker", "pull", image], check=True) if not image.startswith(
        "nambadrive/"
    ) else None
    result = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "-v",
            "/var/run/docker.sock:/var/run/docker.sock:ro",
            "-v",
            str(reports) + ":/reports",
            "-v",
            "nd-trivy-cache:/root/.cache/",
            scanner,
            "image",
            "--scanners",
            "vuln",
            "--severity",
            "CRITICAL,HIGH",
            "--format",
            "json",
            "--output",
            "/reports/" + name + ".json",
            "--exit-code",
            "0",
            image,
        ],
        check=False,
    )
    if result.returncode:
        failed = True
        continue
    report = json.loads((reports / (name + ".json")).read_text())
    critical = [
        v
        for r in report.get("Results", [])
        for v in r.get("Vulnerabilities", [])
        if v["Severity"] == "CRITICAL"
    ]
    high = [
        v
        for r in report.get("Results", [])
        for v in r.get("Vulnerabilities", [])
        if v["Severity"] == "HIGH"
    ]
    print(
        json.dumps(
            {
                "image": name,
                "critical": len(critical),
                "high_review_required": len(high),
            }
        )
    )
    for finding in critical + high:
        print(
            json.dumps(
                {
                    "image": name,
                    "severity": finding["Severity"],
                    "vulnerability": finding["VulnerabilityID"],
                    "package": finding["PkgName"],
                    "installed": finding["InstalledVersion"],
                    "fixed": finding.get("FixedVersion", ""),
                    "title": finding.get("Title", ""),
                }
            )
        )
    failed = failed or bool(critical)
    # Vendor High findings remain visible artifacts; authorization bypasses cannot be accepted.
if failed:
    raise SystemExit("Container scan failed or unresolved Critical vulnerability")
