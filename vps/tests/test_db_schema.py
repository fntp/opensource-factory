"""本地 SQLite 追加列迁移测试（REQ-202610-0899）。"""
from __future__ import annotations

from sqlalchemy import create_engine, inspect

from app.db import _ensure_additive_columns


def test_ensure_additive_columns_adds_missing_and_is_idempotent(tmp_path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "CREATE TABLE my_repositories ("
            "id TEXT PRIMARY KEY, platform TEXT NOT NULL, name TEXT NOT NULL, "
            "description TEXT, html_url TEXT NOT NULL, stars INTEGER, language TEXT, "
            "readme_summary TEXT, category_id TEXT, created_at DATETIME)"
        )

    _ensure_additive_columns(engine)
    columns = {column["name"] for column in inspect(engine).get_columns("my_repositories")}
    assert {"owner", "forks", "updated_at", "synced_at", "pushed_at"} <= columns

    # 重复执行不报错、不重复补列
    _ensure_additive_columns(engine)
    assert len(inspect(engine).get_columns("my_repositories")) == 15


def test_ensure_additive_columns_ignores_missing_table(tmp_path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'empty.db'}")
    _ensure_additive_columns(engine)
    assert "my_repositories" not in inspect(engine).get_table_names()
