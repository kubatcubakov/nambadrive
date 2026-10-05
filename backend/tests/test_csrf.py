from app.auth.csrf import csrf_token, csrf_valid
from app.core.config import Settings


def test_csrf_is_tied_to_session() -> None:
    settings = Settings(csrf_secret="test-secret")
    token = csrf_token("session-a", settings)
    assert csrf_valid("session-a", token, settings)
    assert not csrf_valid("session-b", token, settings)
