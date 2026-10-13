"""README 清洗与技术栈提取测试（纯函数，无网络）。"""
from __future__ import annotations

from app.services.readme import clean_readme, extract_tech_stack


def test_clean_readme_strips_comments_badges_images_and_html() -> None:
    md = "\n".join(
        [
            "<!-- 这是一段注释，应该被移除 -->",
            "# OpenFactory",
            "",
            "[![Build Status](https://img.shields.io/badge/build-passing-green)](https://ci.example.com)",
            "![架构图](https://example.com/arch.png)",
            '<div align="center"><b>一些说明文字</b></div>',
            "",
            "正文段落。",
        ]
    )
    cleaned = clean_readme(md)
    assert "这是一段注释" not in cleaned
    assert "img.shields.io" not in cleaned
    assert "arch.png" not in cleaned
    assert "<div" not in cleaned
    assert "<b>" not in cleaned
    assert "一些说明文字" in cleaned  # HTML 标签移除，文字保留
    assert "正文段落" in cleaned
    assert "OpenFactory" in cleaned


def test_clean_readme_strips_fence_language_and_collapses_blank_lines() -> None:
    md = "标题\n\n\n\n```python\nprint('hi')\n```\n\n\n\n结尾"
    cleaned = clean_readme(md)
    assert "```python" not in cleaned
    assert "```\nprint('hi')" in cleaned
    assert "\n\n\n" not in cleaned
    assert cleaned.startswith("标题")
    assert cleaned.endswith("结尾")


def test_clean_readme_empty_input() -> None:
    assert clean_readme("") == ""
    assert clean_readme(None) == ""  # type: ignore[arg-type]


def test_extract_tech_stack_finds_keywords() -> None:
    text = (
        "使用 Python + FastAPI 构建后端服务，前端采用 Vue 和 TypeScript，"
        "数据层使用 PostgreSQL 与 Redis，部署在 Docker 中。"
    )
    stack = extract_tech_stack(text)
    for keyword in ("Python", "FastAPI", "Vue", "TypeScript", "PostgreSQL", "Redis", "Docker"):
        assert keyword in stack


def test_extract_tech_stack_no_false_positive() -> None:
    assert extract_tech_stack("谷歌搜索很好用") == ""
    keywords = extract_tech_stack("We love Google and Django").split(", ")
    assert "Go" not in keywords  # "Go" 不应命中 "Google"
    assert "Django" in keywords
