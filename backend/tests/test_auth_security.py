from app.auth.security import pkce_challenge, random_urlsafe, sha256_hex


def test_random_urlsafe_is_not_reused() -> None:
    assert random_urlsafe() != random_urlsafe()


def test_sha256_hex_is_stable() -> None:
    assert sha256_hex("nambadrive") == sha256_hex("nambadrive")
    assert len(sha256_hex("nambadrive")) == 64


def test_pkce_challenge_is_urlsafe() -> None:
    challenge = pkce_challenge("A" * 64)
    assert "=" not in challenge
    assert "+" not in challenge
    assert "/" not in challenge
