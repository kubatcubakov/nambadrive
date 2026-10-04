import hashlib
import hmac

from app.core.config import Settings


def csrf_token(session_token: str, settings: Settings) -> str:
    return hmac.new(
        settings.csrf_secret.encode("utf-8"),
        session_token.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def csrf_valid(session_token: str, supplied_token: str, settings: Settings) -> bool:
    expected = csrf_token(session_token, settings)
    return hmac.compare_digest(expected, supplied_token)
