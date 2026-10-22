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

# 旧 SQLite 库的幂等补列（create_all 不会给已存在的表加列）。
# 字段名与 models.Recommendation 保持一致，仅 SQLite 生效。
_RECOMMENDATION_COLUMNS: dict[str, str] = {
    "match_score": "REAL NOT NULL DEFAULT 0",
    # Rerank 精排（M7-07）
    "base_score": "REAL NOT NULL DEFAULT 0",
    "rerank_score": "REAL NOT NULL DEFAULT 0",
    "rerank_rank": "INTEGER",
    "rerank_detail": "TEXT",
    "reranked_at": "DATETIME",
    "quality_score": "REAL NOT NULL DEFAULT 0",
    "quality_detail": "TEXT",
    "evaluation_run_id": "TEXT",
    "evaluated_at": "DATETIME",
    "based_on": "TEXT",
    "bark_sent_at": "DATETIME",
    "bark_error": "TEXT",
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
    """为既有 SQLite 库幂等补齐新增列（create_all 不会修改已有表）。"""
    if not settings.DATABASE_URL.startswith("sqlite"):
        return

    inspector = inspect(engine)
    table_additions: dict[str, dict[str, str]] = {
        "trending_repositories": {
            "readme_summary": "TEXT",
            "owner": "TEXT",
            "language": "TEXT",
            "stars": "INTEGER NOT NULL DEFAULT 0",
            "license_spdx": "TEXT",
            "license_name": "TEXT",
            "license_source": "TEXT",
            "license_checked_at": "DATETIME",
        },
        "my_repositories": {
            "pushed_at": "DATETIME",
            "updated_at": "DATETIME",
            "open_issues_count": "INTEGER NOT NULL DEFAULT 0",
            "archived": "BOOLEAN NOT NULL DEFAULT 0",
            "disabled": "BOOLEAN NOT NULL DEFAULT 0",
            "health_status": "TEXT",
            "health_score": "INTEGER",
            "health_checked_at": "DATETIME",
            "license_spdx": "TEXT",
            "license_name": "TEXT",
            "license_source": "TEXT",
            "license_checked_at": "DATETIME",
        },
    }
    tables = set(inspector.get_table_names())
    for table, additions in table_additions.items():
        if table not in tables:
            continue
        existing = {column["name"] for column in inspector.get_columns(table)}
        missing = {name: ddl for name, ddl in additions.items() if name not in existing}
        if missing:
            with engine.begin() as connection:
                for name, ddl in missing.items():
                    connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))
            logger.info("%s 已补齐列: %s", table, ", ".join(sorted(missing)))

    if "recommendations" in tables:
        existing = {column["name"] for column in inspector.get_columns("recommendations")}
        missing = [
            (name, ddl) for name, ddl in _RECOMMENDATION_COLUMNS.items() if name not in existing
        ]
        if missing:
            try:
                with engine.begin() as connection:
                    for name, ddl in missing:
                        connection.execute(
                            text(f"ALTER TABLE recommendations ADD COLUMN {name} {ddl}")
                        )
                    connection.execute(
                        text(
                            "CREATE INDEX IF NOT EXISTS ix_recommendations_evaluation_run_id "
                            "ON recommendations (evaluation_run_id)"
                        )
                    )
                logger.info("推荐表已补齐评估列: %s", ", ".join(name for name, _ in missing))
            except Exception:  # noqa: BLE001 - 补列失败不阻塞启动，任务会返回明确错误
                logger.warning("推荐表补列失败（可手工迁移后重试）", exc_info=True)


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
