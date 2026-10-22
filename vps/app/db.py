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


def _ensure_sqlite_columns() -> None:
    """为既有 SQLite 库幂等补齐新增列（create_all 不会修改已有表）。"""
    if not settings.DATABASE_URL.startswith("sqlite"):
        return
    inspector = inspect(engine)
    if "trending_repositories" in inspector.get_table_names():
        existing = {column["name"] for column in inspector.get_columns("trending_repositories")}
        additions = {
            "readme_summary": "TEXT",
            "owner": "TEXT",
            "language": "TEXT",
            "stars": "INTEGER NOT NULL DEFAULT 0",
        }
        missing = {name: ddl for name, ddl in additions.items() if name not in existing}
        if missing:
            with engine.begin() as connection:
                for name, ddl in missing.items():
                    connection.execute(text(f"ALTER TABLE trending_repositories ADD COLUMN {name} {ddl}"))
            logger.info("trending_repositories 已补齐列: %s", ", ".join(sorted(missing)))

    with engine.begin() as conn:
        rows = conn.exec_driver_sql("PRAGMA table_info(recommendations)").fetchall()
        if rows:
            columns = {row[1] for row in rows}
            if "based_on" not in columns:
                conn.exec_driver_sql("ALTER TABLE recommendations ADD COLUMN based_on TEXT")
                logger.info("已为 recommendations 补充 based_on 列")


def _ensure_sqlite_indexes() -> None:
    """为既有 SQLite 库幂等补建检索索引（M1-12 / M6-01）。"""
    if not settings.DATABASE_URL.startswith("sqlite"):
        return
    statements = (
        "CREATE INDEX IF NOT EXISTS idx_my_repositories_stars ON my_repositories (stars)",
        "CREATE INDEX IF NOT EXISTS idx_my_repositories_category_stars "
        "ON my_repositories (category_id, stars)",
    )
    with engine.begin() as conn:
        for statement in statements:
            conn.exec_driver_sql(statement)


def init_db() -> None:
    """建表（幂等）。在应用启动与任务执行前调用。"""
    from app import models  # noqa: F401  确保所有模型已注册到 Base.metadata
    from app.services.fulltext import ensure_fts_schema

    Base.metadata.create_all(bind=engine)
    _ensure_sqlite_columns()
    _ensure_sqlite_indexes()
    ensure_fts_schema(engine)
    logger.info("数据库已就绪: %s", settings.DATABASE_URL)


def get_db() -> Iterator[Session]:
    """FastAPI 依赖：请求级数据库会话。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
