from contextvars import ContextVar
from typing import Any

# Each HTTP request installs its own dictionary; dependency tasks can fill actor identity.
audit_context: ContextVar[dict[str, Any] | None] = ContextVar("audit_context", default=None)
