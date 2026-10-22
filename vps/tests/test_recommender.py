"""推荐排序与推荐理由测试（纯计算，无网络）。"""
from __future__ import annotations

from app.services.recommender import build_reason, recommend


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
