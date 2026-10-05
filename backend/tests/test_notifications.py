import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest
from fastapi import HTTPException
from pydantic import SecretStr
from sqlalchemy import select

from app.auth.dependencies import require_csrf
from app.core.config import Settings
from app.main import app
from app.models.access_request import AccessRequest
from app.models.acl import RoleBinding
from app.models.notification import (
    Notification,
    NotificationDelivery,
    NotificationPreference,
    NotificationSource,
)
from app.models.quota import QuotaIncident
from app.notifications.delivery import (
    DeliveryUnavailable,
    DeliveryWorker,
    send_email,
    send_telegram,
)
from app.notifications.service import NotificationService
from tests.test_documents import api as api_fixture
from tests.test_documents import clean as clean_fixture
from tests.test_documents import scene as scene_fixture
from tests.test_governance import admin as admin_fixture

api, clean, scene, admin = api_fixture, clean_fixture, scene_fixture, admin_fixture


@pytest.fixture
async def notices(db, scene, clean, admin):
    row, _, _ = clean
    db.add(
        QuotaIncident(
            actor_id=scene[0].id,
            resource_id=row.id,
            subject_type="USER",
            subject_id=scene[0].id,
            limit_bytes=5,
            requested_bytes=1,
        )
    )
    await db.commit()
    await NotificationService(db).collect()
    return (await db.scalars(select(Notification).order_by(Notification.admin_only))).all()


async def test_quota_fanout_once_and_no_content_disclosure(db, scene, clean, admin, notices):
    assert len(notices) == 2
    assert await NotificationService(db).collect() == 0
    assert len((await db.scalars(select(NotificationDelivery))).all()) == 3
    own = await NotificationService(db).list(scene[0])
    alerts = await NotificationService(db).list(admin)
    assert own[0]["resource_id"] == clean[0].id
    assert alerts[0]["resource_id"] is None
    assert clean[0].name not in str(alerts)
    assert await NotificationService(db).list(scene[1]) == []


async def test_read_and_preferences_idor_csrf(api, db, scene, notices):
    client, state = api
    state["actor"] = scene[0]
    own = next(n for n in notices if n.user_id == scene[0].id)
    path = f"/api/v1/notifications/{own.id}/read"
    assert (await client.post(path)).status_code == 403
    app.dependency_overrides[require_csrf] = lambda: None
    state["actor"] = scene[1]
    assert (await client.post(path)).status_code == 403
    state["actor"] = scene[0]
    assert (await client.post(path)).status_code == 200
    assert (await client.get("/api/v1/notifications")).headers["Cache-Control"] == "no-store"
    assert (
        await client.put("/api/v1/notifications/preferences", json={"email_enabled": False})
    ).status_code == 200
    assert not (await client.get("/api/v1/notifications/preferences")).json()["data"][
        "email_enabled"
    ]
    assert await db.get(NotificationPreference, scene[1].id) is None


async def test_disabled_user_cannot_read(db, scene, notices):
    scene[0].enabled = False
    await db.commit()
    with pytest.raises(HTTPException):
        await NotificationService(db).list(scene[0])


async def test_new_access_request_notifies_only_current_approvers(db, scene, clean, admin):
    db.add(
        AccessRequest(
            resource_id=clean[0].id,
            requested_by=scene[1].id,
            permission_id="VIEW",
            reason="request",
        )
    )
    await db.commit()
    await NotificationService(db).collect()
    rows = (await db.scalars(select(Notification))).all()
    assert any(row.user_id == scene[0].id for row in rows)
    assert not any(row.user_id in {scene[1].id, admin.id} for row in rows)
    request = await db.scalar(select(AccessRequest))
    request.status, request.decided_at, request.decided_by = (
        "DENIED",
        datetime.now(UTC),
        scene[0].id,
    )
    await db.commit()
    await NotificationService(db).collect()
    assert (await NotificationService(db).list(scene[1]))[0]["kind"] == "ACCESS_DECIDED"


async def test_rolled_back_source_does_not_notify(db, scene, clean, admin):
    db.add(
        AccessRequest(
            resource_id=clean[0].id,
            requested_by=scene[1].id,
            permission_id="VIEW",
            reason="rolled back",
        )
    )
    await db.flush()
    await db.rollback()
    await NotificationService(db).collect()
    assert not (await db.scalars(select(Notification))).all()


async def test_failed_document_quota_incident_has_no_broken_resource_link(db, scene, admin):
    db.add(
        QuotaIncident(
            actor_id=scene[0].id,
            resource_id=uuid.uuid4(),
            subject_type="USER",
            subject_id=scene[0].id,
            limit_bytes=0,
            requested_bytes=1,
        )
    )
    await db.commit()
    await NotificationService(db).collect()
    assert all(row.resource_id is None for row in (await db.scalars(select(Notification))).all())


@pytest.mark.parametrize("failure", ["disabled", "revoked_admin", "opt_out"])
async def test_delivery_rechecks_recipient_and_preferences(db, scene, admin, notices, failure):
    target = admin if failure == "revoked_admin" else scene[0]
    if failure == "disabled":
        target.enabled = False
    elif failure == "revoked_admin":
        for binding in (
            await db.scalars(select(RoleBinding).where(RoleBinding.user_id == admin.id))
        ).all():
            binding.revoked_at = datetime.now(UTC)
    else:
        db.add(NotificationPreference(user_id=target.id, email_enabled=False))
    target_notice = next(n for n in notices if n.user_id == target.id)
    deliveries = (await db.scalars(select(NotificationDelivery))).all()
    for row in deliveries:
        row.next_attempt_at = datetime.now(UTC) + timedelta(days=1)
    delivery = next(
        d for d in deliveries if d.notification_id == target_notice.id and d.channel == "EMAIL"
    )
    delivery.next_attempt_at = datetime.now(UTC) - timedelta(seconds=1)
    await db.commit()
    with patch("app.notifications.delivery.send_email") as sender:
        assert await DeliveryWorker(db, Settings()).process_one()
        sender.assert_not_called()
    assert delivery.status == "SUPPRESSED"


async def test_unavailable_delivery_retries_without_exception_secrets(db, scene, notices):
    scene[0].email = "user@example.test"
    delivery = await db.scalar(
        select(NotificationDelivery)
        .join(Notification)
        .where(Notification.user_id == scene[0].id, NotificationDelivery.channel == "EMAIL")
    )
    for row in (await db.scalars(select(NotificationDelivery))).all():
        row.next_attempt_at = datetime.now(UTC) + timedelta(days=1)
    delivery.next_attempt_at = datetime.now(UTC) - timedelta(seconds=1)
    await db.commit()
    with patch("app.notifications.delivery.send_email", side_effect=OSError("SECRET")):
        assert await DeliveryWorker(db, Settings()).process_one()
    assert delivery.attempts == 1 and delivery.status == "PENDING" and delivery.sent_at is None
    delivery.next_attempt_at = datetime.now(UTC) - timedelta(seconds=1)
    await db.commit()
    with patch("app.notifications.delivery.send_email") as send:
        await DeliveryWorker(db, Settings()).process_one()
        send.assert_called_once()
    assert delivery.status == "SENT"


def test_email_tls_and_generic_payload():
    settings = Settings(smtp_host="smtp.example.test", smtp_from="drive@example.test")
    with patch("smtplib.SMTP_SSL") as smtp:
        send_email(settings, "user@example.test", str(uuid.uuid4()))
        context = smtp.call_args.kwargs["context"]
        assert context.check_hostname and context.verify_mode == 2
        message = smtp.return_value.__enter__.return_value.send_message.call_args.args[0]
        assert "document" not in str(message).lower()
        assert "href" not in str(message)
    with pytest.raises(DeliveryUnavailable):
        send_email(settings, "user@example.test\r\nBcc: other@example.test", str(uuid.uuid4()))


async def test_telegram_fixed_origin_no_redirects_and_no_secret_errors():
    settings = Settings(
        telegram_bot_token=SecretStr("123:" + "a" * 32), telegram_admin_chat_id=SecretStr("-1234")
    )
    client = AsyncMock()
    client.post.return_value = Mock(status_code=200, json=lambda: {"ok": True})
    with patch("httpx.AsyncClient") as factory:
        factory.return_value.__aenter__.return_value = client
        await send_telegram(settings, "MALWARE")
        assert factory.call_args.kwargs["follow_redirects"] is False
        assert factory.call_args.kwargs["trust_env"] is False
        assert client.post.call_args.args[0].startswith("https://api.telegram.org/bot")
        assert set(client.post.call_args.kwargs["json"]) == {"chat_id", "text"}
        client.post.side_effect = httpx.ConnectError("secret token")
        with pytest.raises(DeliveryUnavailable) as error:
            await send_telegram(settings, "MALWARE")
        assert "secret" not in str(error.value)


async def test_fanout_and_receipt_rollback_together(db, scene, clean, admin):
    db.add(
        QuotaIncident(
            actor_id=scene[0].id,
            resource_id=clean[0].id,
            subject_type="USER",
            subject_id=scene[0].id,
            limit_bytes=1,
            requested_bytes=1,
        )
    )
    await db.commit()
    with patch.object(db, "commit", new=AsyncMock(side_effect=OSError("commit unavailable"))):
        with pytest.raises(OSError):
            await NotificationService(db).collect()
    await db.rollback()
    assert not (await db.scalars(select(NotificationSource))).all()
    assert not (await db.scalars(select(Notification))).all()
    assert await NotificationService(db).collect() == 1


async def test_malware_and_breakglass_generate_admin_alerts(db, scene, clean, admin):
    import io

    from app.documents.upload import UploadService
    from app.models.acl import BreakGlassGrant

    with patch("app.documents.upload.write_audit_event", new=AsyncMock()):
        service = UploadService(db, clean[2])
        await service.new_version(scene[0], clean[0].id, "hello.txt", io.BytesIO(b"infected"), {})
        scanner = Mock()
        scanner.scan.return_value = False
        await service.scan_one(scanner)
    db.add(
        BreakGlassGrant(
            user_id=admin.id,
            resource_id=clean[0].id,
            permission_id="VIEW",
            valid_from=datetime.now(UTC),
            valid_until=datetime.now(UTC) + timedelta(minutes=30),
            reason="incident",
            created_by=admin.id,
            audited=True,
        )
    )
    await db.commit()
    await NotificationService(db).collect()
    kinds = {row["kind"] for row in await NotificationService(db).list(admin)}
    assert kinds == {"MALWARE", "BREAK_GLASS"}
    assert not await NotificationService(db).list(scene[1])


async def test_telegram_delivery_never_sends_as_ordinary_user(db, scene, notices):
    owner_notice = next(n for n in notices if n.user_id == scene[0].id)
    for row in (await db.scalars(select(NotificationDelivery))).all():
        row.next_attempt_at = datetime.now(UTC) + timedelta(days=1)
    attempt = NotificationDelivery(
        notification_id=owner_notice.id,
        channel="TELEGRAM",
        next_attempt_at=datetime.now(UTC) - timedelta(seconds=1),
    )
    db.add(attempt)
    await db.commit()
    with patch("app.notifications.delivery.send_telegram", new=AsyncMock()) as sender:
        await DeliveryWorker(db, Settings()).process_one()
        sender.assert_not_called()
    assert attempt.status == "SUPPRESSED"


async def test_postgres_concurrent_collectors_create_one_fanout():
    import asyncio
    import os

    from sqlalchemy import delete
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.core.config import get_settings
    from app.models.user import User

    if os.environ.get("NAMBADRIVE_TEST_POSTGRES") != "1":
        pytest.skip("PostgreSQL producer lock")
    engine = create_async_engine(get_settings().database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    uid, incident_id = uuid.uuid4(), uuid.uuid4()
    try:
        async with factory() as session:
            session.add(
                User(
                    id=uid,
                    authentik_sub=str(uid),
                    username="notification-test",
                    display_name="Test",
                )
            )
            session.add(
                QuotaIncident(
                    id=incident_id,
                    actor_id=uid,
                    resource_id=uuid.uuid4(),
                    subject_type="USER",
                    subject_id=uid,
                    limit_bytes=0,
                    requested_bytes=1,
                )
            )
            await session.commit()

        async def collect():
            async with factory() as session:
                return await NotificationService(session).collect()

        assert sum(await asyncio.gather(collect(), collect())) == 1
        async with factory() as session:
            assert (
                len(
                    (
                        await session.scalars(
                            select(Notification).where(Notification.user_id == uid)
                        )
                    ).all()
                )
                == 1
            )
    finally:
        async with factory() as session:
            await session.execute(
                delete(NotificationDelivery).where(
                    NotificationDelivery.notification_id.in_(
                        select(Notification.id).where(Notification.user_id == uid)
                    )
                )
            )
            await session.execute(delete(Notification).where(Notification.user_id == uid))
            await session.execute(
                delete(NotificationSource).where(NotificationSource.source_id == incident_id)
            )
            await session.execute(delete(QuotaIncident).where(QuotaIncident.id == incident_id))
            await session.execute(delete(User).where(User.id == uid))
            await session.commit()
        await engine.dispose()
