"""数据库引擎 / 会话 / 初始化。

默认使用 SQLite（`sqlite:///./data/opensource_factory.db`），
启动时通过 `init_db()` 以 `Base.metadata.create_all` 建表（不做迁移，保持简单）。
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterator

from sqlalchemy import create_engine, inspect, text
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


# 本地 SQLite 兼容补列：create_all 不会修改既有表，这里对新增列做幂等补齐。
# 仅新增列、不改列类型，与 D1 `my_repositories` 的扩展列保持一致。
_SQLITE_ADDED_COLUMNS: dict[str, dict[str, str]] = {
    "my_repositories": {
        "owner": "TEXT",
        "forks": "INTEGER DEFAULT 0",
        "updated_at": "TEXT",
        "synced_at": "TEXT",
    },
}


def _ensure_sqlite_columns() -> None:
    """为既有 SQLite 库补齐新增列（幂等；非 SQLite 直接跳过）。"""
    if not settings.DATABASE_URL.startswith("sqlite"):
        return
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    with engine.begin() as conn:
        for table, columns in _SQLITE_ADDED_COLUMNS.items():
            if table not in tables:
                continue
            existing = {column["name"] for column in inspector.get_columns(table)}
            for name, ddl in columns.items():
                if name not in existing:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))
                    logger.info("SQLite 补列: %s.%s", table, name)


def init_db() -> None:
    """建表（幂等）。在应用启动与任务执行前调用。"""
    from app import models  # noqa: F401  确保所有模型已注册到 Base.metadata

    Base.metadata.create_all(bind=engine)
    _ensure_sqlite_columns()
    logger.info("数据库已就绪: %s", settings.DATABASE_URL)


def get_db() -> Iterator[Session]:
    """FastAPI 依赖：请求级数据库会话。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
