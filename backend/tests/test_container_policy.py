"""Release trust-bypass findings must block even when Critical count is zero."""

import importlib.util
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "container_gate", Path(__file__).resolve().parents[2] / "scripts/deploy/scan_containers.py"
)
assert _spec and _spec.loader
_gate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_gate)


@pytest.mark.parametrize(
    "title",
    [
        "Eclipse Jetty: Authentication bypass via Digest authentication encoding collision",
        "curl: Public key pinning bypass allows unauthenticated connections",
        "Service: authorization bypass through resource identifier",
    ],
)
def test_high_trust_bypass_cannot_pass_release_gate(title):
    assert _gate.has_high_authorization_bypass([{"Title": title}])


def test_other_high_findings_remain_reviewable_without_becoming_authentication_grants():
    assert not _gate.has_high_authorization_bypass(
        [
            {"Title": "Jackson: Denial of Service via regular expression backtracking"},
            {"Title": "util-linux: Local mount namespace privilege escalation"},
        ]
    )
