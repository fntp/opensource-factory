"""安全状态接口（REQ-202610-0943 / M5-05）。

GET /api/security/status：内部令牌双令牌状态 + 限流配置（不含任何令牌明文）。
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends

from app.config import get_settings
from app.security import internal_token_status, require_internal_token

router = APIRouter(
    prefix="/api/security",
    tags=["security"],
    dependencies=[Depends(require_internal_token)],
)


@router.get("/status", summary="安全加固状态（双令牌 / 限流）")
def security_status() -> dict[str, object]:
    settings = get_settings()
    return {
        "internalToken": internal_token_status(),
        "rateLimit": {
            "enabled": settings.RATE_LIMIT_ENABLED,
            "windowSeconds": settings.RATE_LIMIT_WINDOW_SECONDS,
            "maxRequests": settings.RATE_LIMIT_MAX_REQUESTS,
            "heavyMaxRequests": settings.RATE_LIMIT_HEAVY_MAX_REQUESTS,
            "trustProxy": settings.RATE_LIMIT_TRUST_PROXY,
        },
        "now": datetime.now(timezone.utc).isoformat(),
    }
