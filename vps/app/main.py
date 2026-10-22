"""FastAPI 入口：`uvicorn app.main:app`。

启动时建表（幂等），挂载全部路由；CORS 开发环境默认允许所有来源。
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import push, recommend, repos, tasks, trending, vector_sync, vectors
from app.config import get_settings
from app.db import init_db

settings = get_settings()


def _build_handlers() -> list[logging.Handler]:
    """构建日志 handler：stdout 常驻，配置 LOG_DIR 时追加滚动文件。"""
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if settings.LOG_DIR:
        log_dir = Path(settings.LOG_DIR)
        log_dir.mkdir(parents=True, exist_ok=True)
        handlers.append(
            RotatingFileHandler(
                log_dir / "vps-api.log",
                maxBytes=10 * 1024 * 1024,
                backupCount=5,
                encoding="utf-8",
            )
        )
    return handlers


logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    handlers=_build_handlers(),
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """应用生命周期：启动时初始化数据库。"""
    init_db()
    logger.info("%s v%s 已启动", settings.APP_NAME, settings.VERSION)
    yield


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.VERSION,
    description="开源项目工厂本地算力节点：GitHub 同步 / 热榜抓取 / README 摘要 / 向量推荐",
    lifespan=lifespan,
)

# CORS：开发环境允许所有来源（生产可通过 CORS_ORIGINS 收紧）
_origins = [o.strip() for o in settings.CORS_ORIGINS.split(",") if o.strip()] or ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=False if "*" in _origins else True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(tasks.router)
app.include_router(repos.router)
app.include_router(trending.router)
app.include_router(recommend.router)
app.include_router(vector_sync.router)
app.include_router(vectors.router)
app.include_router(push.router)


@app.get("/healthz", tags=["health"], summary="健康检查")
async def healthz() -> dict[str, str]:
    return {"status": "ok", "service": "opensource-factory-vps", "version": settings.VERSION}
