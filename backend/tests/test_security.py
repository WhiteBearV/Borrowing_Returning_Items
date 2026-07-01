"""Unit tests for JWT security — ไม่ต้องการ DB"""
import time

import pytest
from jose import JWTError, jwt

from app.core.config import settings
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)


# ── JWT ───────────────────────────────────────────────────────────────────────

def test_access_token_roundtrip():
    token = create_access_token("user-123")
    payload = decode_token(token)
    assert payload["sub"] == "user-123"
    assert payload["type"] == "access"


def test_access_token_with_extra():
    token = create_access_token("user-123", extra={"role": "admin"})
    payload = decode_token(token)
    assert payload["role"] == "admin"


def test_refresh_token_roundtrip():
    token = create_refresh_token("user-456")
    payload = decode_token(token)
    assert payload["sub"] == "user-456"
    assert payload["type"] == "refresh"


def test_token_has_exp():
    token = create_access_token("x")
    payload = decode_token(token)
    assert "exp" in payload


def test_tampered_token_raises():
    token = create_access_token("x")
    bad = token[:-5] + "XXXXX"
    with pytest.raises(JWTError):
        decode_token(bad)


def test_wrong_secret_raises():
    token = jwt.encode({"sub": "x"}, "wrong-secret", algorithm=settings.ALGORITHM)
    with pytest.raises(JWTError):
        decode_token(token)


def test_expired_token_raises():
    payload = {"sub": "x", "exp": int(time.time()) - 10, "type": "access"}
    token = jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    with pytest.raises(JWTError):
        decode_token(token)


def test_access_vs_refresh_different_tokens():
    a = create_access_token("x")
    r = create_refresh_token("x")
    assert a != r


# ── Password hashing ──────────────────────────────────────────────────────────

def test_hash_not_plaintext():
    h = hash_password("secret123")
    assert h != "secret123"
    assert len(h) > 20


def test_verify_correct_password():
    assert verify_password("mypassword", hash_password("mypassword")) is True


def test_verify_wrong_password():
    assert verify_password("wrongpassword", hash_password("mypassword")) is False


def test_same_password_different_hash():
    """bcrypt ใช้ random salt — hash ต้องไม่ซ้ำกัน"""
    h1 = hash_password("abc")
    h2 = hash_password("abc")
    assert h1 != h2
    assert verify_password("abc", h1)
    assert verify_password("abc", h2)
