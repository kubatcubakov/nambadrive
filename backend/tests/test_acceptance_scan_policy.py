"""An absent/wrong-site/malformed report is not evidence that a scan passed."""

import importlib.util
import json
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "zap_gate", Path(__file__).resolve().parents[2] / "scripts/acceptance/zap_gate.py"
)
assert _spec and _spec.loader
_gate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_gate)


def report(alerts):
    return {"site": [{"@name": "https://edge:8443", "@ssl": "true", "alerts": alerts}]}


@pytest.mark.parametrize(
    "value",
    [
        {},
        {"site": []},
        {"site": [{}]},
        {"site": [{"@name": "https://other:8443", "@ssl": "true", "alerts": []}]},
        {"site": [{"@name": "https://edge:8443", "@ssl": "false", "alerts": []}]},
        report([{"pluginid": "test", "name": "Unknown risk", "riskcode": "unknown"}]),
    ],
)
def test_incomplete_or_wrong_site_scan_cannot_pass(value):
    with pytest.raises(ValueError):
        _gate.validate_report(value)


@pytest.mark.parametrize("risk", ["2", "3"])
def test_medium_or_high_zap_finding_blocks_acceptance(tmp_path, monkeypatch, risk):
    monkeypatch.chdir(tmp_path)
    directory = tmp_path / "acceptance-reports"
    directory.mkdir()
    (directory / "zap.json").write_text(
        json.dumps(report([{"pluginid": "test", "name": "Security finding", "riskcode": risk}]))
    )
    with pytest.raises(SystemExit):
        _gate.main()


def test_low_visible_report_and_clean_report_are_accepted(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    directory = tmp_path / "acceptance-reports"
    directory.mkdir()
    for alerts in ([], [{"pluginid": "test", "name": "Low finding", "riskcode": "1"}]):
        (directory / "zap.json").write_text(json.dumps(report(alerts)))
        _gate.main()
    assert "Low finding" in capsys.readouterr().out
