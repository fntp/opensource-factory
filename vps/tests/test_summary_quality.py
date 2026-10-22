"""摘要质量评分与抽检测试（无网络）。"""
from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.config import get_settings
from app.db import SessionLocal, init_db
from app.main import app
from app.models import MyRepository, SummaryQualitySample, TrendingRepository
from app.services import summary_quality
from app.services.summary_pipeline import RepoSummaryOutcome, summarize_repositories

GOOD_SUMMARY = (
    "这个项目是一个开源项目工厂，提供 GitHub 仓库同步、中文摘要生成与智能推荐功能。"
    "基于 Python FastAPI 与 React 技术栈实现，适合开发者团队管理个人开源资产。"
)


def _cleanup_samples(batch_id: str) -> None:
    db = SessionLocal()
    try:
        rows = db.execute(
            select(SummaryQualitySample).where(SummaryQualitySample.batch_id == batch_id)
        ).scalars().all()
        for row in rows:
            db.delete(row)
        db.commit()
    finally:
        db.close()


def test_evaluate_good_summary_passes() -> None:
    report = summary_quality.evaluate_summary(GOOD_SUMMARY, max_chars=800, source="ollama")
    assert report.verdict == "pass"
    assert report.score >= 70
    assert all(check.passed for check in report.checks)


def test_evaluate_fallback_is_failed_and_capped() -> None:
    report = summary_quality.evaluate_summary(
        "（LLM 暂不可用，以下为项目原文截断）\n" + GOOD_SUMMARY,
        max_chars=800,
        source="truncated",
    )
    assert report.verdict == "fail"
    assert report.score <= 40
    fallback = next(check for check in report.checks if check.key == "no_fallback")
    assert fallback.passed is False


def test_evaluate_english_summary_fails_chinese_check() -> None:
    report = summary_quality.evaluate_summary(
        "A fast web framework for building APIs with Python and TypeScript.",
        max_chars=800,
        source="ollama",
    )
    assert report.verdict == "fail"
    chinese = next(check for check in report.checks if check.key == "chinese")
    assert chinese.passed is False


def test_should_sample_is_deterministic_and_forces_low_score() -> None:
    kwargs = {"batch_id": "batch-x", "repo_source": "my", "repo_id": "owner/repo"}
    first = summary_quality.should_sample(**kwargs, rate=0.5, score=100)
    for _ in range(5):
        assert summary_quality.should_sample(**kwargs, rate=0.5, score=100) == first
    assert summary_quality.should_sample(**kwargs, rate=1.0, score=100) is True
    assert summary_quality.should_sample(**kwargs, rate=0.0, score=100) is False
    assert summary_quality.should_sample(**kwargs, rate=0.0, score=10) is True


def test_record_quality_sample_dedupes_by_batch_and_repo() -> None:
    init_db()
    batch_id = f"test-{uuid4().hex[:8]}"
    db = SessionLocal()
    try:
        report = summary_quality.evaluate_summary(GOOD_SUMMARY, source="ollama")
        first = summary_quality.record_quality_sample(
            db,
            batch_id=batch_id,
            repo_id="owner/demo",
            repo_source="my",
            summary=GOOD_SUMMARY,
            source="ollama",
            model="test-model",
            max_chars=800,
            report=report,
        )
        db.commit()
        second = summary_quality.record_quality_sample(
            db,
            batch_id=batch_id,
            repo_id="owner/demo",
            repo_source="my",
            summary=GOOD_SUMMARY + "（更新）",
            source="ollama",
            model="test-model",
            max_chars=800,
            report=report,
        )
        db.commit()
        count = db.execute(
            select(func.count()).select_from(SummaryQualitySample).where(
                SummaryQualitySample.batch_id == batch_id
            )
        ).scalar()
    finally:
        db.close()
    assert first.id == second.id
    assert count == 1
    _cleanup_samples(batch_id)


def test_sample_existing_summaries_backfills() -> None:
    init_db()
    batch_id = f"backfill-{uuid4().hex[:8]}"
    repo_id = f"owner/existing-{uuid4().hex[:8]}"
    db = SessionLocal()
    try:
        db.add(
            MyRepository(
                id=repo_id,
                platform="github",
                name="existing",
                html_url=f"https://github.com/{repo_id}",
                readme_summary=GOOD_SUMMARY,
            )
        )
        db.commit()
        stats = summary_quality.sample_existing_summaries(
            db, source="my", limit=10, rate=1.0, batch_id=batch_id
        )
        assert stats["total"] >= 1
        assert stats["sampled"] >= 1
        assert stats["batchId"] == batch_id
        db.delete(db.get(MyRepository, repo_id))
        db.commit()
    finally:
        db.close()
    _cleanup_samples(batch_id)


def test_summarize_trending_persists_summary_and_sample(monkeypatch) -> None:
    init_db()
    repo_id = f"owner/trending-{uuid4().hex[:8]}"
    batch_id = f"task-{uuid4().hex[:8]}"
    settings = get_settings()
    monkeypatch.setattr(settings, "SUMMARY_SAMPLE_RATE", 1.0)
    monkeypatch.setattr(settings, "SUMMARY_SAMPLE_MAX_PER_RUN", 10)

    db = SessionLocal()
    try:
        db.add(
            TrendingRepository(
                id=repo_id,
                platform="github",
                name="trending-demo",
                html_url=f"https://github.com/{repo_id}",
                stars_today=100,
                description="demo",
            )
        )
        db.commit()
    finally:
        db.close()

    def fake_summarize_one(repo_id: str, *, token: str = "", max_chars: int = 800):
        return RepoSummaryOutcome(repo_id=repo_id, summary=GOOD_SUMMARY, source="ollama")

    monkeypatch.setattr("app.services.summary_pipeline.summarize_one", fake_summarize_one)
    monkeypatch.setattr(
        "app.services.summary_pipeline.writeback_summaries",
        lambda items, **kwargs: {"status": "skipped", "reason": "test"},
    )

    stats = summarize_repositories(
        source="trending",
        repo_ids=[repo_id],
        batch_id=batch_id,
        batch_size=10,
        sleep_fn=lambda _: None,
    )
    assert stats["status"] == "ok"
    assert stats["summarized"] == 1
    assert stats["sampled"] == 1

    db = SessionLocal()
    try:
        row = db.get(TrendingRepository, repo_id)
        assert row is not None and row.readme_summary == GOOD_SUMMARY
        sample = db.execute(
            select(SummaryQualitySample).where(SummaryQualitySample.batch_id == batch_id)
        ).scalar_one()
        assert sample.repo_source == "trending"
        assert sample.status == "pending"
        db.delete(sample)
        db.delete(row)
        db.commit()
    finally:
        db.close()


def test_quality_api_list_review_and_stats() -> None:
    init_db()
    batch_id = f"api-{uuid4().hex[:8]}"
    db = SessionLocal()
    try:
        report = summary_quality.evaluate_summary(GOOD_SUMMARY, source="ollama")
        sample = summary_quality.record_quality_sample(
            db,
            batch_id=batch_id,
            repo_id="owner/api-demo",
            repo_source="my",
            summary=GOOD_SUMMARY,
            source="ollama",
            model="test-model",
            max_chars=800,
            report=report,
        )
        db.commit()
        sample_id = sample.id
    finally:
        db.close()

    with TestClient(app) as client:
        listing = client.get("/api/summaries/quality/samples", params={"batchId": batch_id})
        assert listing.status_code == 200
        body = listing.json()
        assert body["total"] == 1
        assert body["items"][0]["repoId"] == "owner/api-demo"
        assert body["items"][0]["checks"]

        reviewed = client.post(
            f"/api/summaries/quality/samples/{sample_id}/review",
            json={"result": "passed", "reviewer": "tester", "note": "OK"},
        )
        assert reviewed.status_code == 200
        assert reviewed.json()["status"] == "passed"
        assert reviewed.json()["reviewer"] == "tester"

        stats = client.get("/api/summaries/quality/stats")
        assert stats.status_code == 200
        stats_body = stats.json()
        assert stats_body["total"] >= 1
        assert "passRate" in stats_body

    _cleanup_samples(batch_id)
