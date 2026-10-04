from __future__ import annotations

import asyncio
import json
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.core.config import get_settings

_lock = asyncio.Lock()


async def write_audit_event(event_type: str, **fields: Any) -> None:
    settings = get_settings()
    path = Path(settings.audit_log_path)
    event = {
        "event_id": str(uuid.uuid4()),
        "timestamp": datetime.now(UTC).isoformat(),
        "event_type": event_type,
        **fields,
    }
    line = json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n"

    async with _lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line)
            handle.flush()
            os.fsync(handle.fileno())
