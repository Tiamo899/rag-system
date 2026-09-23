"""JWT 签发与校验：PyJWT + HS256。access 短效，refresh 长效。"""
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt

from app.core.config import get_settings


def _encode(payload: dict[str, Any], expires_delta: timedelta) -> str:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    payload["iat"] = now
    payload["exp"] = now + expires_delta
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_access_token(user_id: uuid.UUID, roles: list[str]) -> str:
    settings = get_settings()
    return _encode(
        {"sub": str(user_id), "roles": roles, "type": "access"},
        timedelta(minutes=settings.access_token_expire_minutes),
    )


def create_refresh_token(user_id: uuid.UUID, roles: list[str]) -> str:
    settings = get_settings()
    return _encode(
        {"sub": str(user_id), "roles": roles, "type": "refresh"},
        timedelta(days=settings.refresh_token_expire_days),
    )


def decode_token(token: str) -> dict[str, Any]:
    """校验并解码 JWT，失败抛 jwt 异常（调用方转 401）。"""
    settings = get_settings()
    return jwt.decode(
        token, settings.jwt_secret, algorithms=[settings.jwt_algorithm]
    )
