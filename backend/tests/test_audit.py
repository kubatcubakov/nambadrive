import asyncio
import json
import subprocess
import sys
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import select

from app.audit.context import audit_context
from app.audit.writer import append_durable, write_audit_event
from app.authorization.administration import ACLAdministrationService
from app.governance.service import GovernanceService
from app.models.acl import ACLEntry, BreakGlassGrant
from app.models.governance import LegalHoldEvent, RetentionPolicy
from tests.test_documents import api as api_fixture
from tests.test_documents import clean as clean_fixture
from tests.test_documents import scene as scene_fixture
from tests.test_governance import admin as admin_fixture

api, clean, scene, admin = api_fixture, clean_fixture, scene_fixture, admin_fixture


async def test_schema_and_nested_secret_redaction(tmp_path):
    token = audit_context.set(
        {
            "user": "actor",
            "ip": "192.0.2.1",
            "user_agent": "browser",
            "correlation_id": str(uuid.uuid4()),
        }
    )
    try:
        await write_audit_event(
            "change_acl",
            resource="resource",
            result="success",
            old_acl=None,
            new_acl={"permission": "VIEW", "password": "SECRET"},
            access_token="SECRET",
            reason='newline\nquoted"',
        )
    finally:
        audit_context.reset(token)
    raw = (tmp_path / "audit.jsonl").read_text()
    assert len(raw.splitlines()) == 1 and "SECRET" not in raw
    event = json.loads(raw)
    assert event["application"] == "nambadrive" and event["schema_version"] == 1
    assert event["user"] == "actor" and event["ip"] == "192.0.2.1"
    assert event["new_acl"]["password"] == "[REDACTED]"
    assert {
        "timestamp",
        "event_id",
        "correlation_id",
        "user_agent",
        "resource",
        "result",
    } <= event.keys()
    assert (tmp_path / "audit.jsonl").stat().st_mode & 0o027 == 0


async def test_worker_context_and_reserved_envelope(tmp_path):
    await write_audit_event("malware_detected", user="actor", resource="document", result="blocked")
    event = json.loads((tmp_path / "audit.jsonl").read_text())
    assert event["user_agent"] == "nambadrive-worker" and event["ip"] is None
    uuid.UUID(event["correlation_id"])
    with pytest.raises(ValueError):
        await write_audit_event("view", timestamp="spoof")


async def test_cross_request_context_isolation(tmp_path):
    async def emit(identity):
        token = audit_context.set({"user": identity})
        try:
            await asyncio.sleep(0)
            await write_audit_event("view")
        finally:
            audit_context.reset(token)

    await asyncio.gather(*(emit(str(i)) for i in range(20)))
    events = [json.loads(line) for line in (tmp_path / "audit.jsonl").read_text().splitlines()]
    assert {row["user"] for row in events} == {str(i) for i in range(20)}


def test_concurrent_processes_preserve_large_jsonl_records(tmp_path):
    destination = tmp_path / "multi.jsonl"
    code = """import json,sys
from pathlib import Path
from app.audit.writer import append_durable
for i in range(15):
 record=json.dumps({'worker':sys.argv[2],'i':i,'payload':'x'*32000})+'\\n'
 append_durable(Path(sys.argv[1]),record.encode())
"""
    processes = [
        subprocess.Popen([sys.executable, "-c", code, str(destination), str(i)]) for i in range(3)
    ]
    assert all(process.wait(timeout=30) == 0 for process in processes)
    events = [json.loads(line) for line in destination.read_text().splitlines()]
    assert len(events) == 45 and len({(r["worker"], r["i"]) for r in events}) == 45


def test_symlinks_insecure_modes_and_partial_segments_fail_closed(tmp_path):
    target = tmp_path / "target"
    target.write_text("unchanged")
    link = tmp_path / "link"
    link.symlink_to(target)
    with pytest.raises(OSError):
        append_durable(link, b"{}\n")
    assert target.read_text() == "unchanged"
    insecure = tmp_path / "insecure"
    insecure.touch(mode=0o666)
    insecure.chmod(0o666)
    with pytest.raises(OSError):
        append_durable(insecure, b"{}\n")
    partial = tmp_path / "partial"
    partial.write_bytes(b'{"incomplete":')
    partial.chmod(0o640)
    with pytest.raises(OSError):
        append_durable(partial, b"{}\n")
    assert partial.read_bytes() == b'{"incomplete":'


async def test_http_denial_has_route_context_without_query_or_secret(api, tmp_path):
    client, _ = api
    response = await client.get(
        "/api/v1/admin/governance/policies?token=DO_NOT_LOG",
        headers={"User-Agent": "audit-test", "X-Correlation-ID": str(uuid.uuid4())},
    )
    assert response.status_code == 403
    raw = (tmp_path / "audit.jsonl").read_text()
    assert "DO_NOT_LOG" not in raw
    event = json.loads(raw.splitlines()[-1])
    assert event["event_type"] == "access_denied" and event["result"] == "denied"
    assert event["correlation_id"] == response.headers["X-Correlation-ID"]
    assert event["user_agent"] == "audit-test" and event["route"].endswith(
        "/admin/governance/policies"
    )


@pytest.mark.parametrize("operation", ["acl", "hold", "retention", "breakglass", "manager"])
async def test_real_fsync_failure_prevents_critical_commit(db, scene, clean, admin, operation):
    document = clean[0]
    with patch("app.audit.writer.os.fsync", side_effect=OSError("audit disk unavailable")):
        with pytest.raises(OSError):
            if operation == "acl":
                from datetime import UTC, datetime

                await ACLAdministrationService(db, scene[0], {}).grant(
                    document.id,
                    "USER",
                    scene[1].id,
                    "VIEW",
                    "ALLOW",
                    True,
                    False,
                    "test",
                    datetime.now(UTC),
                    None,
                )
            elif operation == "hold":
                await GovernanceService(db, admin, {}).hold(document.id, True, "test")
            elif operation == "retention":
                await GovernanceService(db, admin, {}).create_policy(
                    "test", document.id, None, 30, "test"
                )
            elif operation == "manager":
                from app.departments.service import OrganizationService

                await OrganizationService(db, admin, {}).assign(scene[5].id, scene[1].id, "MANAGER")
            else:
                await ACLAdministrationService(db, admin, {}).break_glass(
                    document.id, "VIEW", "test", 30
                )
    await db.rollback()
    if operation == "acl":
        assert not (await db.scalars(select(ACLEntry))).all()
    elif operation == "hold":
        assert not (await db.scalars(select(LegalHoldEvent))).all()
    elif operation == "retention":
        assert not (await db.scalars(select(RetentionPolicy))).all()
    elif operation == "manager":
        from app.models.organization import DepartmentManager

        assert not (await db.scalars(select(DepartmentManager))).all()
    else:
        assert not (await db.scalars(select(BreakGlassGrant))).all()


async def test_http_audit_failure_returns_unavailable(api):
    client, _ = api
    with patch("app.audit.writer.os.fsync", side_effect=OSError("disk full")):
        assert (await client.get("/api/v1/admin/governance/policies")).status_code == 503


def test_wazuh_rules_and_agent_collection_contract():
    from defusedxml.ElementTree import fromstring

    root = Path(__file__).resolve().parents[2]
    rules = fromstring((root / "deploy/wazuh/nambadrive_rules.xml").read_text())
    ids = [rule.attrib["id"] for rule in rules.findall("rule")]
    assert len(ids) == len(set(ids))
    assert all(100000 <= int(rule) <= 120000 for rule in ids)
    assert rules.find("rule[@id='110001']").attrib["level"] == "12"
    config = fromstring((root / "deploy/wazuh/agent.conf").read_text())
    assert config.find("localfile/log_format").text == "json"
