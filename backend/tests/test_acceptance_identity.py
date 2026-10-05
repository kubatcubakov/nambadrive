"""Signed OIDC contracts against a disposable provider key, never real credentials."""

import json
import time
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlsplit

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.auth.oidc import OIDCClient, OIDCError
from app.auth.security import pkce_challenge, sha256_hex
from app.core.config import Settings
from app.core.database import get_db
from app.main import app
from app.models.session import ApplicationSession
from app.models.user import User


class Transactions:
    def __init__(self):
        self.values = {}

    async def set(self, key, value, ex):
        assert ex > 0
        self.values[key] = value

    async def getdel(self, key):
        return self.values.pop(key, None)

    async def delete(self, key):
        self.values.pop(key, None)


@pytest.fixture
def provider(monkeypatch):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    settings = Settings(
        public_url="https://drive.example.test",
        oidc_issuer="https://id.example.test/application/o/drive/",
        oidc_client_id="drive-test",
        oidc_client_secret="isolated-provider-secret",
        cookie_secure=True,
        oidc_clock_skew_seconds=0,
    )
    client = OIDCClient(settings)
    metadata = {
        "issuer": settings.oidc_issuer,
        **{
            name: "https://id.example.test/" + suffix
            for name, suffix in (
                ("authorization_endpoint", "authorize"),
                ("token_endpoint", "token"),
                ("jwks_uri", "jwks"),
            )
        },
    }
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
    jwk.update(kid="acceptance-key", use="sig", alg="RS256")
    client.discovery = AsyncMock(return_value=metadata)
    client._jwks = AsyncMock(return_value={"keys": [jwk]})
    transactions = Transactions()
    monkeypatch.setattr("app.auth.oidc.redis_client", transactions)

    def sign(nonce="expected-nonce", omit=(), **updates):
        now = int(time.time())
        claims = dict(
            iss=settings.oidc_issuer,
            aud=settings.oidc_client_id,
            sub="immutable-subject",
            nonce=nonce,
            iat=now,
            exp=now + 300,
            preferred_username="person",
            email="shared@example.test",
        )
        claims.update(updates)
        for name in omit:
            claims.pop(name, None)
        return jwt.encode(claims, key, algorithm="RS256", headers={"kid": "acceptance-key"})

    return client, settings, sign, jwk, transactions


async def test_signed_identity_accepts_valid_claims_and_single_use_pkce_state(provider):
    client, settings, sign, _, _ = provider
    tx, url = await client.start_login("/drive")
    query = parse_qs(urlsplit(url).query)
    assert query["code_challenge"] == [pkce_challenge(tx.code_verifier)]
    assert query["code_challenge_method"] == ["S256"]
    assert query["nonce"] == [tx.nonce] and query["state"] == [tx.state]
    assert query["redirect_uri"] == [settings.oidc_redirect_uri]
    assert await client.consume_transaction(tx.state) == tx
    with pytest.raises(OIDCError):
        await client.consume_transaction(tx.state)
    assert (await client.validate_id_token(sign(), "expected-nonce"))["sub"] == "immutable-subject"


@pytest.mark.parametrize(
    "changes",
    [
        {"iss": "https://attacker.example.test/"},
        {"aud": "different-client"},
        {"nonce": "different-nonce"},
        {"exp": 1},
        {"iat": 4102444800},
        {"azp": "different-client"},
        {"aud": ["drive-test", "other-client"]},
    ],
)
async def test_signed_oidc_rejects_invalid_required_claims(provider, changes):
    client, _, sign, _, _ = provider
    with pytest.raises(OIDCError):
        await client.validate_id_token(sign(**changes), "expected-nonce")


async def test_oidc_rejects_signature_tampering_unsigned_and_symmetric_tokens(provider):
    client, _, sign, _, _ = provider
    token = sign()
    header, body, signature = token.split(".")
    # Alter the payload, preserving the original signature.
    changed = jwt.utils.base64url_encode(b'{"sub":"attacker"}').decode()
    symmetric = jwt.encode(
        {"sub": "attacker"},
        "isolated-secret" * 3,
        algorithm="HS256",
        headers={"kid": "acceptance-key"},
    )
    for forged in (
        header + "." + changed + "." + signature,
        symmetric,
        jwt.encode({"sub": "attacker"}, key="", algorithm="none"),
    ):
        with pytest.raises(OIDCError):
            await client.validate_id_token(forged, "expected-nonce")
    assert body != changed


async def test_unknown_jwks_key_refresh_is_scoped_and_fail_closed(provider):
    client, _, sign, jwk, _ = provider
    client._jwks = AsyncMock(side_effect=[{"keys": []}, {"keys": [jwk]}])
    assert (await client.validate_id_token(sign(), "expected-nonce"))["sub"]
    assert client._jwks.await_count == 2
    client._jwks = AsyncMock(return_value={"keys": []})
    with pytest.raises(OIDCError):
        await client.validate_id_token(sign(), "expected-nonce")


async def test_callback_binds_browser_state_rotates_session_and_never_persists_raw_token(
    db, provider, monkeypatch
):
    client, settings, sign, _, _ = provider
    from app.api.v1 import auth

    monkeypatch.setattr(auth, "oidc", client)
    monkeypatch.setattr(auth, "settings", settings)

    async def database():
        yield db

    app.dependency_overrides[get_db] = database
    try:
        tx, _ = await client.start_login("/drive")
        client.exchange_code = AsyncMock(return_value={"id_token": sign(tx.nonce)})
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url=settings.public_url
        ) as browser:
            failed = await browser.get(
                "/api/v1/auth/callback", params={"state": tx.state, "code": "fixture"}
            )
            assert failed.status_code == 400
            browser.cookies.set(settings.oidc_state_cookie_name, tx.state)
            browser.cookies.set(settings.session_cookie_name, "pre-login-fixation-attempt")
            response = await browser.get(
                "/api/v1/auth/callback", params={"state": tx.state, "code": "fixture"}
            )
            assert response.status_code == 302 and response.headers["location"] == "/drive"
            raw = response.cookies[settings.session_cookie_name]
            assert raw != "pre-login-fixation-attempt"
            header = next(
                v
                for v in response.headers.get_list("set-cookie")
                if v.startswith(settings.session_cookie_name + "=")
            )
            assert all(
                value in header for value in ("Secure", "HttpOnly", "SameSite=lax", "Path=/")
            )
            row = await db.scalar(select(ApplicationSession))
            assert row.session_hash == sha256_hex(raw) and row.session_hash != raw
            client.exchange_code.assert_awaited_once_with("fixture", tx.code_verifier)
            browser.cookies.set(settings.oidc_state_cookie_name, tx.state)
            assert (
                await browser.get(
                    "/api/v1/auth/callback", params={"state": tx.state, "code": "fixture"}
                )
            ).status_code == 401
            assert len((await db.scalars(select(ApplicationSession))).all()) == 1
            user = await db.scalar(select(User))
            assert user.authentik_sub == "immutable-subject"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.parametrize("claim", ["exp", "iat", "iss", "aud", "sub", "nonce"])
async def test_signed_oidc_requires_every_mandatory_claim(provider, claim):
    client, _, sign, _, _ = provider
    with pytest.raises(OIDCError):
        await client.validate_id_token(sign(omit=[claim]), "expected-nonce")


@pytest.mark.parametrize("redirect", [False, True])
async def test_token_exchange_sends_pkce_with_fixed_origin_and_never_follows_redirect(
    provider, monkeypatch, redirect
):
    import ssl

    import httpx

    client, settings, sign, _, _ = provider
    original = httpx.AsyncClient
    calls = []

    def transport(request):
        calls.append(request)
        assert str(request.url) == "https://id.example.test/token"
        posted = parse_qs(request.content.decode())
        assert posted["code_verifier"] == ["fixture-verifier"]
        assert posted["redirect_uri"] == [settings.oidc_redirect_uri]
        assert posted["grant_type"] == ["authorization_code"]
        assert request.headers["Authorization"].startswith("Basic ")
        if redirect:
            return httpx.Response(302, headers={"Location": "https://attacker.example.test/token"})
        return httpx.Response(200, json={"id_token": sign()})

    def factory(**kwargs):
        assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
        assert isinstance(kwargs["verify"], ssl.SSLContext)
        return original(**kwargs, transport=httpx.MockTransport(transport))

    monkeypatch.setattr("app.auth.oidc.httpx.AsyncClient", factory)
    if redirect:
        with pytest.raises(httpx.HTTPStatusError):
            await client.exchange_code("fixture-code", "fixture-verifier")
    else:
        token = (await client.exchange_code("fixture-code", "fixture-verifier"))["id_token"]
        assert (await client.validate_id_token(token, "expected-nonce"))["sub"]
    assert len(calls) == 1
