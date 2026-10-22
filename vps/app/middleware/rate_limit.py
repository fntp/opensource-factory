"""VPS API 进程内限流（REQ-202610-0943 / M5-05）。

单节点 uvicorn 部署下使用滑动窗口计数，不引入 Redis 依赖：
- 按「客户端 IP + 路径类别」分桶；
- 普通接口与重接口（任务入队 / 向量 / 搜索）分别限额；
- 超限返回 429 + Retry-After + X-RateLimit-*；
- 定期清理空桶，内存有界；
- `RATE_LIMIT_ENABLED=false` 时整体关闭（测试 / 排障）。
"""
from __future__ import annotations

import math
import threading
import time
from collections import deque
from dataclasses import dataclass

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.config import get_settings

# 重接口前缀：涉及模型推理 / 批量任务，单独用更低阈值
HEAVY_PREFIXES = (
    "/api/tasks",
    "/api/vector-index",
    "/api/search",
    "/api/recommend/eval",
    "/api/recommend/evaluate",
)

_CLEANUP_EVERY = 1000


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    limit: int
    remaining: int
    retry_after_seconds: int


class SlidingWindowLimiter:
    """线程安全的滑动窗口计数器。"""

    def __init__(self, window_seconds: int, max_requests: int, heavy_max_requests: int) -> None:
        self.window_seconds = max(1, int(window_seconds))
        self.max_requests = max(1, int(max_requests))
        self.heavy_max_requests = max(1, int(heavy_max_requests))
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()
        self._hits_since_cleanup = 0

    def limit_for(self, path: str) -> int:
        return self.heavy_max_requests if path.startswith(HEAVY_PREFIXES) else self.max_requests

    def hit(self, key: str, limit: int, now: float | None = None) -> RateLimitDecision:
        current = time.monotonic() if now is None else now
        cutoff = current - self.window_seconds
        with self._lock:
            bucket = self._hits.setdefault(key, deque())
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            if len(bucket) >= limit:
                oldest = bucket[0] if bucket else current
                retry = max(1, math.ceil(oldest + self.window_seconds - current))
                return RateLimitDecision(False, limit, 0, retry)
            bucket.append(current)
            remaining = max(0, limit - len(bucket))
        self._hits_since_cleanup += 1
        if self._hits_since_cleanup >= _CLEANUP_EVERY:
            self._cleanup(cutoff)
        return RateLimitDecision(True, limit, remaining, 0)

    def _cleanup(self, cutoff: float) -> None:
        with self._lock:
            self._hits_since_cleanup = 0
            empty: list[str] = []
            for key, bucket in self._hits.items():
                while bucket and bucket[0] <= cutoff:
                    bucket.popleft()
                if not bucket:
                    empty.append(key)
            for key in empty:
                self._hits.pop(key, None)

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()
            self._hits_since_cleanup = 0


def client_ip(request: Request, trust_proxy: bool) -> str:
    """取客户端 IP；生产经 Caddy 反代时信任 X-Forwarded-For 第一跳。"""
    if trust_proxy:
        forwarded = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
        if forwarded:
            return forwarded
    return request.client.host if request.client else "unknown"


def install_rate_limit_middleware(app: FastAPI) -> SlidingWindowLimiter:
    """挂载 HTTP 限流中间件，返回 limiter 供状态接口 / 测试读取。"""
    settings = get_settings()
    limiter = SlidingWindowLimiter(
        window_seconds=settings.RATE_LIMIT_WINDOW_SECONDS,
        max_requests=settings.RATE_LIMIT_MAX_REQUESTS,
        heavy_max_requests=settings.RATE_LIMIT_HEAVY_MAX_REQUESTS,
    )

    @app.middleware("http")
    async def rate_limit_middleware(request: Request, call_next):  # type: ignore[no-untyped-def]
        path = request.url.path
        if not settings.RATE_LIMIT_ENABLED or not path.startswith("/api/"):
            return await call_next(request)

        ip = client_ip(request, settings.RATE_LIMIT_TRUST_PROXY)
        limit = limiter.limit_for(path)
        decision = limiter.hit(f"{ip}:{path.split('/')[2] if path.count('/') >= 2 else path}", limit)
        if not decision.allowed:
            return JSONResponse(
                status_code=429,
                content={"detail": "rate_limited", "retryAfterSeconds": decision.retry_after_seconds},
                headers={
                    "Retry-After": str(decision.retry_after_seconds),
                    "X-RateLimit-Limit": str(decision.limit),
                    "X-RateLimit-Remaining": "0",
                },
            )

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(decision.limit)
        response.headers["X-RateLimit-Remaining"] = str(decision.remaining)
        return response

    return limiter
