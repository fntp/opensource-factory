"""数据库引擎 / 会话 / 初始化。

默认使用 SQLite（`sqlite:///./data/opensource_factory.db`），
启动时通过 `init_db()` 以 `Base.metadata.create_all` 建表（不做迁移，保持简单）。
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class Base(DeclarativeBase):
    """所有 ORM 模型的基类。"""


def _ensure_sqlite_dir(url: str) -> None:
    """SQLite 场景下确保数据文件所在目录存在。"""
    if not url.startswith("sqlite"):
        return
    raw_path = url.split(":///", 1)[-1].split("?", 1)[0]
    if not raw_path or raw_path == ":memory:":
        return
    Path(raw_path).expanduser().parent.mkdir(parents=True, exist_ok=True)


_ensure_sqlite_dir(settings.DATABASE_URL)

_connect_args = {"check_same_thread": False} if settings.DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(settings.DATABASE_URL, connect_args=_connect_args, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def init_db() -> None:
    """建表（幂等）。在应用启动与任务执行前调用。"""
    from app import models  # noqa: F401  确保所有模型已注册到 Base.metadata

    Base.metadata.create_all(bind=engine)
    logger.info("数据库已就绪: %s", settings.DATABASE_URL)


def get_db() -> Iterator[Session]:
    """FastAPI 依赖：请求级数据库会话。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
