"""推荐排序、综合打分与推荐理由测试（纯计算，无网络）。"""
from __future__ import annotations

import pytest

from app.services.recommender import (
    Candidate,
    build_profile_vector,
    build_reason,
    normalized_heat,
    rank_candidates,
    recommend,
    score_candidate,
)


def test_recommend_ranks_most_similar_first() -> None:
    query = [1.0, 0.0, 0.0]
    candidates = [
        ("repo-far", [0.0, 1.0, 0.0]),
        ("repo-near", [0.9, 0.1, 0.0]),
        ("repo-mid", [0.6, 0.4, 0.0]),
    ]
    ranked = recommend(query, candidates, top_k=2)
    assert [repo_id for repo_id, _ in ranked] == ["repo-near", "repo-mid"]
    assert ranked[0][1] > ranked[1][1]


def test_recommend_edge_cases() -> None:
    assert recommend([], [("a", [1.0])]) == []
    assert recommend([1.0], []) == []
    assert recommend([1.0], [("a", [1.0])], top_k=0) == []
    # 空向量候选被跳过
    assert recommend([1.0], [("a", []), ("b", [1.0])]) == [("b", 1.0)]


def test_build_reason_contains_key_fields() -> None:
    repo = {
        "name": "awesome-repo",
        "language": "Python",
        "description": "一个很棒的开源项目",
        "stars": 100,
    }
    reason = build_reason(repo, 0.87)
    assert "awesome-repo" in reason
    assert "Python" in reason
    assert "87%" in reason
    assert "一个很棒的开源项目" in reason


def test_build_reason_uses_separate_similarity() -> None:
    """综合得分与相似度分开时，理由里的百分比应使用相似度。"""
    reason = build_reason({"name": "repo"}, 0.9, similarity=0.5)
    assert "50%" in reason
    assert "90%" not in reason


def test_build_profile_vector_averages_and_normalizes() -> None:
    profile = build_profile_vector([[1.0, 0.0], [0.0, 1.0]])
    assert len(profile) == 2
    assert profile[0] == pytest.approx(0.70710678, rel=1e-6)
    assert profile[1] == pytest.approx(0.70710678, rel=1e-6)

    assert build_profile_vector([]) == []
    assert build_profile_vector([[], []]) == []
    # 维度不一致时无法平均
    assert build_profile_vector([[1.0, 0.0], [1.0, 0.0, 0.0]]) == []


def test_normalized_heat_uses_log_scale() -> None:
    assert normalized_heat(0, 100) == 0.0
    assert normalized_heat(100, 100) == 1.0
    assert 0.0 < normalized_heat(10, 100) < 1.0
    assert normalized_heat(100, 0) == 0.0
    # 负数 / 空值按 0 处理
    assert normalized_heat(-5, 100) == 0.0


def test_score_candidate_combines_similarity_and_heat() -> None:
    # 相似度 0.5、热度 1.0：0.8 * 0.5 + 0.2 * 1.0 = 0.6
    assert score_candidate(0.5, 100, 100) == pytest.approx(0.6)
    # 热度为 0 时只剩相似度权重：0.8 * 0.5 / 1.0 = 0.4
    assert score_candidate(0.5, 0, 100) == pytest.approx(0.4)
    # 相似度为负按 0 处理
    assert score_candidate(-0.5, 0, 100) == 0.0
    # 权重都为 0 时退化为纯相似度
    assert score_candidate(0.5, 100, 100, similarity_weight=0, trending_weight=0) == 0.5


def test_rank_candidates_filters_collected_threshold_and_top_k() -> None:
    profile = [1.0, 0.0, 0.0]
    candidates = [
        Candidate("near", [1.0, 0.0, 0.0], stars_today=10),
        Candidate("far", [0.0, 1.0, 0.0], stars_today=100),
        Candidate("collected", [1.0, 0.0, 0.0], stars_today=1000),
    ]
    ranked = rank_candidates(
        profile,
        candidates,
        collected_ids={"collected"},
        min_score=0.3,
        top_k=5,
    )
    assert [item.repo_id for item in ranked] == ["near"]
    assert ranked[0].score > 0.3
    assert ranked[0].similarity == pytest.approx(1.0)

    # top_k 生效
    more = [Candidate("a", [1.0, 0.0, 0.0]), Candidate("b", [0.9, 0.1, 0.0])]
    assert [item.repo_id for item in rank_candidates(profile, more, top_k=1)] == ["a"]


def test_rank_candidates_tie_break_is_stable() -> None:
    profile = [1.0, 0.0]
    candidates = [
        Candidate("repo-b", [1.0, 0.0], stars_today=50),
        Candidate("repo-a", [1.0, 0.0], stars_today=50),
    ]
    ranked = rank_candidates(profile, candidates, top_k=2)
    assert [item.repo_id for item in ranked] == ["repo-a", "repo-b"]


def test_rank_candidates_edge_cases() -> None:
    assert rank_candidates([], [Candidate("a", [1.0])]) == []
    assert rank_candidates([1.0], []) == []
    assert rank_candidates([1.0], [Candidate("a", [1.0])], top_k=0) == []
    # 空向量候选被跳过
    assert rank_candidates([1.0], [Candidate("a", [])]) == []


def test_daily_recommendation_beat_schedule_configured() -> None:
    from app.tasks.celery_app import celery_app

    entry = celery_app.conf.beat_schedule["generate-recommendations-daily"]
    assert entry["task"] == "app.tasks.jobs.generate_recommendations"
