"""Пароли, подписанные cookie-сессии и CSRF-токены."""
import base64
import hashlib
import hmac
import json
import secrets
import time

from .config import SECRET_KEY, SESSION_MAX_AGE

PBKDF2_ITERATIONS = 260_000
_ALGORITHM = "pbkdf2_sha256"


def hash_password(password: str) -> str:
    """PBKDF2-HMAC-SHA256 со случайной солью. Формат: alg$iterations$salt$hash."""
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), PBKDF2_ITERATIONS
    )
    return f"{_ALGORITHM}${PBKDF2_ITERATIONS}${salt}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algorithm, iterations, salt, expected = stored.split("$")
        if algorithm != _ALGORITHM:
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt.encode("utf-8"), int(iterations)
        )
    except (ValueError, AttributeError):
        return False
    return hmac.compare_digest(digest.hex(), expected)


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def _sign(payload: str) -> str:
    return hmac.new(
        SECRET_KEY.encode("utf-8"), payload.encode("ascii"), hashlib.sha256
    ).hexdigest()


def create_session_token(user_id: int, role: str) -> str:
    payload = _b64encode(
        json.dumps(
            {"uid": user_id, "role": role, "exp": int(time.time()) + SESSION_MAX_AGE}
        ).encode("utf-8")
    )
    return f"{payload}.{_sign(payload)}"


def read_session_token(token: str) -> dict | None:
    """Возвращает данные сессии или None, если подпись/срок недействительны."""
    try:
        payload, signature = token.split(".", 1)
    except (ValueError, AttributeError):
        return None
    if not hmac.compare_digest(_sign(payload), signature):
        return None
    try:
        data = json.loads(_b64decode(payload))
    except (ValueError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or data.get("exp", 0) < time.time():
        return None
    return data


def make_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def check_csrf(expected: str | None, provided: str | None) -> bool:
    if not expected or not provided:
        return False
    return hmac.compare_digest(expected, provided)