"""Password hashing, tokens, secret encryption and client-IP handling."""

from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import os
import secrets
from functools import lru_cache

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from starlette.requests import Request

from app.core.config import get_settings

# OWASP 2024 recommendation for Argon2id: m=19 MiB, t=2, p=1 is the minimum; we use
# a bit more memory since this is a low-traffic self-hosted app.
_hasher = PasswordHasher(time_cost=3, memory_cost=64 * 1024, parallelism=2, hash_len=32, salt_len=16)

# A real hash of a random password: verifying against it keeps the timing of
# "unknown e-mail" equal to "wrong password".
_DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(16))

MIN_PASSWORD_LENGTH = 10


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def password_needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


def password_problems(password: str, email: str | None = None) -> list[str]:
    problems = []
    if len(password) < MIN_PASSWORD_LENGTH:
        problems.append(f"Use at least {MIN_PASSWORD_LENGTH} characters.")
    if len(password) > 256:
        problems.append("Use at most 256 characters.")
    if email and email.split("@")[0].lower() in password.lower() and len(email.split("@")[0]) >= 4:
        problems.append("Don't use your e-mail address in the password.")
    if len(set(password)) < 5:
        problems.append("Use a less repetitive password.")
    return problems


def new_token(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def constant_time_equals(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())


# ---------------------------------------------------------------- encryption
class SecretBox:
    """AES-256-GCM with key ids so keys can be rotated.

    Format: ``v1.<kid>.<base64(nonce|ciphertext)>``. The associated data binds a
    ciphertext to its purpose (e.g. the credential row id), so a value copied
    into another row does not decrypt.
    """

    def __init__(self, keys: dict[str, bytes]):
        if not keys:
            raise ValueError("no encryption keys")
        self._keys = keys
        self._current = next(iter(keys))

    def encrypt(self, plaintext: str, aad: str) -> str:
        nonce = os.urandom(12)
        ct = AESGCM(self._keys[self._current]).encrypt(nonce, plaintext.encode(), aad.encode())
        return f"v1.{self._current}.{base64.b64encode(nonce + ct).decode()}"

    def decrypt(self, token: str, aad: str) -> str:
        version, kid, payload = token.split(".", 2)
        if version != "v1" or kid not in self._keys:
            raise ValueError("unknown key")
        raw = base64.b64decode(payload)
        return AESGCM(self._keys[kid]).decrypt(raw[:12], raw[12:], aad.encode()).decode()

    def needs_reencrypt(self, token: str) -> bool:
        return token.split(".", 2)[1] != self._current


@lru_cache
def secret_box() -> SecretBox:
    return SecretBox(get_settings().encryption_keys)


def key_hint(secret: str) -> str:
    return "…" + secret[-4:] if len(secret) >= 8 else "…"


# ---------------------------------------------------------------- client ip
def _networks(raw: str) -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    return [ipaddress.ip_network(p.strip(), strict=False) for p in raw.split(",") if p.strip()]


@lru_cache
def trusted_proxies() -> list:
    return _networks(get_settings().trusted_proxies)


@lru_cache
def allowed_networks() -> list:
    return _networks(get_settings().allowed_networks)


def _in(ip: str, nets: list) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return any(addr in n for n in nets)


def client_ip(request: Request) -> str:
    """Peer address, or the right-most untrusted X-Forwarded-For hop when the
    peer is a trusted proxy. Never trusts the header from arbitrary clients."""
    peer = request.client.host if request.client else "0.0.0.0"  # noqa: S104
    if not _in(peer, trusted_proxies()):
        return peer
    xff = request.headers.get("x-forwarded-for", "")
    hops = [h.strip() for h in xff.split(",") if h.strip()]
    for hop in reversed(hops):
        if not _in(hop, trusted_proxies()):
            return hop
    return peer


def ip_allowed(ip: str) -> bool:
    nets = allowed_networks()
    return True if not nets else _in(ip, nets)
