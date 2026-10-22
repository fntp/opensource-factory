"""FastAPI 入口：`uvicorn app.main:app`。

启动时建表（幂等），挂载全部路由；CORS 开发环境默认允许所有来源。
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import recommend, repos, summaries, tasks, trending
from app.config import get_settings
from app.db import init_db

settings = get_settings()

logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
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
app.include_router(summaries.router)
app.include_router(recommend.router)


@app.get("/healthz", tags=["health"], summary="健康检查")
async def healthz() -> dict[str, str]:
    return {"status": "ok", "service": "opensource-factory-vps", "version": settings.VERSION}
