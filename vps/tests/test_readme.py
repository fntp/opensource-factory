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


def test_clean_readme_strips_complex_badges_and_reference_images() -> None:
    md = "\n".join(
        [
            "[![CI](https://img.shields.io/github/actions/workflow/status/a/b/ci.yml?branch=main&logo=github)](https://github.com/a/b/actions)",
            "[![npm](https://img.shields.io/npm/v/pkg.svg)](https://www.npmjs.com/package/pkg)",
            "![截图](https://example.com/image_(1).png \"标题\")",
            "[![ref badge][badge-img]][badge-link]",
            "![ref image][img-ref]",
            "",
            "正文。",
            "",
            "[badge-img]: https://img.shields.io/badge/x-y-z",
            "[badge-link]: https://example.com",
            "[img-ref]: https://example.com/a.png",
        ]
    )
    cleaned = clean_readme(md)
    assert "img.shields.io" not in cleaned
    assert "image_(1).png" not in cleaned
    assert "badge-img" not in cleaned
    assert "img-ref" not in cleaned
    assert "https://example.com" not in cleaned
    assert "正文。" in cleaned


def test_clean_readme_strips_script_style_svg_blocks_and_keeps_text() -> None:
    md = "\n".join(
        [
            "<script>alert('x')</script>",
            "<style>.a { color: red; }</style>",
            '<svg><path d="M0 0"/></svg>',
            '<p align="center"><a href="https://ci.example.com"><img src="https://img.shields.io/badge.svg" alt="CI"></a></p>',
            "<p>正文 <strong>加粗</strong><br>下一行</p>",
        ]
    )
    cleaned = clean_readme(md)
    assert "alert" not in cleaned
    assert "color: red" not in cleaned
    assert "M0 0" not in cleaned
    assert "img.shields.io" not in cleaned
    assert "ci.example.com" not in cleaned
    assert "正文 加粗" in cleaned
    assert "下一行" in cleaned


def test_clean_readme_decodes_entities_and_unwraps_links() -> None:
    md = "\n".join(
        [
            "A &amp; B&nbsp;C",
            "[文档](https://example.com/docs) 与 [引用][ref]",
            "",
            "---",
            "",
            "[ref]: https://example.com/ref",
        ]
    )
    cleaned = clean_readme(md)
    assert "A & B C" in cleaned
    assert "文档" in cleaned
    assert "引用" in cleaned
    assert "https://example.com" not in cleaned
    assert "---" not in cleaned


def test_clean_readme_strips_fence_language_and_collapses_blank_lines() -> None:
    md = "标题\n\n\n\n```python\nprint('hi')\n```\n\n\n\n结尾"
    cleaned = clean_readme(md)
    assert "```python" not in cleaned
    assert "```\nprint('hi')" in cleaned
    assert "\n\n\n" not in cleaned
    assert cleaned.startswith("标题")
    assert cleaned.endswith("结尾")


def test_clean_readme_is_idempotent() -> None:
    md = "\n".join(
        [
            "<!-- c -->",
            "[![badge](https://img.shields.io/badge.svg)](https://example.com)",
            "<p>正文 &amp; 更多</p>",
            "```js",
            "console.log('hi')",
            "```",
        ]
    )
    once = clean_readme(md)
    assert clean_readme(once) == once


def test_clean_readme_truncates_on_natural_boundary() -> None:
    cleaned = clean_readme("第一段。第二段。第三段。" * 20, max_chars=20)
    assert cleaned.endswith("…")
    assert len(cleaned) <= 21
    assert "第一段。" in cleaned


def test_clean_readme_strips_bom_and_zero_width_chars() -> None:
    cleaned = clean_readme("\ufeff标题\u200b\n\n正文")
    assert cleaned == "标题\n\n正文"


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


def test_extract_tech_stack_normalizes_aliases() -> None:
    stack = extract_tech_stack("后端 Golang + PostgreSQL，部署 K8s，前端 Next.js 与 React。")
    items = stack.split(", ")
    assert "Go" in items
    assert "Golang" not in items
    assert "Kubernetes" in items
    assert "K8s" not in items
    assert "PostgreSQL" in items
    assert "Next.js" in items
    assert "React" in items


def test_extract_tech_stack_no_false_positive() -> None:
    assert extract_tech_stack("谷歌搜索很好用") == ""
    assert extract_tech_stack("Please go to the docs and react to issues.") == ""
    keywords = extract_tech_stack("We love Google and Django").split(", ")
    assert "Go" not in keywords  # "Go" 不应命中 "Google"
    assert "Django" in keywords


def test_extract_tech_stack_language_has_priority() -> None:
    text = "A project using Django and Redis. " * 20 + "Written in Go."
    stack = extract_tech_stack(text, max_items=3, language="Go")
    assert stack.split(", ")[0] == "Go"


def test_extract_tech_stack_topics_and_max_items() -> None:
    stack = extract_tech_stack("A tool for developers.", max_items=3, topics=["kubernetes", "docker"])
    items = stack.split(", ")
    assert items[:2] == ["Docker", "Kubernetes"] or items[:2] == ["Kubernetes", "Docker"]
    assert len(items) == 2


def test_extract_tech_stack_frequency_order() -> None:
    stack = extract_tech_stack("Docker " * 5 + "Python", max_items=2)
    assert stack.split(", ")[0] == "Docker"


def test_extract_tech_stack_chinese_keywords() -> None:
    stack = extract_tech_stack("一个机器学习与分布式爬虫项目")
    assert "机器学习" in stack
    assert "分布式" in stack
    assert "爬虫" in stack
