"""自动打标建议服务（REQ-202610-0960 / M7-01）。

从仓库的中文摘要（M2-04）中提取可解释的标签建议：

1. 语言字段优先：直接采用 `my_repositories.language`；
2. 框架 / 业务域 / 工程属性：按本地词表做英文词边界 + 中文关键词匹配；
3. 每条建议带置信度、命中理由与证据片段，供人工确认；
4. 排除仓库已有标签，同一仓库最多返回 N 条（默认 6）。

本模块为纯本地规则，不访问网络与模型，所有函数可离线单测。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import MyRepository

# 单仓库建议条数上限
MAX_SUGGESTIONS_PER_REPO = 10
# 低于该分数的建议不返回（避免纯噪声）
MIN_SUGGESTION_SCORE = 0.55

_CATEGORY_ORDER = {"language": 0, "framework": 1, "domain": 2, "quality": 3}
_WHITESPACE_RE = re.compile(r"\s+")
# 英文别名词边界：前后不能是字母 / 数字（允许 . + # 等符号作为别名一部分）
_WORD_BOUNDARY = r"(?<![a-z0-9]){alias}(?![a-z0-9])"


@dataclass(frozen=True)
class TagRule:
    """单条标签规则。"""

    name: str
    category: str
    weight: float
    aliases: tuple[str, ...] = ()
    keywords: tuple[str, ...] = ()


# 词表：语言 / 框架 / 业务域 / 工程属性。
# 说明：英文别名使用小写；中文关键词直接做包含匹配。
TAG_RULES: tuple[TagRule, ...] = (
    # ── 语言 ──────────────────────────────────────────────────
    TagRule("TypeScript", "language", 0.35, ("typescript", "ts"), ("typescript",)),
    TagRule("JavaScript", "language", 0.35, ("javascript", "js"), ("javascript",)),
    TagRule("Python", "language", 0.35, ("python",), ("python",)),
    TagRule("Go", "language", 0.35, ("golang",), ("go 语言", "golang")),
    TagRule("Rust", "language", 0.35, ("rust",), ("rust",)),
    TagRule("Java", "language", 0.35, ("java",), ("java",)),
    TagRule("Kotlin", "language", 0.35, ("kotlin",), ("kotlin",)),
    TagRule("Swift", "language", 0.35, ("swift",), ("swift",)),
    TagRule("C++", "language", 0.35, ("c++", "cpp"), ("c++",)),
    TagRule("C#", "language", 0.35, ("c#", "csharp", ".net"), ("c#", ".net")),
    TagRule("PHP", "language", 0.35, ("php",), ("php",)),
    TagRule("Ruby", "language", 0.35, ("ruby",), ("ruby",)),
    TagRule("Scala", "language", 0.35, ("scala",), ("scala",)),
    TagRule("Elixir", "language", 0.35, ("elixir",), ("elixir",)),
    TagRule("Dart", "language", 0.35, ("dart",), ("dart",)),
    # ── 框架 ──────────────────────────────────────────────────
    TagRule("React", "framework", 0.27, ("react", "react.js"), ("react",)),
    TagRule("Vue", "framework", 0.27, ("vue", "vue.js", "vue3"), ("vue",)),
    TagRule("Next.js", "framework", 0.27, ("next.js", "nextjs"), ("next.js",)),
    TagRule("Nuxt", "framework", 0.27, ("nuxt", "nuxt.js"), ("nuxt",)),
    TagRule("Svelte", "framework", 0.27, ("svelte", "sveltekit"), ("svelte",)),
    TagRule("Angular", "framework", 0.27, ("angular",), ("angular",)),
    TagRule("Node.js", "framework", 0.27, ("node.js", "nodejs"), ("node.js",)),
    TagRule("Deno", "framework", 0.27, ("deno",), ("deno",)),
    TagRule("Bun", "framework", 0.27, ("bun",), ("bun",)),
    TagRule("FastAPI", "framework", 0.27, ("fastapi",), ("fastapi",)),
    TagRule("Django", "framework", 0.27, ("django",), ("django",)),
    TagRule("Flask", "framework", 0.27, ("flask",), ("flask",)),
    TagRule("Spring Boot", "framework", 0.27, ("spring boot", "springboot"), ("spring boot",)),
    TagRule("Ruby on Rails", "framework", 0.27, ("rails", "ruby on rails"), ("rails",)),
    TagRule("Laravel", "framework", 0.27, ("laravel",), ("laravel",)),
    TagRule("Express", "framework", 0.27, ("express", "express.js"), ("express",)),
    TagRule("NestJS", "framework", 0.27, ("nestjs", "nest.js"), ("nestjs",)),
    TagRule("Tailwind CSS", "framework", 0.27, ("tailwind", "tailwindcss"), ("tailwind",)),
    TagRule("Vite", "framework", 0.27, ("vite", "vitejs"), ("vite",)),
    TagRule("Electron", "framework", 0.27, ("electron",), ("electron",)),
    TagRule("Tauri", "framework", 0.27, ("tauri",), ("tauri",)),
    TagRule("Flutter", "framework", 0.27, ("flutter",), ("flutter",)),
    TagRule("React Native", "framework", 0.27, ("react native",), ("react native",)),
    # ── 业务域 ────────────────────────────────────────────────
    TagRule("AI/LLM", "domain", 0.23, ("ai", "llm", "gpt", "chatgpt"), ("人工智能", "大模型", "大语言模型", "生成式 ai")),
    TagRule("机器学习", "domain", 0.23, ("machine learning", "ml"), ("机器学习", "深度学习", "神经网络")),
    TagRule("数据分析", "domain", 0.23, ("data analysis", "analytics"), ("数据分析", "数据统计", "报表")),
    TagRule("数据可视化", "domain", 0.23, ("visualization", "charts"), ("数据可视化", "图表", "可视化")),
    TagRule("前端开发", "domain", 0.23, ("frontend", "front-end"), ("前端", "用户界面", "ui 组件")),
    TagRule("后端服务", "domain", 0.23, ("backend", "back-end"), ("后端", "服务端", "rest api")),
    TagRule("数据库", "domain", 0.23, ("database", "sql", "nosql"), ("数据库", "存储引擎", "查询引擎")),
    TagRule("DevOps", "domain", 0.23, ("devops", "ci/cd", "cicd"), ("持续集成", "持续交付", "运维")),
    TagRule("云原生", "domain", 0.23, ("cloud native", "kubernetes", "k8s", "docker"), ("云原生", "容器", "kubernetes")),
    TagRule("微服务", "domain", 0.23, ("microservice", "microservices"), ("微服务", "服务治理")),
    TagRule("安全", "domain", 0.23, ("security", "auth", "oauth"), ("安全", "鉴权", "认证", "加密")),
    TagRule("测试", "domain", 0.23, ("testing", "test framework"), ("测试", "单元测试", "自动化测试")),
    TagRule("监控告警", "domain", 0.23, ("monitoring", "observability"), ("监控", "告警", "可观测")),
    TagRule("爬虫", "domain", 0.23, ("crawler", "scraper", "spider"), ("爬虫", "抓取", "采集")),
    TagRule("自动化", "domain", 0.23, ("automation", "workflow"), ("自动化", "工作流", "定时任务")),
    TagRule("文档", "domain", 0.23, ("documentation", "docs"), ("文档", "知识库", "笔记")),
    TagRule("低代码", "domain", 0.23, ("low-code", "lowcode", "no-code"), ("低代码", "无代码", "可视化搭建")),
    TagRule("多租户", "domain", 0.23, ("multi-tenant", "multitenant"), ("多租户", "租户隔离")),
    TagRule("支付", "domain", 0.23, ("payment", "billing", "checkout"), ("支付", "计费", "结算", "订单")),
    TagRule("电商", "domain", 0.23, ("ecommerce", "e-commerce"), ("电商", "商城", "购物车")),
    TagRule("内容管理", "domain", 0.23, ("cms", "content management"), ("内容管理", "博客", "发布系统")),
    TagRule("即时通讯", "domain", 0.23, ("chat", "im", "messaging"), ("即时通讯", "聊天", "消息")),
    TagRule("音视频", "domain", 0.23, ("audio", "video", "media"), ("音视频", "播放器", "流媒体")),
    TagRule("区块链", "domain", 0.23, ("blockchain", "web3", "ethereum"), ("区块链", "智能合约", "web3")),
    TagRule("游戏", "domain", 0.23, ("game", "gaming"), ("游戏", "游戏引擎")),
    TagRule("桌面端", "domain", 0.23, ("desktop",), ("桌面应用", "桌面端")),
    TagRule("移动端", "domain", 0.23, ("mobile", "android", "ios"), ("移动端", "安卓", "ios 应用")),
    TagRule("命令行", "domain", 0.23, ("cli", "command line"), ("命令行", "终端工具")),
    TagRule("浏览器扩展", "domain", 0.23, ("browser extension", "chrome extension"), ("浏览器扩展", "插件")),
    TagRule("知识库", "domain", 0.23, ("knowledge base", "wiki"), ("知识库", "wiki", "文档管理")),
    TagRule("搜索", "domain", 0.23, ("search engine", "full-text search", "fts"), ("搜索", "检索", "全文搜索")),
    # ── 工程属性 ──────────────────────────────────────────────
    TagRule("开箱即用", "quality", 0.18, ("out of the box", "ready to use"), ("开箱即用", "零配置")),
    TagRule("轻量", "quality", 0.18, ("lightweight",), ("轻量", "小巧", "低占用")),
    TagRule("高性能", "quality", 0.18, ("high performance", "high-performance", "blazing fast"), ("高性能", "极速", "高吞吐")),
    TagRule("可扩展", "quality", 0.18, ("extensible", "scalable", "plugin"), ("可扩展", "插件化", "可插拔")),
    TagRule("自托管", "quality", 0.18, ("self-hosted", "selfhosted"), ("自托管", "私有化部署", "本地部署")),
    TagRule("离线可用", "quality", 0.18, ("offline", "local-first"), ("离线", "本地优先")),
)


def normalize_tag_key(name: str) -> str:
    """标签归一化：去 `#`、压缩空白、转小写，用于去重与唯一键。"""
    text = (name or "").strip().lstrip("#").strip()
    text = _WHITESPACE_RE.sub(" ", text)
    return text.lower()


def _normalize_text(text: str) -> str:
    return _WHITESPACE_RE.sub(" ", (text or "").lower()).strip()


def _alias_hit(text: str, alias: str) -> bool:
    """英文别名按词边界匹配；含符号别名（c++ / next.js）同样处理。"""
    normalized_alias = alias.strip().lower()
    if not normalized_alias:
        return False
    pattern = _WORD_BOUNDARY.format(alias=re.escape(normalized_alias))
    return re.search(pattern, text) is not None


def _first_hit(text: str, rule: TagRule) -> tuple[str, str] | None:
    """返回规则在文本中的第一个命中词与命中类型（alias / keyword）。"""
    for alias in rule.aliases:
        if _alias_hit(text, alias):
            return alias, "alias"
    for keyword in rule.keywords:
        # 中文关键词做包含匹配；英文关键词同样按词边界，避免 reactive 命中 react
        if any(ord(ch) > 127 for ch in keyword):
            if keyword.lower() in text:
                return keyword, "keyword"
        elif _alias_hit(text, keyword):
            return keyword, "alias"
    return None


def _evidence(text: str, needle: str, *, width: int = 36) -> str:
    """截取命中词前后文作为证据片段。"""
    lowered = text.lower()
    index = lowered.find(needle.lower())
    if index < 0:
        return text[: width * 2].strip()
    start = max(0, index - width)
    end = min(len(text), index + len(needle) + width)
    snippet = text[start:end].strip()
    if start > 0:
        snippet = "…" + snippet
    if end < len(text):
        snippet = snippet + "…"
    return snippet[:160]


def suggest_tags(
    summary: str,
    *,
    description: str = "",
    language: str = "",
    existing_tags: Iterable[str] = (),
    limit: int = 6,
) -> list[dict[str, Any]]:
    """从摘要中提取标签建议（纯函数）。

    - `summary` 为空时回退到 `description`，理由中标注「简介」；
    - `existing_tags` 中的标签（大小写不敏感）会被排除；
    - 返回按置信度降序、同分按类别 / 名称排序的列表。
    """
    max_items = max(1, min(int(limit or 6), MAX_SUGGESTIONS_PER_REPO))
    base_text = (summary or "").strip()
    text_source = "摘要"
    if not base_text:
        base_text = (description or "").strip()
        text_source = "简介"
    if not base_text:
        return []

    normalized_text = _normalize_text(base_text)
    normalized_language = _normalize_text(language)
    existing = {normalize_tag_key(tag) for tag in existing_tags if normalize_tag_key(tag)}

    scored: list[dict[str, Any]] = []
    for rule in TAG_RULES:
        if normalize_tag_key(rule.name) in existing:
            continue

        hits: list[str] = []
        reasons: list[str] = []
        evidence = ""

        # 语言字段直接命中
        if rule.category == "language" and normalized_language:
            language_keys = {normalize_tag_key(rule.name), *(normalize_tag_key(a) for a in rule.aliases)}
            if normalized_language in language_keys:
                hits.append(normalized_language)
                reasons.append(f"语言字段为 {rule.name}")
                evidence = f"language 字段：{language}"

        # 文本命中（语言字段已命中时仍允许补充证据，但只计一次权重）
        hit = _first_hit(normalized_text, rule)
        if hit is not None:
            term, kind = hit
            hits.append(term)
            if not reasons:
                reasons.append(f"{text_source}命中「{term}」")
            if not evidence:
                evidence = _evidence(base_text, term)

        if not hits:
            continue

        score = 0.45 + rule.weight + min(max(len(hits) - 1, 0), 3) * 0.03
        score = round(min(score, 0.98), 2)
        if score < MIN_SUGGESTION_SCORE:
            continue

        scored.append(
            {
                "name": rule.name,
                "category": rule.category,
                "score": score,
                "reason": "；".join(reasons) or f"{text_source}命中「{rule.name}」",
                "evidence": evidence or base_text[:120],
            }
        )

    scored.sort(key=lambda item: (-float(item["score"]), _CATEGORY_ORDER.get(str(item["category"]), 9), str(item["name"])))
    return scored[:max_items]


def generate_for_repositories(
    db: Session,
    *,
    repo_ids: Optional[Iterable[str]] = None,
    limit: int = 200,
    per_repo: int = 6,
) -> dict[str, Any]:
    """为当前数据库中的仓库批量生成建议（只读，不落库）。"""
    limit_value = max(1, min(int(limit or 200), 500))
    per_repo_value = max(1, min(int(per_repo or 6), MAX_SUGGESTIONS_PER_REPO))

    stmt = select(MyRepository).order_by(MyRepository.stars.desc(), MyRepository.id.asc())
    ids = [str(item).strip() for item in (repo_ids or []) if str(item).strip()]
    if ids:
        stmt = stmt.where(MyRepository.id.in_(ids))
    else:
        stmt = stmt.where(func.trim(func.coalesce(MyRepository.readme_summary, "")) != "")
    rows = list(db.execute(stmt.limit(limit_value)).scalars().all())

    items: list[dict[str, Any]] = []
    suggested = 0
    skipped = 0
    for row in rows:
        summary = (row.readme_summary or "").strip()
        if not summary:
            skipped += 1
            continue
        tags = suggest_tags(
            summary,
            description=row.description or "",
            language=row.language or "",
            limit=per_repo_value,
        )
        if tags:
            suggested += 1
            items.append({"repoId": row.id, "tags": tags})
        else:
            skipped += 1

    return {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "scanned": len(rows),
        "suggested": suggested,
        "skipped": skipped,
        "items": items,
    }
