"""VPS API 安全响应头（REQ-202610-0946 / M5-08）。

只补充浏览器侧基线头，不改变业务语义：

- `X-Content-Type-Options: nosniff`：禁止 MIME 嗅探；
- `X-Frame-Options: DENY`：禁止被第三方页面内嵌；
- `Referrer-Policy: strict-origin-when-cross-origin`：跨域只发送 origin；
- `Permissions-Policy`：默认关闭摄像头 / 麦克风 / 定位；
- 认证接口额外 `Cache-Control: no-store`，避免代理缓存登录响应。
"""
from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

DEFAULT_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Cross-Origin-Opener-Policy": "same-origin",
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """为所有响应补充安全头；不覆盖路由已显式设置的同名头。"""

    async def dispatch(self, request: Request, call_next):  # type: ignore[no-untyped-def]
        response: Response = await call_next(request)
        for name, value in DEFAULT_HEADERS.items():
            if name not in response.headers:
                response.headers[name] = value
        if request.url.path.startswith("/api/auth"):
            response.headers.setdefault("Cache-Control", "no-store")
        return response
