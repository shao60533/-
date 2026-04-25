"""Password hashing with bcrypt (rounds=12)."""

from __future__ import annotations

import bcrypt

_ROUNDS = 12
_MIN_LENGTH = 8


def hash_password(plain: str) -> str:
    """Hash a plaintext password with bcrypt."""
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt(rounds=_ROUNDS)).decode()


def verify_password(plain: str, hashed: str) -> bool:
    """Verify a plaintext password against a bcrypt hash."""
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


def validate_password_strength(password: str) -> str | None:
    """Return an error message if password is too weak, else None."""
    if len(password) < _MIN_LENGTH:
        return f"密码长度至少 {_MIN_LENGTH} 位"
    if password.isdigit():
        return "密码不能为纯数字"
    if password.isalpha():
        return "密码需要包含数字"
    return None
