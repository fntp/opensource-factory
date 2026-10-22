"""推荐理由生成：中文可读文案 + 依据字段。

设计目标：
- **纯规则、可离线**：不调用 LLM / 网络，测试与 2G 预算环境均可运行；
- **可解释**：`based_on` 只记录理由中实际引用的字段，供 edge / admin 以标签展示；
- **画像感知**：结合用户收藏的语言 / 技术栈 / 分类，说明「为什么推荐给我」；
- **冷启动安全**：收藏为空时退化为候选自身字段 + 相似度，不虚构用户偏好。

对外主要接口：
- `build_user_profile(repos, category_names=None)`：聚合用户兴趣画像；
- `build_reason_detail(repo, score, profile=None)`：返回 `ReasonDetail(reason, based_on)`；
- `build_reason(repo, score)`：兼容旧调用的纯文本理由。
"""
from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

from app.services.readme import extract_tech_stack

# 理由中提及「今日热度」的最低 stars 增量，避免噪声
_HEAT_MIN_STARS = 20
# based_on 最大条数，避免前端标签溢出
_MAX_BASIS = 6
# 简介截断长度
_DESC_LIMIT = 60

_TERM_SPLIT_RE = re.compile(r"[,，、;；|]+")
_WHITESPACE_RE = re.compile(r"\s+")

# 技术栈别名归并（与 readme.extract_tech_stack 的输出保持一致口径）
_TECH_ALIASES = {
    "golang": "Go",
    "k8s": "Kubernetes",
    "postgres": "PostgreSQL",
    "postgresql": "PostgreSQL",
    "node": "Node.js",
    "nodejs": "Node.js",
    "nextjs": "Next.js",
    "next.js": "Next.js",
}


@dataclass(frozen=True)
class UserInterestProfile:
    """用户兴趣画像（从收藏库聚合）。"""

    languages: tuple[str, ...] = ()
    tech_terms: tuple[str, ...] = ()
    categories: tuple[str, ...] = ()
    repo_count: int = 0

    @property
    def has_signal(self) -> bool:
        """是否有足够的画像信号（收藏库非空即可视为有画像）。"""
        return self.repo_count > 0


@dataclass(frozen=True)
class ReasonDetail:
    """推荐理由与依据字段。"""

    reason: str
    based_on: tuple[str, ...] = ()

    @property
    def based_on_json(self) -> str:
        """序列化为 D1 / 本地表使用的 JSON 数组字符串。"""
        return dump_based_on(self.based_on)


def _field(repo: Any, key: str, default: Any = "") -> Any:
    """兼容 dict / SQLAlchemy 模型 / 任意对象的字段读取。"""
    if isinstance(repo, Mapping):
        value = repo.get(key)
    else:
        value = getattr(repo, key, None)
    return value if value is not None else default


def _text(value: Any) -> str:
    """归一化为去空白字符串。"""
    if value is None:
        return ""
    return _WHITESPACE_RE.sub(" ", str(value)).strip()


def _canonical_term(term: str) -> str:
    """技术栈别名归一。"""
    cleaned = term.strip()
    if not cleaned:
        return ""
    return _TECH_ALIASES.get(cleaned.casefold(), cleaned)


def _split_terms(value: Any) -> list[str]:
    """拆分逗号 / 顿号 / 分号分隔的技术栈字符串，去重并保持顺序。"""
    if not value:
        return []
    if isinstance(value, (list, tuple, set)):
        raw_terms = [str(item) for item in value]
    else:
        raw_terms = _TERM_SPLIT_RE.split(str(value))
    result: list[str] = []
    seen: set[str] = set()
    for raw in raw_terms:
        term = _canonical_term(raw)
        key = term.casefold()
        if term and key not in seen:
            seen.add(key)
            result.append(term)
    return result


def _truncate(text: str, limit: int = _DESC_LIMIT) -> str:
    """按自然边界截断简介，避免半词。"""
    cleaned = _text(text)
    if len(cleaned) <= limit:
        return cleaned
    cut = cleaned[:limit]
    space = cut.rfind(" ")
    if space >= int(limit * 0.6):
        cut = cut[:space]
    return cut.rstrip("，,；;。.、 ") + "…"


def _repo_tech_terms(repo: Any) -> list[str]:
    """读取候选技术栈；字段为空时从简介 / 名称中启发式提取。"""
    terms = _split_terms(_field(repo, "tech_stack"))
    if terms:
        return terms
    text = " ".join(
        filter(
            None,
            [
                _text(_field(repo, "name")),
                _text(_field(repo, "description")),
                _text(_field(repo, "readme_summary")),
            ],
        )
    )
    return _split_terms(extract_tech_stack(text, max_items=8))


def build_user_profile(
    repos: Iterable[Any],
    category_names: Mapping[str, str] | None = None,
) -> UserInterestProfile:
    """从收藏库聚合用户画像：Top 语言 / 技术栈 / 分类。

    `category_names` 为 `category_id -> name` 映射；缺失时忽略分类信号。
    """
    repo_list = list(repos)
    languages: Counter[str] = Counter()
    tech_terms: Counter[str] = Counter()
    categories: Counter[str] = Counter()

    for repo in repo_list:
        language = _text(_field(repo, "language"))
        if language:
            languages[language] += 1

        text = " ".join(
            filter(
                None,
                [
                    _text(_field(repo, "name")),
                    _text(_field(repo, "description")),
                    _text(_field(repo, "readme_summary")),
                    language,
                ],
            )
        )
        for term in _split_terms(extract_tech_stack(text, max_items=12)):
            tech_terms[term] += 1

        category_id = _text(_field(repo, "category_id"))
        if category_id and category_names and category_id in category_names:
            category_name = _text(category_names[category_id])
            if category_name:
                categories[category_name] += 1

    return UserInterestProfile(
        languages=tuple(item for item, _ in languages.most_common(3)),
        tech_terms=tuple(item for item, _ in tech_terms.most_common(8)),
        categories=tuple(item for item, _ in categories.most_common(3)),
        repo_count=len(repo_list),
    )


def _lead(score_pct: int, profile: UserInterestProfile | None) -> str:
    """相似度分档 + 画像感知的开场句。"""
    if profile is not None and profile.has_signal:
        if score_pct >= 75:
            return f"与你收藏的项目高度相似（相似度约 {score_pct}%）"
        if score_pct >= 50:
            return f"与你的收藏方向较为接近（相似度约 {score_pct}%）"
        return f"与你的收藏有一定关联（相似度约 {score_pct}%）"
    if score_pct >= 75:
        return f"语义匹配度很高（约 {score_pct}%）"
    if score_pct >= 50:
        return f"语义匹配度较高（约 {score_pct}%）"
    return f"语义匹配度约 {score_pct}%"


def build_reason_detail(
    repo: Any,
    score: float,
    profile: UserInterestProfile | None = None,
) -> ReasonDetail:
    """生成中文推荐理由与依据字段。

    证据优先级：共同语言 → 共同技术栈 → 共同分类 → 今日热度 → 简介摘要。
    `based_on` 只包含理由中实际使用的字段。
    """
    name = _text(_field(repo, "name")) or _text(_field(repo, "id")) or "该项目"
    language = _text(_field(repo, "language"))
    description = _text(_field(repo, "description"))
    category = _text(_field(repo, "category_name")) or _text(_field(repo, "category"))
    try:
        stars_today = int(_field(repo, "stars_today", 0) or 0)
    except (TypeError, ValueError):
        stars_today = 0

    try:
        similarity = max(0.0, min(1.0, float(score)))
    except (TypeError, ValueError):
        similarity = 0.0
    score_pct = int(round(similarity * 100))

    profile_languages = {item.casefold() for item in (profile.languages if profile else ())}
    profile_tech = {item.casefold() for item in (profile.tech_terms if profile else ())}
    profile_categories = {item.casefold() for item in (profile.categories if profile else ())}

    tech_terms = _repo_tech_terms(repo)
    shared_language = bool(language and language.casefold() in profile_languages)
    shared_tech = [term for term in tech_terms if term.casefold() in profile_tech][:2]
    shared_category = bool(category and category.casefold() in profile_categories)

    clauses: list[str] = []
    basis: list[str] = [f"相似度 {score_pct}%"]

    if language:
        basis.append(f"语言 {language}")
        if shared_language and not shared_tech:
            clauses.append(f"同样使用 {language} 开发")
        elif not shared_language:
            clauses.append(f"主要使用 {language} 开发")

    if shared_tech:
        clauses.append(f"技术栈都涉及 {'、'.join(shared_tech)}")
        basis.extend(f"技术栈 {term}" for term in shared_tech)
    elif tech_terms:
        clauses.append(f"技术栈涉及 {'、'.join(tech_terms[:2])}")
        basis.extend(f"技术栈 {term}" for term in tech_terms[:2])

    if shared_category:
        clauses.append(f"同属「{category}」方向")
    if category:
        basis.append(f"分类 {category}")

    if stars_today >= _HEAT_MIN_STARS:
        clauses.append(f"今日热榜新增 {stars_today} stars")
        basis.append(f"今日 +{stars_today} stars")

    # 技术栈已能说明匹配点时不再重复简介；其余情况用简介补足可读性
    if description and not shared_tech and stars_today < _HEAT_MIN_STARS:
        clauses.append(f"项目简介：{_truncate(description)}")
        basis.append("项目简介")

    reason = _lead(score_pct, profile)
    if clauses:
        reason += "；" + "；".join(clauses)
    reason += f"。推荐关注 {name}。"

    # 去重并限制条数（保留顺序）
    deduped: list[str] = []
    seen: set[str] = set()
    for item in basis:
        if item and item not in seen:
            seen.add(item)
            deduped.append(item)

    return ReasonDetail(reason=reason, based_on=tuple(deduped[:_MAX_BASIS]))


def build_reason(repo: Any, score: float) -> str:
    """兼容旧调用：仅返回中文理由文本。"""
    return build_reason_detail(repo, score).reason


def parse_based_on(raw: Any) -> list[str]:
    """解析 based_on：兼容 JSON 数组字符串、list 与逗号分隔旧格式。"""
    if raw is None:
        return []
    if isinstance(raw, (list, tuple)):
        values: Sequence[Any] = raw
    else:
        text = str(raw).strip()
        if not text:
            return []
        try:
            parsed = json.loads(text)
        except (TypeError, ValueError):
            values = text.split(",")
        else:
            if not isinstance(parsed, list):
                return []
            values = parsed
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = str(value).strip()
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result


def dump_based_on(items: Iterable[Any]) -> str:
    """序列化为 JSON 数组字符串（中文不转义）。"""
    return json.dumps([str(item) for item in items], ensure_ascii=False)
