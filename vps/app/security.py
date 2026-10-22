"""安全加固（REQ-202610-0943 / M5-05）。

- 内部令牌双令牌校验：`INTERNAL_TOKEN`（当前）+ `INTERNAL_TOKEN_PREVIOUS`（轮换过渡期）；
- 使用 `hmac.compare_digest` 做常量时间比较；
- 提供只含指纹的状态信息，任何接口都不回显令牌明文。
"""
from __future__ import annotations

import hashlib
import hmac

from fastapi import Header, HTTPException, status

from app.config import get_settings


def _normalize(value: str | None) -> str:
    return (value or "").strip()


def token_fingerprint(token: str) -> str:
    """令牌指纹：sha-256 前 12 位十六进制，用于人工核对，不可反推。"""
    if not token:
        return ""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()[:12]


def internal_tokens() -> tuple[str, str]:
    settings = get_settings()
    return (
        _normalize(getattr(settings, "INTERNAL_TOKEN", "")),
        _normalize(getattr(settings, "INTERNAL_TOKEN_PREVIOUS", "")),
    )


def verify_internal_token(provided: str | None) -> bool:
    """校验内部令牌；两枚令牌都未配置时视为未启用（本地开发）。"""
    current, previous = internal_tokens()
    if not current and not previous:
        return True
    supplied = _normalize(provided)
    if not supplied:
        return False
    supplied_bytes = supplied.encode("utf-8")
    return any(
        hmac.compare_digest(supplied_bytes, candidate.encode("utf-8"))
        for candidate in (current, previous)
        if candidate
    )


def require_internal_token(
    x_internal_token: str | None = Header(default=None, alias="X-Internal-Token"),
) -> None:
    """FastAPI 依赖：内部令牌未配置时不启用；配置后严格校验（接受双令牌）。"""
    if not verify_internal_token(x_internal_token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid internal token")


def internal_token_status() -> dict[str, object]:
    """双令牌状态（不含明文）。"""
    current, previous = internal_tokens()
    return {
        "configured": bool(current),
        "previousConfigured": bool(previous),
        "rotationPending": bool(current and previous),
        "currentFingerprint": token_fingerprint(current),
        "previousFingerprint": token_fingerprint(previous),
    }
