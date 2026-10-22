"""热榜表结构测试：新库建列 + 旧 SQLite 库幂等补列。"""
from __future__ import annotations

from sqlalchemy import create_engine, inspect, text

import app.db as db_module


def test_init_db_adds_missing_trending_columns(tmp_path, monkeypatch) -> None:
    old_engine = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with old_engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE trending_repositories (
                    id TEXT PRIMARY KEY,
                    platform TEXT NOT NULL,
                    name TEXT NOT NULL,
                    html_url TEXT NOT NULL,
                    stars_today INTEGER,
                    description TEXT,
                    tech_stack TEXT,
                    crawled_at DATE
                )
                """
            )
        )

    monkeypatch.setattr(db_module, "engine", old_engine)
    db_module.init_db()

    columns = {column["name"] for column in inspect(old_engine).get_columns("trending_repositories")}
    assert {"owner", "language", "stars"} <= columns

    # 幂等：重复执行不报错
    db_module.init_db()
