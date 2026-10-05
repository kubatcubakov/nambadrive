from __future__ import annotations

import hashlib
import json
import ssl
from dataclasses import dataclass
from typing import Any
from urllib.parse import unquote, urlencode, urlsplit

import httpx
import jwt
from jwt import PyJWK

from app.auth.security import pkce_challenge, pkce_verifier, random_urlsafe
from app.core.config import Settings
from app.core.redis import redis_client


def safe_next_url(value: str) -> str:
    decoded = value
    for _ in range(3):
        decoded = unquote(decoded)
    try:
        parsed = urlsplit(decoded)
    except ValueError:
        return "/"
    if (
        not decoded.startswith("/")
        or decoded.startswith("//")
        or "\\" in decoded
        or any(ord(char) < 32 or ord(char) == 127 for char in decoded)
        or parsed.scheme
        or parsed.netloc
    ):
        return "/"
    return value


class OIDCError(RuntimeError):
    pass


@dataclass(frozen=True)
class LoginTransaction:
    state: str
    nonce: str
    code_verifier: str
    next_url: str


class OIDCClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.cache_scope = hashlib.sha256(
            (settings.oidc_issuer + "\0" + settings.oidc_client_id).encode()
        ).hexdigest()

    def validated_metadata(self, data: dict[str, Any]) -> dict[str, Any]:
        if data.get("issuer") != self.settings.oidc_issuer:
            raise OIDCError("OIDC discovery issuer mismatch")
        expected = urlsplit(self.settings.oidc_issuer)
        try:
            for name in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
                endpoint = urlsplit(data[name])
                if (
                    endpoint.scheme not in {"http", "https"}
                    or endpoint.username
                    or endpoint.password
                    or endpoint.fragment
                    or (endpoint.scheme, endpoint.hostname, endpoint.port)
                    != (expected.scheme, expected.hostname, expected.port)
                ):
                    raise OIDCError("OIDC endpoint origin mismatch")
        except (KeyError, ValueError, TypeError) as error:
            raise OIDCError("OIDC endpoint configuration invalid") from error
        return data

    async def discovery(self) -> dict[str, Any]:
        cache_key = "oidc:discovery:" + self.cache_scope
        cached = await redis_client.get(cache_key)
        if cached:
            return self.validated_metadata(json.loads(cached))

        async with httpx.AsyncClient(
            timeout=10.0,
            trust_env=False,
            follow_redirects=False,
            verify=ssl.create_default_context(cafile=self.settings.http_ca_file),
        ) as client:
            response = await client.get(self.settings.oidc_discovery_url)
            response.raise_for_status()
            data = response.json()

        self.validated_metadata(data)
        await redis_client.set(cache_key, json.dumps(data), ex=3600)
        return data

    async def start_login(self, next_url: str = "/") -> tuple[LoginTransaction, str]:
        metadata = await self.discovery()
        state = random_urlsafe()
        nonce = random_urlsafe()
        verifier = pkce_verifier()
        transaction = LoginTransaction(
            state=state,
            nonce=nonce,
            code_verifier=verifier,
            next_url=safe_next_url(next_url),
        )
        await redis_client.set(
            f"oidc:tx:{state}",
            json.dumps(transaction.__dict__),
            ex=self.settings.oidc_transaction_ttl_seconds,
        )
        params = {
            "client_id": self.settings.oidc_client_id,
            "redirect_uri": self.settings.oidc_redirect_uri,
            "response_type": "code",
            "scope": "openid profile email",
            "state": state,
            "nonce": nonce,
            "code_challenge": pkce_challenge(verifier),
            "code_challenge_method": "S256",
        }
        return transaction, f"{metadata['authorization_endpoint']}?{urlencode(params)}"

    async def consume_transaction(self, state: str) -> LoginTransaction:
        key = f"oidc:tx:{state}"
        raw = await redis_client.getdel(key)
        if raw is None:
            raise OIDCError("OIDC transaction expired or invalid")
        return LoginTransaction(**json.loads(raw))

    async def exchange_code(self, code: str, verifier: str) -> dict[str, Any]:
        metadata = await self.discovery()
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self.settings.oidc_redirect_uri,
            "client_id": self.settings.oidc_client_id,
            "code_verifier": verifier,
        }
        auth: httpx.BasicAuth | None = None
        if self.settings.oidc_client_secret:
            auth = httpx.BasicAuth(self.settings.oidc_client_id, self.settings.oidc_client_secret)

        async with httpx.AsyncClient(
            timeout=15.0,
            trust_env=False,
            follow_redirects=False,
            verify=ssl.create_default_context(cafile=self.settings.http_ca_file),
        ) as client:
            if auth is None:
                response = await client.post(metadata["token_endpoint"], data=data)
            else:
                response = await client.post(metadata["token_endpoint"], data=data, auth=auth)
            response.raise_for_status()
            return response.json()

    async def _jwks(self, jwks_uri: str) -> dict[str, Any]:
        cache_key = "oidc:jwks:" + self.cache_scope
        cached = await redis_client.get(cache_key)
        if cached:
            return json.loads(cached)
        async with httpx.AsyncClient(
            timeout=10.0,
            trust_env=False,
            follow_redirects=False,
            verify=ssl.create_default_context(cafile=self.settings.http_ca_file),
        ) as client:
            response = await client.get(jwks_uri)
            response.raise_for_status()
            data = response.json()
        await redis_client.set(cache_key, json.dumps(data), ex=3600)
        return data

    async def validate_id_token(self, id_token: str, nonce: str) -> dict[str, Any]:
        metadata = await self.discovery()
        try:
            header = jwt.get_unverified_header(id_token)
        except jwt.PyJWTError as exc:
            raise OIDCError("OIDC ID token header is invalid") from exc
        algorithm = header.get("alg")
        kid = header.get("kid")
        allowed_algorithms = set(self.settings.oidc_allowed_algorithms)
        if algorithm not in allowed_algorithms or not kid:
            raise OIDCError("OIDC token algorithm or key id is not allowed")

        jwks = await self._jwks(metadata["jwks_uri"])
        matching = next((item for item in jwks.get("keys", []) if item.get("kid") == kid), None)
        if matching is None:
            await redis_client.delete("oidc:jwks:" + self.cache_scope)
            jwks = await self._jwks(metadata["jwks_uri"])
            matching = next((item for item in jwks.get("keys", []) if item.get("kid") == kid), None)
        if matching is None:
            raise OIDCError("OIDC signing key not found")

        try:
            key = PyJWK.from_dict(matching, algorithm=algorithm).key
            claims = jwt.decode(
                id_token,
                key=key,
                algorithms=[algorithm],
                audience=self.settings.oidc_client_id,
                issuer=self.settings.oidc_issuer,
                leeway=self.settings.oidc_clock_skew_seconds,
                options={"require": ["exp", "iat", "iss", "aud", "sub", "nonce"]},
            )
        except jwt.PyJWTError as exc:
            raise OIDCError("OIDC ID token validation failed") from exc
        if claims.get("nonce") != nonce:
            raise OIDCError("OIDC nonce mismatch")
        audience = claims.get("aud")
        if (
            isinstance(audience, list)
            and len(audience) > 1
            and claims.get("azp") != self.settings.oidc_client_id
        ) or ("azp" in claims and claims["azp"] != self.settings.oidc_client_id):
            raise OIDCError("OIDC authorized party mismatch")
        return claims
