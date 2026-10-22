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
from fastapi.responses import JSONResponse

from app.api import (
    analysis,
    backup,
    category_suggestions,
    degradation,
    duplicates,
    licenses,
    local,
    model_routes,
    monitoring,
    notifications,
    push,
    push_policy,
    recommend,
    repos,
    search,
    security,
    summaries,
    tag_suggestions,
    tasks,
    trending,
    vector_index,
    vectors,
)
from app.config import get_settings
from app.db import SessionLocal, init_db
from app.local_ui import mount_local_ui
from app.middleware.rate_limit import install_rate_limit_middleware
from app.middleware.security_headers import SecurityHeadersMiddleware
from app.schemas import ReadyCheckOut
from app.services import monitoring as monitoring_service

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

# CORS：默认仅本机管理后台 dev server；生产通过 CORS_ORIGINS 配置精确域名
_origins = [o.strip() for o in settings.CORS_ORIGINS.split(",") if o.strip()] or ["http://localhost:5173"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=False if "*" in _origins else True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# M5-08 安全审计：补充浏览器侧基线响应头
app.add_middleware(SecurityHeadersMiddleware)

app.include_router(tasks.router)
app.include_router(notifications.router)
app.include_router(repos.router)
app.include_router(trending.router)
app.include_router(summaries.router)
app.include_router(tag_suggestions.router)
app.include_router(recommend.router)
app.include_router(push_policy.router)
app.include_router(vectors.router)
app.include_router(vector_index.router)
app.include_router(search.router)
app.include_router(category_suggestions.router)
app.include_router(duplicates.router)
app.include_router(licenses.router)
app.include_router(degradation.router)
app.include_router(push.router)
app.include_router(backup.router)
app.include_router(security.router)
app.include_router(monitoring.router)
app.include_router(model_routes.router)

# 本机一体化只读 API：/local/api/*（LOCAL_MODE=false 时统一 404）
app.include_router(local.router, prefix="/local")

# 接口限流（M5-05）：进程内滑动窗口，默认开启
install_rate_limit_middleware(app)
app.include_router(analysis.router)


@app.get("/healthz", tags=["health"], summary="健康检查")
async def healthz() -> dict[str, str]:
    return {"status": "ok", "service": "opensource-factory-vps", "version": settings.VERSION}


@app.get("/healthz/ready", tags=["health"], summary="就绪检查（数据库 / 运行目录）")
def healthz_ready() -> JSONResponse:
    """就绪探针：数据库或显式配置的运行目录不可用时返回 503。"""
    db = SessionLocal()
    try:
        checks = [
            monitoring_service.check_database(db),
            monitoring_service.check_runtime_home(monitoring_service.resolve_home(settings)),
        ]
    finally:
        db.close()
    ok = all(item["ok"] for item in checks)
    payload = ReadyCheckOut(
        status="ok" if ok else "degraded",
        service="opensource-factory-vps",
        version=settings.VERSION,
        checks=checks,
    )
    return JSONResponse(status_code=200 if ok else 503, content=payload.model_dump())


# admin 静态托管（仅 LOCAL_MODE=true；必须最后注册，避免覆盖 API 路由）
mount_local_ui(app)
