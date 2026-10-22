"""每日推荐评估测试（M4-01）。

覆盖：质量分纯函数、匹配度 / 质量分双门槛、状态保留、幂等重跑与阈值调参、
运行记录、合格推荐查询、任务与 API。全部使用本地 SQLite，不访问网络。
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.db import SessionLocal, init_db
from app.main import app
from app.models import (
    MyRepository,
    Recommendation,
    RecommendationEvaluationRun,
    TrendingRepository,
    User,
)
from app.services.embedding import EmbeddingService
from app.services.recommendation_eval import (
    compute_quality_score,
    evaluate_candidate,
    evaluate_daily,
    score_reason_quality,
    score_repo_quality,
)
from app.services.recommendation_service import generate_for_user
from app.tasks.jobs import daily_push, evaluate_recommendations

GOOD_REASON = (
    "与你的兴趣相似度约 82%。主要使用 Python 开发；技术栈涉及 FastAPI / SQLAlchemy；"
    "项目简介：一个用于测试的完整 Web 服务模板，包含鉴权、任务队列与可观测性。推荐关注 demo。"
)


@pytest.fixture()
def db():
    init_db()
    session = SessionLocal()
    _cleanup(session)
    yield session
    _cleanup(session)
    session.close()


def _cleanup(session) -> None:
    session.execute(delete(Recommendation).where(Recommendation.user_id.like("eval-test%")))
    session.execute(
        delete(RecommendationEvaluationRun).where(
            (RecommendationEvaluationRun.user_id.like("eval-test%"))
            | (RecommendationEvaluationRun.user_id.is_(None))
        )
    )
    session.execute(delete(MyRepository).where(MyRepository.id.like("eval-test/%")))
    session.execute(delete(TrendingRepository).where(TrendingRepository.id.like("eval-test/%")))
    session.execute(delete(User).where(User.id.like("eval-test%")))
    session.commit()


def _seed_repo(
    db,
    suffix: str,
    *,
    description: str = "一个用于测试的完整 Web 服务模板，包含鉴权、任务队列、缓存与可观测性。",
    tech_stack: str = "Python / FastAPI / SQLAlchemy / Redis",
    stars_today: int = 500,
) -> TrendingRepository:
    row = TrendingRepository(
        id=f"eval-test/{suffix}",
        platform="github",
        name=suffix,
        html_url=f"https://example.com/eval-test/{suffix}",
        stars_today=stars_today,
        description=description,
        tech_stack=tech_stack,
    )
    db.add(row)
    db.commit()
    return row


def _seed_rec(
    db,
    suffix: str,
    *,
    user_id: str = "eval-test-user",
    repo_id: str | None = None,
    score: float = 0.7,
    match_score: float = 0.7,
    reason: str = GOOD_REASON,
    status: str = "new",
) -> Recommendation:
    row = Recommendation(
        id=f"eval-test-rec-{suffix}",
        user_id=user_id,
        repo_id=repo_id or f"eval-test/{suffix}",
        score=score,
        match_score=match_score,
        reason=reason,
        status=status,
    )
    db.add(row)
    db.commit()
    return row


def _rows(db, user_id: str = "eval-test-user") -> dict[str, Recommendation]:
    db.expire_all()
    rows = db.execute(
        select(Recommendation).where(Recommendation.user_id == user_id)
    ).scalars().all()
    return {row.repo_id: row for row in rows}


def test_reason_quality_rewards_complete_reason() -> None:
    assert score_reason_quality(None) == 0.0
    assert score_reason_quality("") == 0.0
    short = score_reason_quality("推荐关注 demo。")
    detailed = score_reason_quality(GOOD_REASON)
    assert 0.0 < short < detailed
    assert detailed >= 0.9


def test_repo_quality_rewards_complete_metadata() -> None:
    rich = {
        "name": "demo",
        "description": "x" * 120,
        "tech_stack": "Python / FastAPI / SQLAlchemy / Redis",
        "stars_today": 1000,
        "readme_summary": "y" * 200,
        "language": "Python",
    }
    sparse = {"name": "demo"}
    assert score_repo_quality(rich) > score_repo_quality(sparse)
    assert score_repo_quality(rich) <= 1.0
    assert score_repo_quality(None) == 0.0


def test_compute_quality_score_weights() -> None:
    assert compute_quality_score(1.0, 1.0) == 1.0
    assert compute_quality_score(0.0, 0.0) == 0.0
    mixed = compute_quality_score(1.0, 0.0)
    assert 0.69 <= mixed <= 0.71


def test_evaluate_candidate_applies_match_and_quality_thresholds() -> None:
    rich = {
        "name": "demo",
        "description": "x" * 120,
        "tech_stack": "Python / FastAPI",
        "stars_today": 1000,
    }
    sparse = {"name": "demo"}

    passed = evaluate_candidate(
        match_score=0.8,
        repo=rich,
        reason=GOOD_REASON,
        match_threshold=0.35,
        quality_threshold=0.55,
    )
    assert passed.passed is True
    assert passed.detail["matchPassed"] is True
    assert passed.detail["qualityPassed"] is True

    low_match = evaluate_candidate(
        match_score=0.1,
        repo=rich,
        reason=GOOD_REASON,
        match_threshold=0.35,
        quality_threshold=0.55,
    )
    assert low_match.passed is False
    assert low_match.detail["matchPassed"] is False
    assert low_match.detail["qualityPassed"] is True

    low_quality = evaluate_candidate(
        match_score=0.9,
        repo=sparse,
        reason="",
        match_threshold=0.35,
        quality_threshold=0.55,
    )
    assert low_quality.passed is False
    assert low_quality.detail["qualityPassed"] is False


def test_evaluate_daily_marks_qualified_and_filtered(db) -> None:
    _seed_repo(db, "good")
    _seed_repo(db, "low-match")
    _seed_rec(db, "good", match_score=0.8)
    _seed_rec(db, "low-match", match_score=0.1)

    result = evaluate_daily(db, user_id="eval-test-user")

    assert result["status"] == "completed"
    assert result["total"] == 2
    assert result["qualified"] == 1
    assert result["filtered"] == 1
    rows = _rows(db)
    assert rows["eval-test/good"].status == "qualified"
    assert rows["eval-test/good"].quality_score >= 0.55
    assert rows["eval-test/good"].evaluated_at is not None
    assert rows["eval-test/good"].evaluation_run_id == result["runId"]
    detail = json.loads(rows["eval-test/good"].quality_detail or "{}")
    assert detail["passed"] is True
    assert rows["eval-test/low-match"].status == "filtered"
    assert json.loads(rows["eval-test/low-match"].quality_detail or "{}")["matchPassed"] is False


def test_evaluate_preserves_user_and_push_statuses(db) -> None:
    _seed_repo(db, "saved")
    _seed_repo(db, "dismissed")
    _seed_repo(db, "pushed")
    _seed_rec(db, "saved", status="saved")
    _seed_rec(db, "dismissed", status="dismissed")
    _seed_rec(db, "pushed", status="pushed")

    result = evaluate_daily(db, user_id="eval-test-user")

    assert result["total"] == 0
    rows = _rows(db)
    assert rows["eval-test/saved"].status == "saved"
    assert rows["eval-test/dismissed"].status == "dismissed"
    assert rows["eval-test/pushed"].status == "pushed"
    assert rows["eval-test/saved"].quality_score == 0.0


def test_evaluate_is_idempotent_and_threshold_tunable(db) -> None:
    _seed_repo(db, "tunable")
    _seed_rec(db, "tunable", match_score=0.2)

    first = evaluate_daily(db, user_id="eval-test-user")
    assert first["filtered"] == 1
    assert _rows(db)["eval-test/tunable"].status == "filtered"

    second = evaluate_daily(db, user_id="eval-test-user", match_threshold=0.05)
    assert second["qualified"] == 1
    row = _rows(db)["eval-test/tunable"]
    assert row.status == "qualified"
    assert row.evaluation_run_id == second["runId"]

    runs = db.execute(select(RecommendationEvaluationRun)).scalars().all()
    assert len(runs) == 2


def test_evaluate_skips_missing_trending_repo(db) -> None:
    _seed_rec(db, "missing", repo_id="eval-test/missing", match_score=0.9)

    result = evaluate_daily(db, user_id="eval-test-user")

    assert result["total"] == 1
    assert result["skipped"] == 1
    assert _rows(db)["eval-test/missing"].status == "new"


def test_evaluate_all_users(db) -> None:
    db.add(User(id="eval-test-a", username="a"))
    db.add(User(id="eval-test-b", username="b"))
    db.commit()
    _seed_repo(db, "a")
    _seed_repo(db, "b")
    _seed_rec(db, "a", user_id="eval-test-a", match_score=0.8)
    _seed_rec(db, "b", user_id="eval-test-b", match_score=0.1)

    result = evaluate_daily(db, user_id=None)

    assert result["userCount"] >= 2
    assert result["total"] >= 2
    assert _rows(db, "eval-test-a")["eval-test/a"].status == "qualified"
    assert _rows(db, "eval-test-b")["eval-test/b"].status == "filtered"


def test_daily_push_only_pushes_qualified(db) -> None:
    _seed_repo(db, "qualified")
    _seed_repo(db, "new")
    _seed_rec(db, "qualified", status="qualified")
    _seed_rec(db, "new", status="new")

    result = daily_push()

    assert result["pushed"] == 1
    rows = _rows(db)
    assert rows["eval-test/qualified"].status == "pushed"
    assert rows["eval-test/new"].status == "new"


def test_generation_persists_match_score_and_resets_evaluation(db) -> None:
    my = MyRepository(
        id="eval-test/my",
        platform="github",
        name="fastapi",
        description="python web framework",
        html_url="https://example.com/eval-test/my",
        stars=10,
        language="Python",
    )
    repo = TrendingRepository(
        id="eval-test/generated",
        platform="github",
        name="fastapi-demo",
        html_url="https://example.com/eval-test/generated",
        stars_today=100,
        description="python web framework",
        tech_stack="Python",
    )
    db.add_all([my, repo])
    db.commit()

    first = generate_for_user(
        db, "eval-test-gen", service=EmbeddingService(force_fallback=True), min_score=0.0
    )
    assert first["created"] == 1
    row = _rows(db, "eval-test-gen")["eval-test/generated"]
    assert row.match_score > 0
    assert row.status == "new"

    row.status = "qualified"
    row.quality_score = 0.9
    row.quality_detail = '{"passed":true}'
    row.evaluation_run_id = "old-run"
    db.commit()

    generate_for_user(
        db, "eval-test-gen", service=EmbeddingService(force_fallback=True), min_score=0.0
    )
    row = _rows(db, "eval-test-gen")["eval-test/generated"]
    assert row.status == "new"
    assert row.quality_score == 0.0
    assert row.quality_detail is None
    assert row.evaluation_run_id is None


def test_celery_task_returns_summary(db) -> None:
    _seed_repo(db, "task")
    _seed_rec(db, "task", match_score=0.8)

    result = evaluate_recommendations(user_id="eval-test-user")

    assert result["status"] == "completed"
    assert result["qualified"] == 1


def test_evaluate_run_marks_failed_when_all_users_fail(db, monkeypatch) -> None:
    import app.services.recommendation_eval as eval_mod

    def boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(eval_mod, "evaluate_for_user", boom)
    result = eval_mod.evaluate_daily(db, user_id="eval-test-user")

    assert result["status"] == "failed"
    assert result["failed"] == 1
    run = db.get(RecommendationEvaluationRun, result["runId"])
    assert run is not None
    assert run.status == "failed"
    assert "boom" in (run.error or "")


def test_sqlite_backfill_adds_missing_columns(tmp_path, monkeypatch) -> None:
    from types import SimpleNamespace

    from sqlalchemy import create_engine, inspect, text

    import app.db as db_module

    legacy = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    with legacy.begin() as connection:
        connection.execute(text("CREATE TABLE recommendations (id TEXT PRIMARY KEY)"))

    monkeypatch.setattr(db_module, "engine", legacy)
    monkeypatch.setattr(
        db_module, "settings", SimpleNamespace(DATABASE_URL="sqlite:///legacy.db")
    )
    db_module._ensure_sqlite_columns()

    inspector = inspect(legacy)
    columns = {column["name"] for column in inspector.get_columns("recommendations")}
    assert {"match_score", "quality_score", "quality_detail", "evaluation_run_id", "evaluated_at"} <= columns
    indexes = {index["name"] for index in inspector.get_indexes("recommendations")}
    assert "ix_recommendations_evaluation_run_id" in indexes


def test_api_enqueue_and_query(db) -> None:
    _seed_repo(db, "api")
    _seed_rec(db, "api", match_score=0.8)

    with TestClient(app) as client:
        enqueued = client.post(
            "/api/tasks/evaluate-recommendations",
            params={"user_id": "eval-test-user"},
        )
        assert enqueued.status_code == 202
        assert enqueued.json().get("taskId")

        runs = client.get("/api/recommend/evaluations", params={"limit": 5})
        assert runs.status_code == 200
        payload = runs.json()
        assert payload["count"] >= 1
        assert payload["items"][0]["status"] == "completed"

        qualified = client.get(
            "/api/recommend/qualified", params={"user_id": "eval-test-user"}
        )
        assert qualified.status_code == 200
        items = qualified.json()["items"]
        assert len(items) == 1
        assert items[0]["repoId"] == "eval-test/api"
        assert items[0]["qualityScore"] > 0
        assert items[0]["qualityDetail"]["passed"] is True
