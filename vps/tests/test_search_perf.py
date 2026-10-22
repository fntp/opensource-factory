"""检索性能与查询计划测试（REQ-202610-0904）。

覆盖：
- 分类 + Star 排序、全量 Star 排序均命中复合/单列索引，且无临时排序；
- 5k 行本地镜像上检索 P95 < 300ms（spec §6 的本地同引擎基线）；
- API 关键字过滤、LIKE 通配符转义行为。
"""
from __future__ import annotations

import random
import time
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from app.db import Base, SessionLocal, init_db
from app.main import app
from app.models import MyRepository

P95_BUDGET_MS = 300
ROWS = 5000
ITERATIONS = 200


@pytest.fixture(scope="module")
def memory_engine():
    """独立内存库：复用真实模型（含索引定义），不影响全局测试库。"""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine


def _seed(engine, rows: int = ROWS) -> None:
    random.seed(20261022)
    payload = []
    for i in range(rows):
        category = f"c{i % 10:02d}"
        payload.append(
            {
                "id": f"u{i % 20:03d}/repo-{i}",
                "platform": "github",
                "name": f"repo-{i}",
                "description": f"项目 {i} 的描述",
                "html_url": f"https://github.com/u{i % 20:03d}/repo-{i}",
                "stars": random.randint(0, 100000),
                "language": "Python" if i % 2 else "TypeScript",
                "readme_summary": None,
                "category_id": category,
                "created_at": datetime(2026, 1, 1),
            }
        )
    with engine.begin() as conn:
        conn.execute(MyRepository.__table__.insert(), payload)


def _plan(conn, sql: str, params: dict | None = None) -> str:
    rows = conn.execute(text(f"EXPLAIN QUERY PLAN {sql}"), params or {}).fetchall()
    return " | ".join(str(row[-1]) for row in rows)


def _p95(samples: list[float]) -> float:
    ordered = sorted(samples)
    index = min(len(ordered) - 1, max(0, int(len(ordered) * 0.95) - 1))
    return ordered[index]


def test_query_plan_uses_search_indexes(memory_engine) -> None:
    _seed(memory_engine)
    with memory_engine.connect() as conn:
        category_plan = _plan(
            conn,
            "SELECT * FROM my_repositories WHERE category_id = :cid "
            "ORDER BY stars DESC LIMIT 50",
            {"cid": "c03"},
        )
        list_plan = _plan(
            conn,
            "SELECT * FROM my_repositories ORDER BY stars DESC LIMIT 50",
        )

    assert "idx_my_repositories_category_stars" in category_plan
    assert "USE TEMP B-TREE FOR ORDER BY" not in category_plan
    assert "idx_my_repositories_stars" in list_plan
    assert "USE TEMP B-TREE FOR ORDER BY" not in list_plan


def test_search_p95_within_budget(memory_engine) -> None:
    # 复用已灌入的数据；若单独执行本用例则补种。
    with memory_engine.connect() as conn:
        count = conn.execute(text("SELECT COUNT(*) FROM my_repositories")).scalar_one()
    if count == 0:
        _seed(memory_engine)

    random.seed(7)
    samples: list[float] = []
    with memory_engine.connect() as conn:
        for _ in range(ITERATIONS):
            category = f"c{random.randint(0, 9):02d}"
            start = time.perf_counter()
            conn.execute(
                text(
                    "SELECT * FROM my_repositories WHERE category_id = :cid "
                    "ORDER BY stars DESC LIMIT 50"
                ),
                {"cid": category},
            ).fetchall()
            samples.append((time.perf_counter() - start) * 1000)

    assert _p95(samples) < P95_BUDGET_MS


def test_repos_api_filters_and_escapes_like() -> None:
    init_db()
    with SessionLocal() as db:
        db.merge(
            MyRepository(
                id="perf/alpha_payment",
                platform="github",
                name="alpha_payment",
                description="支付网关",
                html_url="https://github.com/perf/alpha_payment",
                stars=10,
                category_id="perf",
            )
        )
        db.merge(
            MyRepository(
                id="perf/beta",
                platform="github",
                name="beta",
                description="100% coverage",
                html_url="https://github.com/perf/beta",
                stars=20,
                category_id="perf",
            )
        )
        db.commit()

    with TestClient(app) as client:
        alpha = client.get("/api/repos", params={"q": "alpha"})
        percent = client.get("/api/repos", params={"q": "%"})

    assert alpha.status_code == 200
    assert [item["id"] for item in alpha.json()] == ["perf/alpha_payment"]
    # 未转义时 "%" 会匹配全部；转义后只匹配描述中真的含 "%" 的行
    assert [item["id"] for item in percent.json()] == ["perf/beta"]
