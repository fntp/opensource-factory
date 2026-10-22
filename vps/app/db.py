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

# 旧 SQLite 库的幂等补列（create_all 不会给已存在的表加列）。
# 字段名与 models.Recommendation 保持一致，仅 SQLite 生效。
_RECOMMENDATION_COLUMNS: dict[str, str] = {
    "match_score": "REAL NOT NULL DEFAULT 0",
    "quality_score": "REAL NOT NULL DEFAULT 0",
    "quality_detail": "TEXT",
    "evaluation_run_id": "TEXT",
    "evaluated_at": "DATETIME",
}


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
    """为旧 SQLite 库补齐推荐评估新增列（幂等，失败只告警）。"""
    if not settings.DATABASE_URL.startswith("sqlite"):
        return
    from sqlalchemy import inspect, text

    inspector = inspect(engine)
    if "recommendations" not in inspector.get_table_names():
        return
    existing = {column["name"] for column in inspector.get_columns("recommendations")}
    missing = [
        (name, ddl) for name, ddl in _RECOMMENDATION_COLUMNS.items() if name not in existing
    ]
    if not missing:
        return
    try:
        with engine.begin() as connection:
            for name, ddl in missing:
                connection.execute(
                    text(f"ALTER TABLE recommendations ADD COLUMN {name} {ddl}")
                )
            # create_all 会跳过已存在的表，索引也需一并补齐
            connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_recommendations_evaluation_run_id "
                    "ON recommendations (evaluation_run_id)"
                )
            )
        logger.info("推荐表已补齐评估列: %s", ", ".join(name for name, _ in missing))
    except Exception:  # noqa: BLE001 - 补列失败不阻塞启动，任务会返回明确错误
        logger.warning("推荐表补列失败（可手工迁移后重试）", exc_info=True)


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
