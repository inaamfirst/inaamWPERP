from __future__ import annotations

import hashlib
import hmac
import secrets
from base64 import urlsafe_b64encode

from cryptography.fernet import Fernet

from erp.packages.core.config import Settings, get_settings

PASSWORD_ALGORITHM = "pbkdf2_sha256"
PASSWORD_ITERATIONS = 260_000


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        PASSWORD_ITERATIONS,
    ).hex()
    return f"{PASSWORD_ALGORITHM}${PASSWORD_ITERATIONS}${salt}${digest}"


def verify_password(password: str, password_hash: str) -> bool:
    try:
        algorithm, iterations_text, salt, expected_digest = password_hash.split("$", 3)
        iterations = int(iterations_text)
    except ValueError:
        return False

    if algorithm != PASSWORD_ALGORITHM:
        return False

    actual_digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        iterations,
    ).hex()
    return hmac.compare_digest(actual_digest, expected_digest)


def generate_session_token() -> str:
    return secrets.token_urlsafe(48)


def hash_session_token(token: str, settings: Settings | None = None) -> str:
    active_settings = settings or get_settings()
    return hmac.new(
        active_settings.secret_key.encode("utf-8"),
        token.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def encryption_key(settings: Settings | None = None) -> bytes:
    active_settings = settings or get_settings()
    digest = hashlib.sha256(f"erp-fernet:{active_settings.secret_key}".encode()).digest()
    return urlsafe_b64encode(digest)


def encrypt_text(value: str, settings: Settings | None = None) -> str:
    return Fernet(encryption_key(settings)).encrypt(value.encode("utf-8")).decode("utf-8")


def decrypt_text(value: str, settings: Settings | None = None) -> str:
    return Fernet(encryption_key(settings)).decrypt(value.encode("utf-8")).decode("utf-8")
