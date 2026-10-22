"""推荐质量评估与调参测试（M3-08）。

覆盖：排序指标纯函数、抽样评估集、阈值 / 权重扫描、反馈统计、
数据不足降级与 API 契约。全部使用 hash 兜底向量与独立临时数据库，不访问网络。
"""
from __future__ import annotations

import math

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import Settings
from app.db import Base
from app.main import app
from app.models import MyRepository, Recommendation, TrendingRepository
from app.services.embedding import EmbeddingService
from app.services.recommendation_quality import (
    diversity_at_k,
    evaluate_recommendation_quality,
    feedback_metrics,
    hit_rate_at_k,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
    reciprocal_rank_at_k,
)


@pytest.fixture()
def db(tmp_path):
    """独立 SQLite 数据库，避免共享测试库中的其他数据干扰评估抽样。"""
    engine = create_engine(
        f"sqlite:///{tmp_path / 'recommendation-eval.db'}",
        connect_args={"check_same_thread": False},
        future=True,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _service() -> EmbeddingService:
    return EmbeddingService(force_fallback=True)


def _seed_my(db, index: int, *, language: str = "Python") -> MyRepository:
    row = MyRepository(
        id=f"eval-test/my-{index}",
        platform="github",
        name=f"python-framework-{index}",
        description="python web framework fastapi service",
        html_url=f"https://example.com/eval-test/my-{index}",
        stars=100 + index,
        language=language,
    )
    db.add(row)
    return row


def _seed_trending(db, index: int, *, tech_stack: str = "Rust") -> TrendingRepository:
    row = TrendingRepository(
        id=f"eval-test/trending-{index}",
        platform="github",
        name=f"rust-game-engine-{index}",
        html_url=f"https://example.com/eval-test/trending-{index}",
        stars_today=500 + index,
        description="rust game engine graphics rendering",
        tech_stack=tech_stack,
    )
    db.add(row)
    return row


def _seed_dataset(db) -> None:
    for index in range(8):
        _seed_my(db, index)
    for index in range(6):
        _seed_trending(db, index)
    db.commit()


def test_ranking_metrics_known_values() -> None:
    ranked = ["a", "b", "c", "d"]
    positives = {"b", "d"}

    assert precision_at_k(ranked, positives, 2) == pytest.approx(0.5)
    assert recall_at_k(ranked, positives, 2) == pytest.approx(0.5)
    assert hit_rate_at_k(ranked, positives, 2) == 1.0
    assert reciprocal_rank_at_k(ranked, positives, 2) == pytest.approx(0.5)

    dcg = 1 / math.log2(3) + 1 / math.log2(5)
    ideal = 1 + 1 / math.log2(3)
    assert ndcg_at_k(ranked, positives, 4) == pytest.approx(dcg / ideal)
    assert ndcg_at_k(["a", "c"], positives, 2) == 0.0

    groups = {"a": "Python", "b": "Rust", "c": "Python"}
    assert diversity_at_k(ranked, groups, 3) == pytest.approx(2 / 3)


def test_evaluate_builds_samples_and_recommends_parameters(db) -> None:
    _seed_dataset(db)

    report = evaluate_recommendation_quality(
        db,
        service=_service(),
        sample_size=3,
        top_k=5,
        holdout_ratio=0.25,
        negatives_per_positive=3,
        seed=7,
    )

    assert report["status"] == "ok"
    assert report["dataset"]["samples"] == 3
    assert report["dataset"]["positives"] > 0
    assert report["dataset"]["negatives"] > 0
    assert len(report["thresholds"]) >= 3
    assert len(report["weights"]) >= 1

    # 留出正样本与画像同主题，负样本为无关的 Rust 项目：当前阈值下应全部命中。
    assert report["metrics"]["precision"] == pytest.approx(1.0)
    assert report["metrics"]["recall"] == pytest.approx(1.0)
    assert report["metrics"]["f1"] == pytest.approx(1.0)
    assert report["metrics"]["coverage"] == pytest.approx(1.0)

    recommended = report["recommended"]
    assert 0.0 <= recommended["minScore"] <= 1.0
    assert 0.0 <= recommended["similarityWeight"] <= 1.0
    assert recommended["reason"]

    # 同一随机种子结果可复现
    again = evaluate_recommendation_quality(
        db,
        service=_service(),
        sample_size=3,
        top_k=5,
        holdout_ratio=0.25,
        negatives_per_positive=3,
        seed=7,
    )
    assert again["metrics"] == report["metrics"]
    assert again["recommended"]["minScore"] == recommended["minScore"]
    assert again["recommended"]["similarityWeight"] == recommended["similarityWeight"]


def test_high_threshold_falls_back_to_current_parameters(db) -> None:
    _seed_dataset(db)
    settings = Settings(
        RECOMMEND_EVAL_MIN_SCORE_GRID="0.90,0.95",
        RECOMMEND_EVAL_WEIGHT_GRID="0.8",
        RECOMMEND_EVAL_SAMPLE_SIZE=2,
        RECOMMEND_EVAL_TOP_K=5,
        RECOMMEND_EVAL_NEGATIVES_PER_POSITIVE=3,
        RECOMMEND_EVAL_SEED=3,
    )

    report = evaluate_recommendation_quality(db, service=_service(), settings=settings)

    assert report["status"] == "ok"
    assert all(row["avgResults"] == 0.0 for row in report["thresholds"])
    assert report["recommended"]["minScore"] == pytest.approx(settings.RECOMMEND_MIN_SCORE)
    assert report["recommended"]["improved"] is False
    assert "保留当前参数" in report["recommended"]["reason"]


def test_feedback_metrics_counts_statuses(db) -> None:
    statuses = ["saved", "saved", "dismissed", "new", "new", "pushed"]
    for index, status in enumerate(statuses):
        db.add(
            Recommendation(
                id=f"eval-test/rec-{index}",
                user_id="eval-test-user",
                repo_id=f"eval-test/repo-{index}",
                score=0.5,
                status=status,
            )
        )
    db.commit()

    stats = feedback_metrics(db, "eval-test-user")
    assert stats["total"] == 6
    assert stats["byStatus"]["saved"] == 2
    assert stats["byStatus"]["dismissed"] == 1
    assert stats["decided"] == 3
    assert stats["saveRate"] == pytest.approx(round(2 / 3, 4))
    assert stats["dismissRate"] == pytest.approx(round(1 / 3, 4))


def test_insufficient_data_returns_status_without_raising(db) -> None:
    report = evaluate_recommendation_quality(db, service=_service())

    assert report["status"] == "insufficient_data"
    assert report["warnings"]
    assert report["thresholds"] == []
    assert report["recommended"]["improved"] is False


def test_eval_api_contract() -> None:
    with TestClient(app) as client:
        resp = client.post("/api/recommend/eval", json={"sampleSize": 1, "topK": 5})
        invalid = client.post("/api/recommend/eval", json={"holdoutRatio": 1.5})

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] in {"ok", "insufficient_data"}
    for key in ("generatedAt", "config", "dataset", "metrics", "thresholds", "weights", "recommended", "feedback"):
        assert key in body
    assert invalid.status_code == 422
