"""Agent 工作流服务（REQ-202610-0968 / M7-09）。

把 M7-01 标签建议、M7-02 分类建议与 M7-03 报告能力串成一条确定性工作流：

1. ``plan_workflow`` 生成可回放的执行计划（盘点 → 整理标签 → 整理分类 → 草稿）；
2. ``build_draft`` 基于当前收藏快照生成 Markdown 精选草稿；
3. ``build_agent_response`` 组装 VPS 内部接口响应。

本模块不访问网络、不依赖 LLM，便于单测与降级；edge 侧在 VPS 不可达时
会使用同构的本地规则生成计划与草稿。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Literal

AgentTemplate = Literal["organize", "draft", "full"]
AgentMode = Literal["preview", "apply"]


@dataclass(frozen=True)
class RepoSnapshot:
    """当前用户的一个收藏仓库快照。"""

    repo_id: str
    name: str = ""
    description: str = ""
    language: str = ""
    stars: int = 0
    category: str = ""
    tags: tuple[str, ...] = field(default_factory=tuple)
    summary: str = ""

    @property
    def display_name(self) -> str:
        return self.name or self.repo_id

    @property
    def url(self) -> str:
        return f"https://github.com/{self.repo_id}"


@dataclass(frozen=True)
class ActionSnapshot:
    """一条待处理 / 已应用的标签或分类建议。"""

    kind: Literal["tag", "category"]
    repo_id: str
    value: str
    score: float = 0.0
    reason: str = ""


def _clamp_threshold(value: float | None) -> float:
    if value is None:
        return 0.75
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.75
    return max(0.5, min(1.0, round(number, 2)))


def _normalize_template(value: str | None) -> AgentTemplate:
    if value in ("organize", "draft", "full"):
        return value  # type: ignore[return-value]
    return "draft"


def _normalize_mode(value: str | None) -> AgentMode:
    return "apply" if value == "apply" else "preview"


def _actionable(actions: Iterable[ActionSnapshot], threshold: float) -> list[ActionSnapshot]:
    return [item for item in actions if item.score >= threshold]


def _language_distribution(repos: Iterable[RepoSnapshot]) -> list[tuple[str, int]]:
    counts: dict[str, int] = {}
    stars: dict[str, int] = {}
    for repo in repos:
        language = (repo.language or "").strip()
        if not language:
            continue
        counts[language] = counts.get(language, 0) + 1
        stars[language] = stars.get(language, 0) + max(0, int(repo.stars or 0))
    return sorted(counts.items(), key=lambda item: (-item[1], -stars.get(item[0], 0), item[0]))


def _tag_distribution(repos: Iterable[RepoSnapshot]) -> list[tuple[str, int]]:
    counts: dict[str, int] = {}
    for repo in repos:
        for tag in repo.tags:
            name = tag.strip()
            if not name:
                continue
            counts[name] = counts.get(name, 0) + 1
    return sorted(counts.items(), key=lambda item: (-item[1], item[0]))


def compute_stats(repos: Iterable[RepoSnapshot]) -> dict[str, Any]:
    """汇总收藏概览，供计划与草稿共用。"""
    items = list(repos)
    categories = {repo.category.strip() for repo in items if repo.category.strip()}
    languages = {repo.language.strip() for repo in items if repo.language.strip()}
    tags = {tag.strip() for repo in items for tag in repo.tags if tag.strip()}
    return {
        "totalRepos": len(items),
        "totalStars": sum(max(0, int(repo.stars or 0)) for repo in items),
        "categoryCount": len(categories),
        "languageCount": len(languages),
        "tagCount": len(tags),
        "topLanguage": _language_distribution(items)[0][0] if languages else None,
        "topCategory": sorted(categories)[0] if categories else None,
    }


def plan_workflow(
    template: AgentTemplate,
    repos: Iterable[RepoSnapshot],
    pending_tags: Iterable[ActionSnapshot],
    pending_categories: Iterable[ActionSnapshot],
    threshold: float | None = None,
    mode: AgentMode = "preview",
) -> list[dict[str, Any]]:
    """生成执行计划步骤；步骤只描述将要做什么，不代表已经写入。"""
    repo_list = list(repos)
    threshold_value = _clamp_threshold(threshold)
    tags = _actionable(pending_tags, threshold_value)
    categories = _actionable(pending_categories, threshold_value)
    organize = template in ("organize", "full")

    steps: list[dict[str, Any]] = [
        {
            "key": "inventory",
            "title": "盘点收藏",
            "detail": f"扫描 {len(repo_list)} 个收藏仓库，读取分类、标签与摘要覆盖。",
            "count": len(repo_list),
            "status": "ready" if repo_list else "skipped",
        }
    ]

    if organize:
        steps.append(
            {
                "key": "tags",
                "title": "整理标签",
                "detail": (
                    f"{len(tags)} 条标签建议达到阈值 {threshold_value:.2f}，"
                    + ("将写入 tags / repo_tags。" if mode == "apply" else "先生成预览，不写入。")
                ),
                "count": len(tags),
                "status": "ready" if tags else "skipped",
            }
        )
        steps.append(
            {
                "key": "categories",
                "title": "整理分类",
                "detail": (
                    f"{len(categories)} 条分类建议达到阈值 {threshold_value:.2f}，"
                    + ("将写入仓库分类。" if mode == "apply" else "先生成预览，不写入。")
                ),
                "count": len(categories),
                "status": "ready" if categories else "skipped",
            }
        )
    else:
        steps.append(
            {
                "key": "organize",
                "title": "整理建议",
                "detail": "当前模板只生成草稿，不处理标签 / 分类建议。",
                "count": 0,
                "status": "skipped",
            }
        )

    steps.append(
        {
            "key": "draft",
            "title": "生成草稿",
            "detail": f"基于 {len(repo_list)} 个收藏生成一份可编辑的 Markdown 精选草稿。",
            "count": len(repo_list),
            "status": "ready" if repo_list else "skipped",
        }
    )
    return steps


def _format_stars(value: int) -> str:
    number = max(0, int(value or 0))
    if number >= 10000:
        return f"{number / 10000:.1f} 万"
    if number >= 1000:
        return f"{number / 1000:.1f}k"
    return str(number)


def _escape_markdown(text: str) -> str:
    """转义会破坏标题 / 列表结构的字符，保留中文与常规标点。"""
    result = text.replace("\\", "\\\\")
    for char in ("[", "]", "(", ")", "#", "*", "_", "|", "`"):
        result = result.replace(char, f"\\{char}")
    return result.strip()


def _repo_line(repo: RepoSnapshot) -> str:
    name = _escape_markdown(repo.display_name)
    parts: list[str] = []
    if repo.language:
        parts.append(repo.language)
    parts.append(f"⭐ {_format_stars(repo.stars)}")
    meta = " · ".join(parts)
    description = _escape_markdown(repo.description or repo.summary or "暂无简介")
    tags = " ".join(f"#{_escape_markdown(tag)}" for tag in repo.tags[:4] if tag.strip())
    suffix = f" {tags}" if tags else ""
    return f"- [{name}]({repo.url}) — {description}（{meta}）{suffix}"


def build_draft(
    template: AgentTemplate,
    repos: Iterable[RepoSnapshot],
    *,
    stats: dict[str, Any] | None = None,
    applied_tags: Iterable[ActionSnapshot] = (),
    applied_categories: Iterable[ActionSnapshot] = (),
    focus: str | None = None,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    """生成确定性的 Markdown 收藏精选草稿。"""
    repo_list = sorted(list(repos), key=lambda item: (-int(item.stars or 0), item.repo_id))
    summary_stats = stats or compute_stats(repo_list)
    tags_applied = list(applied_tags)
    categories_applied = list(applied_categories)
    now = generated_at or datetime.now(timezone.utc)
    date_text = now.strftime("%Y-%m-%d")

    title_focus = (focus or "").strip()
    title = f"{title_focus} · 收藏精选草稿" if title_focus else f"我的开源收藏精选 · {date_text}"

    languages = _language_distribution(repo_list)
    tags = _tag_distribution(repo_list)
    top_repos = repo_list[:3]

    lines: list[str] = [
        f"# {title}",
        "",
        f"> 由 OpenFactory Agent 基于 {len(repo_list)} 个收藏生成于 {date_text}；"
        f"模板 `{template}`，可在发布前自由编辑。",
        "",
        "## 概览",
        "",
        f"- 收藏总数：{summary_stats.get('totalRepos', len(repo_list))}",
        f"- Star 合计：{_format_stars(int(summary_stats.get('totalStars') or 0))}",
        f"- 分类数：{summary_stats.get('categoryCount', 0)}",
        f"- 语言数：{summary_stats.get('languageCount', 0)}",
        f"- 标签数：{summary_stats.get('tagCount', 0)}",
        "",
    ]

    if languages:
        language_text = "、".join(f"{name}（{count}）" for name, count in languages[:5])
        lines.extend([f"主要语言：{language_text}", ""])
    if tags:
        tag_text = "、".join(f"#{name}（{count}）" for name, count in tags[:8])
        lines.extend([f"高频标签：{tag_text}", ""])

    lines.extend(["## 本期亮点", ""])
    if top_repos:
        for index, repo in enumerate(top_repos, 1):
            lines.append(
                f"{index}. **{_escape_markdown(repo.display_name)}** — "
                f"{_escape_markdown(repo.description or repo.summary or '暂无简介')}"
            )
    else:
        lines.append("- 收藏库还是空的，先同步一些项目再来生成草稿。")
    lines.append("")

    lines.extend(["## 分类精选", ""])
    grouped: dict[str, list[RepoSnapshot]] = {}
    for repo in repo_list:
        key = (repo.category or "未分类").strip() or "未分类"
        grouped.setdefault(key, []).append(repo)
    if grouped:
        for category in sorted(grouped, key=lambda name: (-len(grouped[name]), name)):
            items = grouped[category]
            lines.extend([f"### {_escape_markdown(category)}（{len(items)}）", ""])
            for repo in items[:8]:
                lines.append(_repo_line(repo))
            if len(items) > 8:
                lines.append(f"- …另有 {len(items) - 8} 个项目")
            lines.append("")
    else:
        lines.extend(["暂无收藏项目。", ""])

    lines.extend(["## 本次整理", ""])
    if tags_applied or categories_applied:
        lines.append(f"- 应用标签建议 {len(tags_applied)} 条")
        for action in tags_applied[:10]:
            lines.append(f"  - `{action.repo_id}` → #{_escape_markdown(action.value)}")
        lines.append(f"- 应用分类建议 {len(categories_applied)} 条")
        for action in categories_applied[:10]:
            lines.append(f"  - `{action.repo_id}` → {_escape_markdown(action.value)}")
    else:
        lines.append("- 本次未自动应用标签 / 分类建议（预览模式或没有达到阈值的建议）。")
    lines.append("")

    lines.extend(
        [
            "## 发布清单",
            "",
            "- [ ] 核对项目描述与链接",
            "- [ ] 补充一段个人点评",
            "- [ ] 选择发布渠道（博客 / 周报 / 社群）",
            "",
        ]
    )

    highlights = [
        f"收藏 {len(repo_list)} 个项目，累计 {_format_stars(int(summary_stats.get('totalStars') or 0))} Star",
        f"覆盖 {summary_stats.get('categoryCount', 0)} 个分类、{summary_stats.get('languageCount', 0)} 种语言",
        f"整理动作：标签 {len(tags_applied)} 条、分类 {len(categories_applied)} 条",
    ]

    return {
        "title": title,
        "markdown": "\n".join(lines).strip() + "\n",
        "highlights": highlights,
        "stats": summary_stats,
    }


def build_agent_response(
    *,
    template: str | None,
    mode: str | None,
    threshold: float | None,
    repos: Iterable[RepoSnapshot],
    pending_tags: Iterable[ActionSnapshot] = (),
    pending_categories: Iterable[ActionSnapshot] = (),
    applied_tags: Iterable[ActionSnapshot] = (),
    applied_categories: Iterable[ActionSnapshot] = (),
    focus: str | None = None,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    """组装内部接口响应：计划 + 草稿 + 统计。"""
    normalized_template = _normalize_template(template)
    normalized_mode = _normalize_mode(mode)
    threshold_value = _clamp_threshold(threshold)
    repo_list = list(repos)
    stats = compute_stats(repo_list)
    plan = plan_workflow(
        normalized_template,
        repo_list,
        pending_tags,
        pending_categories,
        threshold_value,
        normalized_mode,
    )
    draft = build_draft(
        normalized_template,
        repo_list,
        stats=stats,
        applied_tags=applied_tags,
        applied_categories=applied_categories,
        focus=focus,
        generated_at=generated_at,
    )
    now = generated_at or datetime.now(timezone.utc)
    return {
        "template": normalized_template,
        "mode": normalized_mode,
        "threshold": threshold_value,
        "plan": plan,
        "draft": draft,
        "stats": stats,
        "generatedAt": now.isoformat(),
    }
