"""每日推荐生成服务测试（M3-05）。

覆盖：已收藏去重、阈值过滤、综合打分、幂等更新、过期状态、复用持久化向量、
任务薄封装。全部使用 hash 兜底向量，不加载模型、不访问网络。
"""
from __future__ import annotations

import json

import pytest
from sqlalchemy import delete, select

from app.db import SessionLocal, init_db
from app.models import MyRepository, Recommendation, RepoVector, TrendingRepository, User
from app.services.embedding import EmbeddingService
from app.services.recommendation_service import generate_for_user
from app.services.vector_pipeline import build_repo_text, text_digest
from app.tasks.jobs import generate_recommendations


@pytest.fixture()
def db():
    init_db()
    session = SessionLocal()
    _cleanup(session)
    yield session
    _cleanup(session)
    session.close()


def _cleanup(session) -> None:
    session.execute(delete(Recommendation).where(Recommendation.user_id.like("rec-test%")))
    session.execute(delete(RepoVector).where(RepoVector.repo_id.like("rec-test/%")))
    session.execute(delete(MyRepository).where(MyRepository.id.like("rec-test/%")))
    session.execute(delete(TrendingRepository).where(TrendingRepository.id.like("rec-test/%")))
    session.execute(delete(User).where(User.id.like("rec-test%")))
    session.commit()


def _service() -> EmbeddingService:
    return EmbeddingService(force_fallback=True)


def _seed_my(
    db,
    suffix: str,
    *,
    name: str = "fastapi",
    description: str = "python web framework",
    language: str = "Python",
    stars: int = 10,
) -> MyRepository:
    row = MyRepository(
        id=f"rec-test/{suffix}",
        platform="github",
        name=name,
        description=description,
        html_url=f"https://example.com/rec-test/{suffix}",
        stars=stars,
        language=language,
        readme_summary=None,
    )
    db.add(row)
    db.commit()
    return row


def _seed_trending(
    db,
    suffix: str,
    *,
    name: str = "django",
    description: str = "python web framework",
    tech_stack: str = "Python",
    stars_today: int = 100,
) -> TrendingRepository:
    row = TrendingRepository(
        id=f"rec-test/{suffix}",
        platform="github",
        name=name,
        html_url=f"https://example.com/rec-test/{suffix}",
        stars_today=stars_today,
        description=description,
        tech_stack=tech_stack,
    )
    db.add(row)
    db.commit()
    return row


def _recommendations(db, user_id: str) -> list[Recommendation]:
    db.expire_all()
    return list(
        db.execute(
            select(Recommendation)
            .where(Recommendation.user_id == user_id)
            .order_by(Recommendation.repo_id)
        )
        .scalars()
        .all()
    )


def test_generate_filters_collected_and_below_threshold(db) -> None:
    _seed_my(db, "my")
    # 已收藏仓库同时出现在热榜中：必须被排除
    _seed_my(db, "collected", name="django", description="python web framework")
    _seed_trending(db, "collected", name="django", description="python web framework")
    _seed_trending(db, "related", name="django", description="python web framework")
    _seed_trending(
        db,
        "unrelated",
        name="rust-game",
        description="rust game engine graphics",
        tech_stack="Rust",
        stars_today=500,
    )

    result = generate_for_user(
        db,
        "rec-test-user",
        service=_service(),
        min_score=0.3,
        top_k=5,
    )

    assert result["status"] == "ok"
    assert result["excludedCollected"] == 1
    assert result["belowThreshold"] == 1
    assert result["selected"] == 1
    assert result["created"] == 1

    rows = _recommendations(db, "rec-test-user")
    assert [row.repo_id for row in rows] == ["rec-test/related"]
    assert rows[0].score > 0.3
    assert "相似度" in (rows[0].reason or "")
    assert "rec-test/collected" not in {row.repo_id for row in rows}


def test_generate_is_idempotent_and_expires_stale_new(db) -> None:
    _seed_my(db, "my")
    _seed_trending(db, "related", name="django", description="python web framework")
    _seed_trending(
        db,
        "unrelated",
        name="rust-game",
        description="rust game engine graphics",
        tech_stack="Rust",
        stars_today=500,
    )

    first = generate_for_user(
        db, "rec-test-user", service=_service(), min_score=0.3, top_k=5
    )
    assert first["created"] == 1

    rows = _recommendations(db, "rec-test-user")
    related = rows[0]
    related.status = "dismissed"
    db.add(
        Recommendation(
            id="rec-test-old",
            user_id="rec-test-user",
            repo_id="rec-test/old",
            score=0.5,
            reason="旧推荐",
            status="new",
        )
    )
    # 已收藏仓库的历史 new 推荐也应过期
    _seed_my(db, "collected", name="django", description="python web framework")
    db.add(
        Recommendation(
            id="rec-test-collected-rec",
            user_id="rec-test-user",
            repo_id="rec-test/collected",
            score=0.6,
            reason="已收藏",
            status="new",
        )
    )
    db.commit()

    second = generate_for_user(
        db, "rec-test-user", service=_service(), min_score=0.3, top_k=5
    )
    assert second["created"] == 0
    # M3-07 反馈闭环会把 dismissed 仓库排除出候选，因此本轮不会刷新该行；
    # 旧 new 推荐（含已收藏仓库）仍应被过期。
    assert second["updated"] == 0
    assert second["expired"] == 2

    rows = _recommendations(db, "rec-test-user")
    by_repo = {row.repo_id: row for row in rows}
    # 不重复插入；用户忽略状态不被覆盖
    assert len([row for row in rows if row.repo_id == "rec-test/related"]) == 1
    assert by_repo["rec-test/related"].status == "dismissed"
    assert by_repo["rec-test/old"].status == "expired"
    assert by_repo["rec-test/collected"].status == "expired"


def test_generate_reuses_persisted_vectors(db, monkeypatch) -> None:
    my_row = _seed_my(db, "my")
    trending_row = _seed_trending(
        db, "related", name="django", description="python web framework"
    )
    service = _service()

    for source, row in (("my", my_row), ("trending", trending_row)):
        text = build_repo_text(source, row)
        vector = service.encode_one(text)
        db.add(
            RepoVector(
                source=source,
                repo_id=row.id,
                model=service.model_name,
                backend=service.backend,
                dim=len(vector),
                text_hash=text_digest(text),
                vector=json.dumps(vector),
            )
        )
    db.commit()

    def _unexpected_encode(*args, **kwargs):
        raise AssertionError("已有兼容向量时不应重新编码")

    monkeypatch.setattr(service, "encode", _unexpected_encode)

    result = generate_for_user(
        db, "rec-test-user", service=service, min_score=0.3, top_k=5
    )
    assert result["status"] == "ok"
    assert result["selected"] == 1
    assert result["profileSize"] == 1


def test_generate_high_threshold_expires_existing_new(db) -> None:
    _seed_my(db, "my")
    _seed_trending(db, "related", name="django", description="python web framework")

    first = generate_for_user(
        db, "rec-test-user", service=_service(), min_score=0.3, top_k=5
    )
    assert first["created"] == 1

    second = generate_for_user(
        db, "rec-test-user", service=_service(), min_score=0.99, top_k=5
    )
    assert second["status"] == "ok"
    assert second["selected"] == 0
    assert second["expired"] == 1

    rows = _recommendations(db, "rec-test-user")
    assert rows[0].status == "expired"


def test_generate_top_k_limits_results(db) -> None:
    _seed_my(db, "my")
    _seed_trending(db, "related", name="django", description="python web framework")
    _seed_trending(db, "flask", name="flask", description="python web framework")

    result = generate_for_user(
        db, "rec-test-user", service=_service(), min_score=0.3, top_k=1
    )
    assert result["selected"] == 1
    assert len(_recommendations(db, "rec-test-user")) == 1


def test_generate_skips_without_profile_or_trending(db) -> None:
    no_profile = generate_for_user(db, "rec-test-user", service=_service())
    assert no_profile["status"] == "skipped"
    assert "没有仓库" in no_profile["reason"]

    _seed_my(db, "my")
    no_trending = generate_for_user(db, "rec-test-user", service=_service())
    assert no_trending["status"] == "skipped"
    assert "热榜" in no_trending["reason"]


def test_task_wrapper_returns_summary(db) -> None:
    _seed_my(db, "my")
    _seed_trending(db, "related", name="django", description="python web framework")

    result = generate_recommendations.run(
        user_id="rec-test-task", top_k=5, min_score=0.3
    )

    assert result["status"] == "ok"
    assert result["users"] == ["rec-test-task"]
    assert result["created"] == 1
    db.expire_all()
    rows = _recommendations(db, "rec-test-task")
    assert [row.repo_id for row in rows] == ["rec-test/related"]
