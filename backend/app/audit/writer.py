from __future__ import annotations

import fcntl
import json
import os
import re
import stat
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from starlette.concurrency import run_in_threadpool

from app.audit.context import audit_context
from app.core.config import get_settings

SECRET_KEYS = frozenset(
    {
        "password",
        "token",
        "raw_token",
        "access_token",
        "refresh_token",
        "id_token",
        "session_token",
        "share_token",
        "csrf_token",
        "client_secret",
        "s3_secret_key",
        "s3_access_key",
        "authorization",
        "cookie",
        "set-cookie",
        "code_verifier",
        "telegram_bot_token",
        "smtp_password",
    }
)


def safe_fields(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: "[REDACTED]" if str(key).lower() in SECRET_KEYS else safe_fields(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [safe_fields(item) for item in value]
    return value


def append_durable(path: Path, line: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o750)
    descriptor = os.open(
        path, os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o640
    )
    try:
        info = os.fstat(descriptor)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_mode & 0o027
            or info.st_nlink != 1
            or info.st_uid != os.geteuid()
        ):
            raise OSError("Audit destination is not a protected regular file")
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        size = os.fstat(descriptor).st_size
        if size and os.pread(descriptor, 1, size - 1) != b"\n":
            raise OSError("Incomplete audit segment requires operator recovery")
        remaining = memoryview(line)
        while remaining:
            written = os.write(descriptor, remaining)
            if written <= 0:
                raise OSError("Incomplete audit write")
            remaining = remaining[written:]
        os.fsync(descriptor)
        # Persist directory entry as well when the file was newly created/rotated.
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        os.close(descriptor)


async def write_audit_event(event_type: str, **fields: Any) -> None:
    if not re.fullmatch(r"[a-z][a-z0-9_.]{0,79}", event_type):
        raise ValueError("Invalid audit event type")
    if {"event_id", "timestamp", "application", "schema_version"} & fields.keys():
        raise ValueError("Reserved audit fields")
    context = audit_context.get() or {}
    event = {
        "user": None,
        "resource": None,
        "ip": None,
        "user_agent": "nambadrive-worker",
        "correlation_id": str(uuid.uuid4()),
        "result": "failed" if event_type.endswith("_failed") else "observed",
        **context,
        **fields,
        "event_id": str(uuid.uuid4()),
        "timestamp": datetime.now(UTC).isoformat(),
        "event_type": event_type,
        "application": "nambadrive",
        "schema_version": 1,
    }
    if "user_id" in event:
        event["user"] = event.pop("user_id")
    if "resource_id" in event:
        event["resource"] = event.pop("resource_id")
    line = (
        json.dumps(safe_fields(event), ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        + "\n"
    ).encode()
    await run_in_threadpool(append_durable, Path(get_settings().audit_log_path), line)
