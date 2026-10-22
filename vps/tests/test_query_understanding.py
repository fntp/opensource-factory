"""查询理解（同义词 / 技术栈词表）纯函数测试（REQ-202610-0928）。

不访问网络、不依赖模型；覆盖别名归一、长词优先、ASCII 词边界、去重、
扩展上限、关闭开关与词表规模。
"""
from __future__ import annotations

import pytest

from app.services.query_understanding import (
    QueryUnderstandingError,
    understand_query,
    vocabulary_stats,
)


def test_understand_expands_tech_aliases() -> None:
    result = understand_query("k8s 部署工具")
    assert result.expanded is True
    assert result.rewritten.startswith("k8s 部署工具")
    assert "Kubernetes" in result.tech_stack
    assert "部署" in result.concepts
    assert "Kubernetes" in result.terms
    assert "container orchestration" in result.terms


def test_understand_synonyms_chinese() -> None:
    result = understand_query("管理后台 脚手架")
    assert result.concepts == ("管理后台", "脚手架")
    for term in ("admin", "dashboard", "boilerplate", "starter kit"):
        assert term in result.terms
        assert term in result.rewritten


def test_understand_template_alias_and_tech() -> None:
    result = understand_query("NestJS 管理后台模板")
    assert "NestJS" in result.tech_stack
    assert "管理后台" in result.concepts
    assert "脚手架" in result.concepts
    assert "boilerplate" in result.terms


def test_understand_case_insensitive_and_deduped() -> None:
    result = understand_query("POSTGRES Postgres postgres")
    assert result.tech_stack == ("PostgreSQL",)
    assert result.terms.count("PostgreSQL") == 1
    assert result.terms.count("relational database") == 1


def test_understand_ascii_word_boundaries() -> None:
    # Go 不能命中 Google；Java 不能命中 JavaScript。
    assert understand_query("Google 搜索").tech_stack == ()
    assert "Java" not in understand_query("JavaScript 工具").tech_stack
    assert "JavaScript" in understand_query("JavaScript 工具").tech_stack
    assert understand_query("ts").tech_stack == ("TypeScript",)


def test_understand_long_alias_priority() -> None:
    result = understand_query("react native 组件库")
    assert "React Native" in result.tech_stack
    assert "React" not in result.tech_stack
    assert "组件库" in result.concepts


def test_understand_canonical_term_added_when_alias_used() -> None:
    result = understand_query("后台 工具")
    assert "管理后台" in result.concepts
    assert "管理后台" in result.terms
    assert "admin" in result.terms


def test_understand_no_match_returns_original() -> None:
    result = understand_query("一个很小众的项目")
    assert result.expanded is False
    assert result.rewritten == "一个很小众的项目"
    assert result.terms == ()
    assert result.tech_stack == ()
    assert result.keyword_terms == ("一个很小众的项目",)


def test_understand_max_terms_and_keyword_terms() -> None:
    result = understand_query("多租户 SaaS 管理后台 脚手架 支付 权限 监控", max_terms=5)
    assert len(result.terms) <= 5
    assert result.keyword_terms[0] == result.query
    assert len(result.keyword_terms) <= 8
    assert len({term.casefold() for term in result.keyword_terms}) == len(result.keyword_terms)


def test_understand_disabled_keeps_query() -> None:
    result = understand_query("k8s 部署", enabled=False)
    assert result.expanded is False
    assert result.rewritten == "k8s 部署"
    assert result.terms == ()
    assert result.keyword_terms == ("k8s 部署",)


def test_understand_empty_query_raises() -> None:
    with pytest.raises(QueryUnderstandingError):
        understand_query("   ")


def test_vocabulary_stats() -> None:
    stats = vocabulary_stats()
    assert stats["techEntries"] >= 60
    assert stats["conceptEntries"] >= 50
    assert stats["aliases"] >= 250
