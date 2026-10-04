import hashlib
import hmac
import secrets

from fastapi import HTTPException
from redis.exceptions import RedisError

from app.core.redis import redis_client


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def password_hash(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 600000)
    return "pbkdf2-sha256$600000$" + salt.hex() + "$" + digest.hex()


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations, salt, expected = encoded.split("$")
        if algorithm != "pbkdf2-sha256" or iterations != "600000":
            return False
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 600000)
        return hmac.compare_digest(actual.hex(), expected)
    except ValueError:
        return False


async def limit_attempts(ip: str, digest: str) -> None:
    # Fixed-window counters are atomic and expire even if a worker crashes.
    script = """
    local result = redis.call('INCR', KEYS[1])
    if result == 1 then redis.call('EXPIRE', KEYS[1], 60) end
    return result
    """
    try:
        for key, maximum in [("all", 120), ("ip:" + token_hash(ip), 30), ("token:" + digest, 10)]:
            count = await redis_client.eval(script, 1, "share-rate:" + key)  # type: ignore[misc]
            if int(count) > maximum:
                raise HTTPException(429, "Too many attempts", headers={"Retry-After": "60"})
    except RedisError:
        raise HTTPException(503, "Share access temporarily unavailable") from None
