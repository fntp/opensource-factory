"""推荐理由生成测试：画像聚合、分档措辞、依据字段与兼容性（纯函数，无网络）。"""
from __future__ import annotations

import json

from app.services.recommend_reason import (
    build_reason,
    build_reason_detail,
    build_user_profile,
    dump_based_on,
    parse_based_on,
)


def test_build_user_profile_aggregates_language_tech_and_category() -> None:
    repos = [
        {
            "name": "alpha",
            "language": "Python",
            "description": "FastAPI 后端服务",
            "category_id": "c1",
        },
        {
            "name": "beta",
            "language": "Python",
            "description": "Django 管理后台",
            "category_id": "c1",
        },
        {"name": "gamma", "language": "TypeScript", "description": "React 前端"},
    ]
    profile = build_user_profile(repos, {"c1": "后端开发"})

    assert profile.repo_count == 3
    assert profile.languages[0] == "Python"
    assert "FastAPI" in profile.tech_terms
    assert profile.categories == ("后端开发",)
    assert profile.has_signal is True


def test_high_match_reason_uses_profile_evidence_and_basis() -> None:
    profile = build_user_profile(
        [
            {"name": "a", "language": "Python", "description": "FastAPI 服务", "category_id": "c1"},
            {"name": "b", "language": "Python", "description": "Django 后台", "category_id": "c1"},
        ],
        {"c1": "后端开发"},
    )
    repo = {
        "name": "owner/repo",
        "language": "Python",
        "tech_stack": "Python, FastAPI, Redis",
        "description": "一个支付后端",
        "category_name": "后端开发",
        "stars_today": 120,
    }

    detail = build_reason_detail(repo, 0.87, profile)

    assert "高度相似" in detail.reason
    assert "87%" in detail.reason
    assert "Python" in detail.reason
    assert "FastAPI" in detail.reason
    assert "后端开发" in detail.reason
    assert "120 stars" in detail.reason
    assert "owner/repo" in detail.reason

    assert detail.based_on[0] == "相似度 87%"
    assert "语言 Python" in detail.based_on
    assert "技术栈 Python" in detail.based_on
    assert "技术栈 FastAPI" in detail.based_on
    assert "分类 后端开发" in detail.based_on
    assert len(detail.based_on) <= 6

    parsed = json.loads(detail.based_on_json)
    assert parsed == list(detail.based_on)


def test_medium_and_low_match_wording() -> None:
    profile = build_user_profile([{"name": "a", "language": "Python"}])
    medium = build_reason_detail({"name": "m", "language": "Go"}, 0.6, profile)
    low = build_reason_detail({"name": "l", "language": "Go"}, 0.3, profile)

    assert "较为接近" in medium.reason
    assert "60%" in medium.reason
    assert "一定关联" in low.reason
    assert "30%" in low.reason
    assert medium.reason != low.reason


def test_cold_start_does_not_claim_user_preference() -> None:
    repo = {
        "name": "solo",
        "language": "Rust",
        "description": "命令行工具",
        "tech_stack": "Rust, CLI",
    }
    detail = build_reason_detail(repo, 0.9)

    assert "你的收藏" not in detail.reason
    assert "语义匹配度" in detail.reason
    assert "Rust" in detail.reason
    assert "CLI" in detail.reason
    assert detail.based_on[0] == "相似度 90%"


def test_empty_fields_still_produce_reason_and_basis() -> None:
    detail = build_reason_detail({"name": "minimal"}, 0.6)

    assert detail.reason == "语义匹配度较高（约 60%）。推荐关注 minimal。"
    assert detail.based_on == ("相似度 60%",)


def test_description_used_when_no_tech_evidence() -> None:
    repo = {
        "name": "desc-only",
        "language": "Python",
        "description": "一个用于处理支付回调的开源服务",
    }
    detail = build_reason_detail(repo, 0.7, build_user_profile([{"language": "Python"}]))

    assert "项目简介：" in detail.reason
    assert "项目简介" in detail.based_on


def test_build_reason_backwards_compatible() -> None:
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


def test_parse_and_dump_based_on() -> None:
    items = ["相似度 87%", "语言 Python"]
    raw = dump_based_on(items)
    assert json.loads(raw) == items
    assert parse_based_on(raw) == items
    assert parse_based_on("a,b, a") == ["a", "b"]
    assert parse_based_on("not-json") == ["not-json"]
    assert parse_based_on(None) == []
    assert parse_based_on('{"not": "list"}') == []
