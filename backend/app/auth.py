"""Authentication helpers using only the standard library.

* Passwords: PBKDF2-HMAC-SHA256 with a per-user random salt.
* Sessions: compact signed tokens ``base64url(payload).base64url(HMAC-SHA256)``
  carrying the username and an expiry time (similar in spirit to a JWT).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time

PBKDF2_ROUNDS = 240_000
SESSION_COOKIE_NAME = "rtla_session"


def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ROUNDS)
    return f"pbkdf2_sha256${PBKDF2_ROUNDS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, rounds, salt_hex, digest_hex = stored.split("$")
        if scheme != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), int(rounds))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(digest.hex(), digest_hex)


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def create_token(
    username: str,
    secret: str,
    ttl_seconds: int = 8 * 3600,
    now: float | None = None,
    session_version: int = 0,
) -> str:
    payload = _b64(json.dumps({
        "sub": username,
        "exp": int((now or time.time()) + ttl_seconds),
        "ver": session_version,
    }).encode())
    signature = _b64(hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest())
    return f"{payload}.{signature}"


def read_token(
    token: str,
    secret: str,
    now: float | None = None,
    session_version: int | None = None,
) -> str | None:
    """Return the username if the token is genuine and unexpired, else None."""
    try:
        payload, signature = token.split(".")
        expected = _b64(hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(signature, expected):
            return None
        data = json.loads(_unb64(payload))
        if data["exp"] < (now or time.time()):
            return None
        if session_version is not None and data.get("ver", 0) != session_version:
            return None
        return str(data["sub"])
    except (ValueError, KeyError, TypeError):
        return None


class LoginThrottle:
    """Blocks a username for ``lock_seconds`` after ``max_failures`` bad passwords."""

    def __init__(self, max_failures: int = 5, lock_seconds: int = 60):
        self.max_failures, self.lock_seconds = max_failures, lock_seconds
        self._failures: dict[str, list[float]] = {}

    def locked(self, username: str, now: float | None = None) -> bool:
        now = now or time.time()
        recent = [t for t in self._failures.get(username, []) if now - t < self.lock_seconds]
        if recent:
            self._failures[username] = recent
        else:
            self._failures.pop(username, None)
        return len(recent) >= self.max_failures

    def fail(self, username: str, now: float | None = None) -> None:
        now = now or time.time()
        if len(self._failures) >= 10_000 and username not in self._failures:
            cutoff = now - self.lock_seconds
            for name in tuple(self._failures):
                if not self._failures[name] or self._failures[name][-1] < cutoff:
                    self._failures.pop(name, None)
            if len(self._failures) >= 10_000:
                oldest = min(self._failures, key=lambda name: self._failures[name][-1])
                self._failures.pop(oldest, None)
        self._failures.setdefault(username, []).append(now)

    def clear(self, username: str) -> None:
        self._failures.pop(username, None)
