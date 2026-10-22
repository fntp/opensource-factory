"""多轮问答式检索（M6-09）。

把单轮语义搜索升级为可连续追问的问答：

- 客户端携带会话消息（最多 20 条），服务端**无状态回放**用户轮次，得到主题 / 语言 /
  范围 / 意图 / 已展示结果；
- 检索采用「关键词 + 本地向量」混合：关键词保证新收藏在向量化前也能命中，向量提升
  语义召回；两者按 `source:repo_id` 合并取较高分；
- `my` 来源必须受调用方传入的 `myRepoIds` 白名单约束（VPS 镜像没有 user_id，用户隔离
  由 edge 负责），未传白名单时不返回任何 `my` 结果；
- 答案使用确定性模板并带 `[n]` 引用，不依赖 LLM / 网络，测试可稳定断言。
"""
from __future__ import annotations

import re
import time
from collections import Counter
from dataclasses import dataclass
from typing import Any, Iterable, Optional, Sequence

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import MyRepository, TrendingRepository
from app.services.query_understanding import QueryUnderstandingError, understand_query
from app.services.semantic_search import (
    SearchError,
    SearchHit,
    hydrate_hits,
    normalize_scope,
    search_local,
)

MAX_MESSAGES = 20
MAX_MESSAGE_LENGTH = 500
MAX_MY_REPOS = 5000
MAX_TOP_K = 20
DEFAULT_TOP_K = 8
MAX_TERMS = 12
VECTOR_MIN_SCORE = 0.15
KEYWORD_TRENDING_LIMIT = 300

SCOPE_LABELS = {"my": "你的收藏", "trending": "每日热榜", "all": "全部来源"}


class ChatError(SearchError):
    """会话参数错误。"""


@dataclass(frozen=True)
class ChatMessage:
    role: str
    content: str


@dataclass
class ChatContext:
    topic: str = ""
    language: str = ""
    scope: str = "all"
    intent: str = "list"
    turn: int = 0
    excluded: tuple[str, ...] = ()


@dataclass
class Candidate:
    source: str
    repo_id: str
    score: float
    item: dict[str, Any]
    matched_by: str


# ---------------------------------------------------------------------------
# 消息校验
# ---------------------------------------------------------------------------


def normalize_messages(raw: Iterable[Any]) -> list[ChatMessage]:
    """校验并归一化会话消息；最后一条必须是 user。"""
    messages: list[ChatMessage] = []
    for entry in raw:
        if isinstance(entry, ChatMessage):
            role, content = entry.role, entry.content
        elif isinstance(entry, dict):
            role, content = entry.get("role"), entry.get("content")
        elif hasattr(entry, "role") and hasattr(entry, "content"):
            role, content = getattr(entry, "role"), getattr(entry, "content")
        else:
            raise ChatError("消息格式非法")
        role = str(role or "").strip().lower()
        if role not in {"user", "assistant"}:
            raise ChatError("消息角色仅支持 user / assistant")
        text = " ".join(str(content or "").split())
        if not text:
            raise ChatError("消息内容不能为空")
        if len(text) > MAX_MESSAGE_LENGTH:
            raise ChatError(f"单条消息不能超过 {MAX_MESSAGE_LENGTH} 字")
        messages.append(ChatMessage(role=role, content=text))
    if not messages:
        raise ChatError("至少需要一条消息")
    if len(messages) > MAX_MESSAGES:
        raise ChatError(f"会话最多 {MAX_MESSAGES} 条消息")
    if messages[-1].role != "user":
        raise ChatError("最后一条消息必须来自用户")
    return messages


# ---------------------------------------------------------------------------
# 语言 / 范围 / 主题 / 意图解析
# ---------------------------------------------------------------------------

LANGUAGE_ALIASES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("TypeScript", ("typescript", "ts")),
    ("JavaScript", ("javascript", "js", "ecmascript")),
    ("Python", ("python", "python3", "py")),
    ("Go", ("golang", "go语言", "go 语言", "go")),
    ("Rust", ("rust", "rustlang")),
    ("Java", ("java",)),
    ("Kotlin", ("kotlin",)),
    ("Swift", ("swift",)),
    ("C++", ("c++", "cpp")),
    ("C#", ("c#", "csharp")),
    ("Ruby", ("ruby",)),
    ("PHP", ("php",)),
    ("Scala", ("scala",)),
    ("Dart", ("dart",)),
    ("Elixir", ("elixir",)),
    ("Lua", ("lua",)),
)

_MY_SCOPE_TERMS = (
    "我的收藏",
    "我收藏",
    "收藏里",
    "收藏中",
    "我的仓库",
    "我的库",
    "已收藏",
    "my collection",
    "my repos",
    "saved",
    "favorites",
)
_TRENDING_SCOPE_TERMS = ("热榜", "榜单", "趋势", "trending", "hot list")
_ALL_SCOPE_TERMS = ("全部来源", "所有来源", "全库", "全部", "所有", "all sources", "everywhere")

_TOPIC_NOISE_PATTERNS: tuple[str, ...] = (
    r"我的收藏(里|中)?",
    r"我收藏的?",
    r"收藏(里|中|库)?",
    r"我的仓库",
    r"我的库",
    r"已收藏",
    r"有哪些",
    r"有什么",
    r"有多少",
    r"多少个",
    r"几个",
    r"多少",
    r"哪些",
    r"哪个",
    r"请帮我",
    r"帮我",
    r"帮忙",
    r"麻烦",
    r"请",
    r"找一下",
    r"找一些",
    r"找找",
    r"找",
    r"查一下",
    r"查查",
    r"查",
    r"看看",
    r"看一下",
    r"列出",
    r"显示",
    r"告诉",
    r"换个话题",
    r"换一个话题",
    r"聊点别的",
    r"那么",
    r"那",
    r"这些",
    r"那些",
    r"其中",
    r"还有",
    r"再找",
    r"再来",
    r"再看",
    r"更多",
    r"其他",
    r"其它",
    r"别的",
    r"只看",
    r"只要",
    r"不限",
    r"所有",
    r"全部",
    r"来源",
    r"热榜",
    r"榜单",
    r"趋势",
    r"收藏",
    r"对比",
    r"比较",
    r"区别",
    r"第一个",
    r"第1个",
    r"这个项目",
    r"那个项目",
    r"这个",
    r"那个",
    r"它们",
    r"它",
    r"怎么样",
    r"相关",
    r"项目",
    r"仓库",
    r"开源",
    r"一下",
    r"的",
    r"里",
    r"中",
    r"和",
    r"与",
    r"及",
    r"呢",
    r"吗",
    r"啊",
    r"吧",
)

_ENGLISH_STOPWORDS = {
    "what",
    "which",
    "are",
    "is",
    "in",
    "my",
    "collection",
    "saved",
    "favorites",
    "favourite",
    "favorites",
    "project",
    "projects",
    "repo",
    "repos",
    "repository",
    "repositories",
    "related",
    "about",
    "show",
    "list",
    "me",
    "find",
    "any",
    "how",
    "many",
    "more",
    "other",
    "others",
    "please",
    "the",
    "a",
    "an",
    "of",
    "to",
    "for",
    "and",
    "or",
    "with",
    "using",
    "written",
    "language",
    "languages",
    "all",
    "sources",
    "source",
    "trending",
    "hot",
    "top",
    "compare",
    "versus",
    "vs",
    "first",
    "one",
    "this",
    "that",
    "there",
    "have",
    "has",
    "do",
    "does",
}

_PUNCTUATION_RE = re.compile(r"[，。！？、；：,.!?;:()（）\[\]【】\"“”'‘’]+")
_FOLLOWUP_RE = re.compile(
    r"(还有|再找|再来|再看|更多|其他|其它|别的|只看|只要|不限|第一个|第1个|对比|比较|区别|怎么样|呢[？?]?$)"
)


def _has_ascii(value: str) -> bool:
    return all(ord(char) < 128 for char in value)


def _alias_pattern(alias: str) -> re.Pattern[str]:
    return re.compile(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])")


def detect_language(text: str) -> tuple[str, bool]:
    """返回 (规范语言名, 是否显式提及)；「不限语言」返回 ("", True)。"""
    folded = (text or "").casefold()
    if any(word in folded for word in ("不限语言", "所有语言", "任何语言", "any language")):
        return "", True
    for canonical, aliases in LANGUAGE_ALIASES:
        for alias in aliases:
            if _has_ascii(alias):
                if _alias_pattern(alias).search(folded):
                    return canonical, True
            elif alias in folded:
                return canonical, True
    return "", False


def detect_scope(text: str) -> Optional[str]:
    folded = (text or "").casefold()
    my = any(term in folded for term in _MY_SCOPE_TERMS)
    trending = any(term in folded for term in _TRENDING_SCOPE_TERMS)
    all_scope = any(term in folded for term in _ALL_SCOPE_TERMS)
    if my and trending:
        return "all"
    if my:
        return "my"
    if trending:
        return "trending"
    if all_scope:
        return "all"
    return None


def detect_intent(text: str) -> str:
    folded = (text or "").casefold()
    if any(word in folded for word in ("多少", "几个", "数量", "count", "how many")):
        return "count"
    if any(word in folded for word in ("还有", "再找", "更多", "其他", "其它", "别的", "more", "other")):
        return "more"
    if any(word in folded for word in ("第一个", "第1个", "这个项目", "详情", "detail", "first one")):
        return "detail"
    if any(word in folded for word in ("对比", "比较", "区别", "compare", "versus", " vs ")):
        return "compare"
    return "list"


def _strip_noise(text: str) -> str:
    cleaned = _PUNCTUATION_RE.sub(" ", text or "")
    for pattern in _TOPIC_NOISE_PATTERNS:
        cleaned = re.sub(pattern, " ", cleaned, flags=re.IGNORECASE)
    for canonical, aliases in LANGUAGE_ALIASES:
        for alias in aliases:
            if _has_ascii(alias):
                cleaned = _alias_pattern(alias).sub(" ", cleaned.casefold())
            else:
                cleaned = cleaned.replace(alias, " ")
    tokens = [token for token in cleaned.split() if token and token.casefold() not in _ENGLISH_STOPWORDS]
    return " ".join(tokens).strip()


def extract_topic(text: str) -> str:
    """剔除范围 / 语言 / 疑问 / 填充词后的主题；纯追问返回空串。"""
    return _strip_noise(text)[:60]


def _is_followup(text: str) -> bool:
    return bool(_FOLLOWUP_RE.search((text or "").casefold()))


def resolve_context(messages: Sequence[ChatMessage], shown_ids: Sequence[str] = ()) -> tuple[ChatContext, str]:
    """回放用户轮次，得到本轮上下文与最后一个问题。"""
    state = ChatContext()
    last_question = ""
    for message in messages:
        if message.role != "user":
            continue
        question = message.content
        last_question = question
        explicit_scope = detect_scope(question)
        language, language_explicit = detect_language(question)
        topic = extract_topic(question)
        intent = detect_intent(question)
        followup = _is_followup(question)

        if topic:
            state.topic = topic
            if not language_explicit:
                state.language = ""
        elif not followup and not explicit_scope and not language_explicit:
            # 无法归类的独立问句：整句作为主题，避免追问到上一轮完全不相关的内容。
            fallback_topic = _strip_noise(question)
            if fallback_topic:
                state.topic = fallback_topic[:60]
                if not language_explicit:
                    state.language = ""

        if explicit_scope:
            state.scope = explicit_scope
        elif state.turn == 0:
            folded = question.casefold()
            state.scope = "my" if ("收藏" in question or "saved" in folded) else "all"

        if language_explicit:
            state.language = language

        state.intent = intent
        state.excluded = tuple(dict.fromkeys(shown_ids)) if intent == "more" else ()
        state.turn += 1

    return state, last_question


# ---------------------------------------------------------------------------
# 检索
# ---------------------------------------------------------------------------


def _chunks(values: Sequence[str], size: int) -> Iterable[Sequence[str]]:
    for index in range(0, len(values), size):
        yield values[index : index + size]


def _item_from_my(row: MyRepository) -> dict[str, Any]:
    description = row.description or row.readme_summary or ""
    return {
        "id": row.id,
        "source": "my",
        "fullName": row.id,
        "name": row.name,
        "description": description,
        "language": row.language or "",
        "stars": int(row.stars or 0),
        "starsToday": 0,
        "url": row.html_url,
        "score": 0.0,
        "reason": "",
        "citation": 0,
    }


def _item_from_trending(row: TrendingRepository) -> dict[str, Any]:
    description = row.description or row.readme_summary or ""
    return {
        "id": row.id,
        "source": "trending",
        "fullName": row.id,
        "name": row.name,
        "description": description,
        "language": row.language or "",
        "stars": int(row.stars or 0),
        "starsToday": int(row.stars_today or 0),
        "url": row.html_url,
        "score": 0.0,
        "reason": "",
        "citation": 0,
    }


def _keyword_score(text: str, terms: Sequence[str]) -> float:
    folded = text.casefold()
    matched = 0
    score = 0.0
    for index, term in enumerate(terms):
        needle = term.casefold()
        if not needle or needle not in folded:
            continue
        matched += 1
        score += 0.55 if index == 0 else 0.08
    if matched == 0:
        return 0.0
    return min(0.95, score)


def _keyword_candidates(
    db: Session,
    *,
    terms: Sequence[str],
    scope: str,
    my_repo_ids: Sequence[str],
) -> list[Candidate]:
    candidates: list[Candidate] = []
    sources = ["my", "trending"] if scope == "all" else [scope]

    if "my" in sources and my_repo_ids:
        unique_ids = list(dict.fromkeys(item for item in my_repo_ids if item))[:MAX_MY_REPOS]
        rows: list[MyRepository] = []
        for chunk in _chunks(unique_ids, 500):
            rows.extend(
                db.execute(select(MyRepository).where(MyRepository.id.in_(list(chunk)))).scalars().all()
            )
        for row in rows:
            text = " ".join(filter(None, [row.id, row.name, row.description, row.readme_summary]))
            score = _keyword_score(text, terms)
            if score <= 0:
                continue
            item = _item_from_my(row)
            item["score"] = round(score, 6)
            item["reason"] = _keyword_reason(terms[0] if terms else "", row.language or "", item["description"])
            candidates.append(Candidate("my", row.id, score, item, "keyword"))

    if "trending" in sources:
        conditions = []
        for term in terms:
            like = f"%{term}%"
            conditions.append(
                or_(
                    TrendingRepository.id.like(like),
                    TrendingRepository.name.like(like),
                    TrendingRepository.description.like(like),
                    TrendingRepository.tech_stack.like(like),
                    TrendingRepository.readme_summary.like(like),
                )
            )
        if conditions:
            stmt = (
                select(TrendingRepository)
                .where(or_(*conditions))
                .order_by(TrendingRepository.stars_today.desc())
                .limit(KEYWORD_TRENDING_LIMIT)
            )
            for row in db.execute(stmt).scalars().all():
                text = " ".join(
                    filter(None, [row.id, row.name, row.description, row.tech_stack, row.readme_summary])
                )
                score = _keyword_score(text, terms)
                if score <= 0:
                    continue
                item = _item_from_trending(row)
                item["score"] = round(score, 6)
                item["reason"] = _keyword_reason(
                    terms[0] if terms else "", row.language or "", item["description"]
                )
                candidates.append(Candidate("trending", row.id, score, item, "keyword"))

    return candidates


def _vector_candidates(
    db: Session,
    *,
    query: str,
    scope: str,
    my_repo_ids: Sequence[str],
    top_k: int,
) -> tuple[list[Candidate], str, str]:
    try:
        result = search_local(
            db,
            query,
            top_k=max(top_k * 4, 20),
            scope=scope,
            min_score=VECTOR_MIN_SCORE,
        )
    except (SearchError, QueryUnderstandingError):
        return [], "", ""
    hits = [
        SearchHit(source=item["source"], repo_id=item["repoId"], score=float(item["score"]))
        for item in result.get("items", [])
    ]
    my_set = set(my_repo_ids)
    candidates: list[Candidate] = []
    for item in hydrate_hits(db, hits):
        if item["source"] == "my" and item["id"] not in my_set:
            continue
        item["score"] = round(float(item["score"]) * 0.95, 6)
        candidates.append(Candidate(item["source"], item["id"], float(item["score"]), item, "vector"))
    return candidates, str(result.get("backend") or ""), str(result.get("model") or "")


def _keyword_reason(topic: str, language: str, description: str) -> str:
    parts = [f"与「{topic or '当前问题'}」关键词匹配。"]
    if language:
        parts.append(f"主要使用 {language} 开发；")
    if description:
        parts.append(f"项目简介：{description[:80]}。")
    return "".join(parts)


def _merge_candidates(candidates: Iterable[Candidate]) -> list[Candidate]:
    merged: dict[str, Candidate] = {}
    for candidate in candidates:
        key = f"{candidate.source}:{candidate.repo_id}"
        current = merged.get(key)
        if current is None or candidate.score > current.score:
            merged[key] = candidate
    return sorted(
        merged.values(),
        key=lambda item: (item.score, item.item.get("stars", 0), item.item.get("name", "")),
        reverse=True,
    )


# ---------------------------------------------------------------------------
# 答案与建议
# ---------------------------------------------------------------------------


def _scope_label(scope: str) -> str:
    return SCOPE_LABELS.get(scope, "全部来源")


def _language_suffix(language: str) -> str:
    return f"，语言限定为 {language}" if language else ""


def _format_item(item: dict[str, Any], index: int) -> str:
    language = item.get("language") or "未标注语言"
    stars = int(item.get("stars") or 0)
    description = (item.get("description") or "").strip()
    suffix = f"—— {description[:60]}" if description else ""
    return f"[{index}] {item.get('fullName') or item.get('name')}（{language}，★{stars}）{suffix}"


def build_answer(
    context: ChatContext,
    items: Sequence[dict[str, Any]],
    total: int,
    *,
    unfiltered_total: int = 0,
    source_counts: Optional[dict[str, int]] = None,
) -> str:
    topic = context.topic or "当前问题"
    scope_label = _scope_label(context.scope)
    language_suffix = _language_suffix(context.language)

    if total == 0:
        if context.language and unfiltered_total > 0:
            return (
                f"在{scope_label}里没有找到与「{topic}」相关且使用 {context.language} 的项目，"
                f"但其他语言有 {unfiltered_total} 个相关项目。可以说「不限语言再看看」。"
            )
        return (
            f"在{scope_label}里没有找到与「{topic}」相关的项目。"
            "可以换个关键词，或把范围放宽到全部来源。"
        )

    if context.intent == "count":
        names = "、".join(
            f"[{index}] {item.get('fullName') or item.get('name')}"
            for index, item in enumerate(items[:3], start=1)
        )
        suffix = f"例如：{names}。" if names else ""
        return f"在{scope_label}里，与「{topic}」相关的项目共有 {total} 个{language_suffix}。{suffix}"

    if context.intent == "detail" and items:
        item = items[0]
        return (
            f"当前最匹配的是 [1] {item.get('fullName') or item.get('name')}："
            f"{(item.get('description') or '暂无项目简介')[:160]}"
            f"（{item.get('language') or '未标注语言'}，★{int(item.get('stars') or 0)}）。"
        )

    if context.intent == "compare":
        counts = source_counts or {}
        my_count = int(counts.get("my", 0))
        trending_count = int(counts.get("trending", 0))
        if my_count or trending_count:
            return (
                f"与「{topic}」相关的项目：你的收藏 {my_count} 个，每日热榜 {trending_count} 个"
                f"{language_suffix}。"
                + ("收藏库更多，建议优先从收藏里挑选。" if my_count >= trending_count else "热榜更多，可以关注近期趋势。")
            )

    if context.intent == "more":
        lines = [f"继续为你找到 {total} 个与「{topic}」相关的项目{language_suffix}："]
    else:
        lines = [f"在{scope_label}里找到 {total} 个与「{topic}」相关的项目{language_suffix}："]
    lines.extend(_format_item(item, index) for index, item in enumerate(items, start=1))
    if total > len(items):
        lines.append(f"还有 {total - len(items)} 个结果，可以说「还有吗」继续查看。")
    return "\n".join(lines)


def build_suggestions(
    context: ChatContext,
    items: Sequence[dict[str, Any]],
    total: int,
    facets: dict[str, list[dict[str, Any]]],
) -> list[str]:
    topic = context.topic or "这个主题"
    suggestions: list[str] = []
    if total > len(items):
        suggestions.append("还有吗？")
    if context.language:
        suggestions.append("不限语言再看看")
    if context.scope != "my":
        suggestions.append("只看我的收藏")
    if context.scope != "trending":
        suggestions.append(f"热榜里有哪些{topic}项目？")
    languages = facets.get("languages", [])
    if languages:
        top_language = languages[0].get("name")
        if top_language and top_language != context.language:
            suggestions.append(f"只看{top_language}的")
    if items:
        suggestions.append("其中 Star 最多的是哪个？")
    unique: list[str] = []
    for suggestion in suggestions:
        if suggestion and suggestion not in unique:
            unique.append(suggestion)
    return unique[:4]


def _facets(items: Sequence[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    language_counts = Counter((item.get("language") or "未标注").strip() for item in items)
    source_counts = Counter(str(item.get("source") or "") for item in items)
    return {
        "languages": [
            {"name": name, "count": count} for name, count in language_counts.most_common(5)
        ],
        "sources": [
            {"name": name, "count": count}
            for name, count in source_counts.most_common()
            if name
        ],
    }


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------


def chat_search(
    db: Session,
    messages: Iterable[Any],
    *,
    my_repo_ids: Sequence[str] = (),
    shown_ids: Sequence[str] = (),
    top_k: int = DEFAULT_TOP_K,
    scope: Optional[str] = None,
) -> dict[str, Any]:
    """执行一轮问答检索并返回可序列化结果。"""
    started = time.perf_counter()
    normalized = normalize_messages(messages)
    context, last_question = resolve_context(normalized, shown_ids)
    effective_scope = normalize_scope(scope) if scope else normalize_scope(context.scope)
    context.scope = effective_scope

    query_text = context.topic or _strip_noise(last_question) or last_question
    if not query_text:
        raise ChatError("无法从问题中提取检索主题")
    context.topic = context.topic or query_text

    understanding = None
    try:
        understanding = understand_query(query_text, enabled=True)
        terms = [query_text, *understanding.terms, *understanding.concepts]
    except QueryUnderstandingError:
        terms = [query_text]
    deduped_terms: list[str] = []
    seen_terms: set[str] = set()
    for term in terms:
        value = str(term or "").strip()
        key = value.casefold()
        if value and key not in seen_terms:
            seen_terms.add(key)
            deduped_terms.append(value)
    terms = deduped_terms[:MAX_TERMS]

    keyword_candidates = _keyword_candidates(
        db, terms=terms, scope=effective_scope, my_repo_ids=my_repo_ids
    )
    vector_candidates, backend, model = _vector_candidates(
        db, query=query_text, scope=effective_scope, my_repo_ids=my_repo_ids, top_k=top_k
    )
    merged = _merge_candidates([*keyword_candidates, *vector_candidates])

    excluded = set(context.excluded)
    if excluded:
        merged = [item for item in merged if item.repo_id not in excluded]

    unfiltered_total = len(merged)
    if context.language:
        merged = [
            item
            for item in merged
            if (item.item.get("language") or "").casefold() == context.language.casefold()
        ]

    total = len(merged)
    page = merged[: max(1, min(MAX_TOP_K, int(top_k or DEFAULT_TOP_K)))]
    items: list[dict[str, Any]] = []
    for index, candidate in enumerate(page, start=1):
        item = dict(candidate.item)
        item["citation"] = index
        item["score"] = round(float(candidate.score), 6)
        items.append(item)

    facets = _facets([candidate.item for candidate in merged])
    source_counts = {entry["name"]: entry["count"] for entry in facets["sources"]}
    answer = build_answer(
        context,
        items,
        total,
        unfiltered_total=unfiltered_total,
        source_counts=source_counts,
    )
    suggestions = build_suggestions(context, items, total, facets)
    mode = "hybrid" if keyword_candidates and vector_candidates else (
        "vector" if vector_candidates else "keyword"
    )
    took_ms = int((time.perf_counter() - started) * 1000)

    return {
        "question": last_question,
        "answer": answer,
        "intent": context.intent,
        "scope": effective_scope,
        "topic": context.topic,
        "language": context.language,
        "filters": {
            "language": context.language,
            "concepts": list(understanding.concepts) if understanding else [],
            "terms": terms,
        },
        "count": len(items),
        "total": total,
        "items": items,
        "facets": facets,
        "suggestions": suggestions,
        "mode": mode,
        "tookMs": took_ms,
        "turn": context.turn,
        "backend": backend,
        "model": model,
    }
