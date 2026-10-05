from __future__ import annotations

import re
import smtplib
import ssl
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from email.utils import parseaddr

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.authorization.service import AuthorizationService
from app.core.config import Settings
from app.models.notification import Notification, NotificationDelivery, NotificationPreference
from app.models.user import User
from app.notifications.service import MESSAGES, permitted


class DeliveryUnavailable(Exception):
    pass


def mailbox(value: str) -> str:
    if any(char in value for char in "\r\n") or parseaddr(value)[1] != value or "@" not in value:
        raise DeliveryUnavailable("Invalid mail configuration")
    return value


def send_email(settings: Settings, recipient: str, message_id: str) -> None:
    if not settings.smtp_host or not settings.smtp_from:
        raise DeliveryUnavailable("Email channel not configured")
    message = EmailMessage()
    message["From"] = mailbox(settings.smtp_from)
    message["To"] = mailbox(recipient)
    message["Subject"] = "NambaDrive: новое уведомление"
    message["Message-ID"] = "<" + message_id + "@nambadrive>"
    # No document/event/identity detail is exported to mail infrastructure.
    message.set_content("В NambaDrive появилось новое уведомление. Войдите в приложение.")
    context = ssl.create_default_context(cafile=settings.smtp_ca_file)
    with smtplib.SMTP_SSL(
        settings.smtp_host, settings.smtp_port, timeout=20, context=context
    ) as smtp:
        if settings.smtp_username:
            smtp.login(settings.smtp_username, settings.smtp_password.get_secret_value())
        smtp.send_message(message)


async def send_telegram(settings: Settings, kind: str) -> None:
    token, chat = (
        settings.telegram_bot_token.get_secret_value(),
        settings.telegram_admin_chat_id.get_secret_value(),
    )
    if not re.fullmatch(r"[0-9]+:[A-Za-z0-9_-]{20,}", token) or not re.fullmatch(r"-?[0-9]+", chat):
        raise DeliveryUnavailable("Telegram channel not configured")
    if kind not in {"QUOTA", "MALWARE", "BREAK_GLASS"}:
        raise DeliveryUnavailable("Unsupported administrative alert")
    # Fixed official origin, no user URL / redirect / environment proxy; no error body logs.
    url = "https://api.telegram.org/bot" + token + "/sendMessage"
    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=False, trust_env=False) as client:
            response = await client.post(
                url, json={"chat_id": chat, "text": "NambaDrive: " + MESSAGES[kind]}
            )
            if response.status_code != 200 or response.json().get("ok") is not True:
                raise DeliveryUnavailable("Telegram unavailable")
    except (httpx.HTTPError, ValueError):
        raise DeliveryUnavailable("Telegram unavailable") from None


class DeliveryWorker:
    def __init__(self, db: AsyncSession, settings: Settings):
        self.db, self.settings = db, settings

    async def process_one(self) -> bool:
        now = datetime.now(UTC)
        row = await self.db.scalar(
            select(NotificationDelivery)
            .where(
                NotificationDelivery.status == "PENDING",
                NotificationDelivery.next_attempt_at <= now,
            )
            .order_by(NotificationDelivery.next_attempt_at, NotificationDelivery.id)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if row is None:
            await self.db.rollback()
            return False
        notice = await self.db.get(Notification, row.notification_id)
        user = await self.db.get(User, notice.user_id, populate_existing=True) if notice else None
        allowed = notice is not None and user is not None and await permitted(self.db, user, notice)
        if allowed and user is not None and row.channel == "TELEGRAM":
            allowed = (
                await AuthorizationService().authorize(self.db, user, "RECEIVE_ADMIN_ALERTS", None)
            ).allowed
        preference = await self.db.get(NotificationPreference, user.id) if user else None
        if row.channel == "EMAIL" and preference is not None and not preference.email_enabled:
            allowed = False
        if not allowed:
            row.status = "SUPPRESSED"
        else:
            row.attempts += 1
            try:
                if row.channel == "EMAIL":
                    if user is None or not user.email:
                        raise DeliveryUnavailable("Recipient has no email")
                    await run_in_threadpool(send_email, self.settings, user.email, str(row.id))
                elif notice is not None:
                    await send_telegram(self.settings, notice.kind)
                row.status, row.sent_at = "SENT", now
            except (DeliveryUnavailable, smtplib.SMTPException, OSError):
                # Store retry state, never exception strings containing credentials/recipient data.
                row.next_attempt_at = now + timedelta(
                    seconds=min(3600, 30 * 2 ** min(row.attempts, 7))
                )
        await self.db.commit()
        return True
