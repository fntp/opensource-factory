"""重复 / 相似项目检测与合并建议（M6-03）。

在收藏库与热榜的本地镜像中识别「同一个项目被重复收录」的条目：

- 地址归一化：`html_url` / `repo_id` 去协议、域名、`.git`、大小写与尾斜杠；
- 名称相似：归一化名称的 token Jaccard 与字符序列相似度取大；
- 简介相似：中英文 token（中文按 bigram）Jaccard；
- 向量复核：同 model + dim 的余弦相似度，仅用于提升 / 降低置信度，不单独判重；
- 并查集聚类后选出保留条目，输出字段级合并建议。

检测是只读的：本模块不会删除、改写任何仓库；合并动作由用户在控制台确认后人工执行。
"""
from __future__ import annotations

import hashlib
import logging
import re
import time
import uuid
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any, Iterable, Optional
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import MyRepository, RepoVector, TrendingRepository
from app.services.embedding import EmbeddingService
from app.services.semantic_search import _parse_vector

logger = logging.getLogger(__name__)

SCOPES: tuple[str, ...] = ("my", "trending", "all")
_KIND_EXACT = "exact"
_KIND_NAME = "name"
_KIND_SEMANTIC = "semantic"
_KIND_MIXED = "mixed"

_GITHUB_HOSTS = {"github.com", "www.github.com"}
_GITEE_HOSTS = {"gitee.com", "www.gitee.com"}

_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_CJK_RANGE = re.compile(r"[一-鿿]+")
_ASCII_WORD = re.compile(r"[0-9a-z]+")

_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "the",
    "to",
    "with",
    "app",
    "apps",
    "demo",
    "docs",
    "example",
    "examples",
    "lib",
    "library",
    "project",
    "repo",
    "repository",
    "sdk",
    "template",
    "tool",
    "tools",
    "ui",
    "web",
    "支持",
    "一个",
    "以及",
    "使用",
    "基于",
    "可以",
    "工具",
    "开源",
    "我们",
    "我的",
    "提供",
    "方便",
    "项目",
    "仓库",
}

# 中文停用 bigram（避免「支持」「可以」这类高频词造成假相似）
_CJK_STOPWORDS = {
    "支持",
    "一个",
    "以及",
    "使用",
    "基于",
    "可以",
    "工具",
    "开源",
    "我们",
    "我的",
    "提供",
    "方便",
    "项目",
    "仓库",
    "管理",
    "系统",
    "平台",
}


class DuplicateError(RuntimeError):
    """重复检测参数错误。"""


@dataclass
class _Repo:
    """参与检测的仓库（收藏库或热榜）。"""

    source: str
    repo_id: str
    platform: str
    name: str
    description: str
    html_url: str
    stars: int
    language: str
    readme_summary: str
    category_id: str
    tech_stack: list[str]
    key: str
    name_tokens: frozenset[str]
    desc_tokens: frozenset[str]


@dataclass
class _Pair:
    """一对命中重复信号的仓库。"""

    a: _Repo
    b: _Repo
    name_score: float
    desc_score: float
    vector_score: Optional[float]
    confidence: float
    kind: str
    reasons: list[str]


@dataclass
class _VectorEntry:
    model: str
    dim: int
    vector: list[float]


def normalize_scope(scope: str) -> str:
    value = (scope or "all").strip().lower()
    if value not in SCOPES:
        raise DuplicateError(f"非法 scope：{scope}（可选 my / trending / all）")
    return value


def normalize_repo_key(platform: str, repo_id: str, html_url: str = "") -> str:
    """把仓库地址归一化为 `platform:owner/repo`，用于识别完全重复。"""
    platform_value = (platform or "github").strip().lower()
    candidate = ""
    url = (html_url or "").strip()
    if url:
        parsed = urlparse(url if "://" in url else f"https://{url}")
        host = (parsed.netloc or "").lower().split(":", 1)[0]
        path = parsed.path.strip("/")
        if host in _GITHUB_HOSTS:
            platform_value = "github"
        elif host in _GITEE_HOSTS:
            platform_value = "gitee"
        else:
            path = ""
        if path:
            parts = [part for part in path.split("/") if part]
            if len(parts) >= 2:
                candidate = f"{parts[0]}/{parts[1]}"
    if not candidate:
        candidate = (repo_id or "").strip()
    candidate = candidate.replace("\\", "/").strip().strip("/")
    if candidate.lower().endswith(".git"):
        candidate = candidate[:-4]
    candidate = re.sub(r"\s+", "", candidate)
    return f"{platform_value}:{candidate.lower()}"


def normalize_name(value: str) -> str:
    """归一化仓库名：拆 camelCase、小写、分隔符折叠为空格。"""
    raw = _CAMEL_BOUNDARY.sub(" ", (value or "").strip())
    return " ".join(re.findall(r"[0-9a-z一-鿿]+", raw.lower()))


def text_tokens(value: str) -> set[str]:
    """提取中英文 token；中文按 bigram，英文按单词。"""
    raw = _CAMEL_BOUNDARY.sub(" ", (value or "").strip().lower())
    tokens: set[str] = set()
    for chunk in re.split(r"[^0-9a-z一-鿿]+", raw):
        if not chunk:
            continue
        for match in re.finditer(r"[一-鿿]+|[0-9a-z]+", chunk):
            part = match.group(0)
            if _CJK_RANGE.fullmatch(part):
                if len(part) == 1:
                    if part not in _CJK_STOPWORDS:
                        tokens.add(part)
                    continue
                for index in range(len(part) - 1):
                    bigram = part[index : index + 2]
                    if bigram not in _CJK_STOPWORDS:
                        tokens.add(bigram)
            else:
                if len(part) >= 2 and part not in _STOPWORDS:
                    tokens.add(part)
    return tokens


def token_jaccard(left: Iterable[str], right: Iterable[str]) -> float:
    a = set(left)
    b = set(right)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def name_similarity(left: str, right: str) -> float:
    """名称相似度：字符序列相似度与 token Jaccard 取大。"""
    a = normalize_name(left)
    b = normalize_name(right)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    ratio = SequenceMatcher(None, a, b).ratio()
    jaccard = token_jaccard(text_tokens(a), text_tokens(b))
    return round(max(ratio, jaccard), 6)


def _as_text(value: Any) -> str:
    return str(value or "").strip()


def _to_repo(source: str, row: Any) -> _Repo:
    tech_stack = [
        item.strip()
        for item in _as_text(getattr(row, "tech_stack", "")).split(",")
        if item.strip()
    ]
    description = _as_text(getattr(row, "description", ""))
    readme_summary = _as_text(getattr(row, "readme_summary", ""))
    name = _as_text(getattr(row, "name", "")) or _as_text(row.id).split("/")[-1]
    return _Repo(
        source=source,
        repo_id=_as_text(row.id),
        platform=_as_text(getattr(row, "platform", "")) or "github",
        name=name,
        description=description,
        html_url=_as_text(getattr(row, "html_url", "")),
        stars=int(getattr(row, "stars", 0) or 0),
        language=_as_text(getattr(row, "language", "")),
        readme_summary=readme_summary,
        category_id=_as_text(getattr(row, "category_id", "")),
        tech_stack=tech_stack,
        key=normalize_repo_key(
            _as_text(getattr(row, "platform", "")) or "github",
            _as_text(row.id),
            _as_text(getattr(row, "html_url", "")),
        ),
        name_tokens=frozenset(text_tokens(name)),
        desc_tokens=frozenset(text_tokens(f"{description} {readme_summary}")),
    )


def _load_repos(
    db: Session,
    scope: str,
    my_repo_ids: Optional[list[str]],
    max_repos: int,
) -> list[_Repo]:
    repos: list[_Repo] = []
    if scope in ("my", "all"):
        stmt = select(MyRepository)
        if my_repo_ids is not None:
            ids = [item.strip() for item in my_repo_ids if item and item.strip()]
            stmt = stmt.where(MyRepository.id.in_(ids))
        stmt = stmt.order_by(MyRepository.stars.desc(), MyRepository.id.asc()).limit(max_repos)
        repos.extend(_to_repo("my", row) for row in db.execute(stmt).scalars().all())

    remaining = max(1, max_repos - len(repos))
    if scope in ("trending", "all") and remaining > 0:
        stmt = (
            select(TrendingRepository)
            .order_by(TrendingRepository.stars.desc(), TrendingRepository.id.asc())
            .limit(remaining)
        )
        repos.extend(_to_repo("trending", row) for row in db.execute(stmt).scalars().all())
    return repos


def _load_vectors(db: Session, repos: list[_Repo]) -> dict[tuple[str, str], _VectorEntry]:
    entries: dict[tuple[str, str], _VectorEntry] = {}
    by_source: dict[str, list[str]] = {}
    for repo in repos:
        by_source.setdefault(repo.source, []).append(repo.repo_id)
    for source, repo_ids in by_source.items():
        rows = db.execute(
            select(RepoVector).where(
                RepoVector.source == source,
                RepoVector.repo_id.in_(repo_ids),
            )
        ).scalars()
        for row in rows:
            vector = _parse_vector(row.vector)
            if vector is None or not vector:
                continue
            entries[(row.source, row.repo_id)] = _VectorEntry(
                model=row.model,
                dim=int(row.dim or len(vector)),
                vector=vector,
            )
    return entries


def _vector_score(
    left: _Repo,
    right: _Repo,
    vectors: dict[tuple[str, str], _VectorEntry],
) -> Optional[float]:
    a = vectors.get((left.source, left.repo_id))
    b = vectors.get((right.source, right.repo_id))
    if a is None or b is None:
        return None
    if a.model != b.model or a.dim != b.dim or len(a.vector) != len(b.vector):
        return None
    return round(EmbeddingService.cosine(a.vector, b.vector), 6)


def _owner(repo: _Repo) -> str:
    return repo.repo_id.split("/", 1)[0].lower() if "/" in repo.repo_id else ""


def _evaluate_pair(
    left: _Repo,
    right: _Repo,
    vectors: dict[tuple[str, str], _VectorEntry],
    *,
    name_threshold: float,
    description_threshold: float,
    vector_threshold: float,
    min_confidence: float,
) -> Optional[_Pair]:
    if left.source == right.source and left.repo_id == right.repo_id:
        return None
    if left.platform.lower() != right.platform.lower():
        return None

    exact = left.key == right.key
    name_score = name_similarity(left.name, right.name)
    desc_score = token_jaccard(left.desc_tokens, right.desc_tokens)
    vector_score = _vector_score(left, right, vectors)
    vector_ok = vector_score is not None and vector_score >= vector_threshold
    name_ok = name_score >= name_threshold

    if not exact:
        accepted = name_ok and (
            desc_score >= 0.08 or vector_ok or name_score >= 0.96
        )
        if not accepted:
            # 语义重复：名称不同，靠简介 + 向量复核；简介阈值放宽到配置值的 60%，
            # 且不低于 0.5，向量阈值（默认 0.88）负责兜底，避免仅凭泛化简介误报。
            accepted = desc_score >= max(0.5, description_threshold * 0.6) and vector_ok
        if not accepted:
            return None

    if exact:
        confidence = 1.0
        kind = _KIND_EXACT
    else:
        if name_ok:
            vector_part = vector_score if vector_score is not None else name_score
            confidence = name_score * 0.70 + desc_score * 0.15 + vector_part * 0.15
            if _owner(left) == _owner(right) and name_score >= 0.80:
                confidence = min(1.0, confidence + 0.03)
        else:
            # 语义重复按简介 + 向量加权，名称相似度天然很低，不参与主评分。
            confidence = desc_score * 0.45 + (vector_score or 0.0) * 0.55
        confidence = round(confidence, 4)
        kind = _KIND_NAME if name_ok else _KIND_SEMANTIC

    if confidence < min_confidence:
        return None

    reasons: list[str] = []
    if exact:
        reasons.append("仓库地址归一化后完全一致（同一项目）")
    if name_ok and not exact:
        reasons.append(f"仓库名相似度 {round(name_score * 100)}%")
    if desc_score >= 0.45:
        reasons.append(f"项目简介相似度 {round(desc_score * 100)}%")
    if vector_ok:
        reasons.append(f"向量余弦相似度 {round((vector_score or 0) * 100)}%")
    if not exact and _owner(left) == _owner(right) and name_score >= 0.80:
        reasons.append("同一 owner 下的仓库，可能是改名 / 归档")
    if left.source != right.source:
        reasons.append("同一项目同时出现在收藏库与热榜")
    if not reasons:
        reasons.append("名称 / 简介规则命中")

    return _Pair(
        a=left,
        b=right,
        name_score=name_score,
        desc_score=desc_score,
        vector_score=vector_score,
        confidence=confidence,
        kind=kind,
        reasons=reasons,
    )


class _UnionFind:
    def __init__(self, size: int) -> None:
        self.parent = list(range(size))

    def find(self, index: int) -> int:
        while self.parent[index] != index:
            self.parent[index] = self.parent[self.parent[index]]
            index = self.parent[index]
        return index

    def union(self, left: int, right: int) -> None:
        root_left = self.find(left)
        root_right = self.find(right)
        if root_left != root_right:
            self.parent[root_right] = root_left


def cluster_key(members: Iterable[_Repo]) -> str:
    """稳定的簇签名：成员集合不变则 key 不变（用于用户级忽略）。"""
    raw = "|".join(sorted(f"{member.source}:{member.repo_id}" for member in members))
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _metadata_score(repo: _Repo) -> float:
    score = 0.0
    if repo.description:
        score += 1.0
    if repo.readme_summary:
        score += 1.0
    if repo.language:
        score += 0.5
    if repo.category_id:
        score += 0.5
    if repo.tech_stack:
        score += 0.5
    return score


def _pick_canonical(members: list[_Repo]) -> _Repo:
    """保留项优先级：收藏库 > 元数据完整度 > Star 数 > repo id。"""
    return sorted(
        members,
        key=lambda member: (
            1 if member.source == "my" else 0,
            _metadata_score(member),
            member.stars,
            member.repo_id,
        ),
        reverse=True,
    )[0]


def _field_suggestion(
    field: str,
    value: Any,
    source: _Repo,
    reason: str,
) -> dict[str, Any]:
    return {
        "field": field,
        "value": value,
        "from": {"source": source.source, "repoId": source.repo_id},
        "reason": reason,
    }


def _build_fields(members: list[_Repo], canonical: _Repo) -> list[dict[str, Any]]:
    fields: list[dict[str, Any]] = []

    best_description = max(members, key=lambda item: len(item.description))
    if len(best_description.description) > len(canonical.description):
        fields.append(
            _field_suggestion(
                "description",
                best_description.description,
                best_description,
                "取最完整的项目简介",
            )
        )

    best_summary = max(members, key=lambda item: len(item.readme_summary))
    if len(best_summary.readme_summary) > len(canonical.readme_summary):
        fields.append(
            _field_suggestion(
                "readmeSummary",
                best_summary.readme_summary,
                best_summary,
                "取最完整的 README 摘要",
            )
        )

    if not canonical.language:
        with_language = next((item for item in members if item.language), None)
        if with_language is not None:
            fields.append(
                _field_suggestion("language", with_language.language, with_language, "补充主语言")
            )

    max_stars = max(members, key=lambda item: item.stars)
    if max_stars.stars > canonical.stars:
        fields.append(
            _field_suggestion("stars", max_stars.stars, max_stars, "取最大的 Star 数")
        )

    if not canonical.category_id:
        with_category = next((item for item in members if item.category_id), None)
        if with_category is not None:
            fields.append(
                _field_suggestion(
                    "categoryId",
                    with_category.category_id,
                    with_category,
                    "补充收藏库分类",
                )
            )

    merged_tech: list[str] = []
    for member in members:
        for tech in member.tech_stack:
            if tech.lower() not in {item.lower() for item in merged_tech}:
                merged_tech.append(tech)
    if merged_tech and merged_tech != canonical.tech_stack:
        source = next((item for item in members if item.tech_stack), canonical)
        fields.append(
            _field_suggestion("techStack", merged_tech, source, "合并技术栈标签")
        )

    return fields


def build_merge_suggestion(
    members: list[_Repo],
    *,
    confidence: float,
) -> dict[str, Any]:
    """生成保留项、合并项与字段级建议。"""
    canonical = _pick_canonical(members)
    others = [member for member in members if member is not canonical]
    cross_source = any(member.source != canonical.source for member in others)
    action = "merge" if confidence >= 0.85 and len(others) <= 5 else "review"
    notes = (
        "收藏库与热榜命中同一项目，建议保留收藏库条目，将热榜的摘要 / 技术栈并入后归档。"
        if cross_source
        else "建议保留元数据更完整的条目，合并其余重复项后归档。"
    )
    if action == "review":
        notes += f" 当前置信度 {round(confidence * 100)}%，请人工确认后再合并。"
    return {
        "action": action,
        "keep": {"source": canonical.source, "repoId": canonical.repo_id},
        "mergeTargets": [
            {"source": member.source, "repoId": member.repo_id} for member in others
        ],
        "fields": _build_fields(members, canonical),
        "notes": notes,
    }


def _member_signals(
    member: _Repo,
    members: list[_Repo],
    vectors: dict[tuple[str, str], _VectorEntry],
) -> dict[str, Any]:
    name_best = 0.0
    desc_best = 0.0
    vector_best: Optional[float] = None
    exact = False
    for other in members:
        if other is member:
            continue
        name_best = max(name_best, name_similarity(member.name, other.name))
        desc_best = max(desc_best, token_jaccard(member.desc_tokens, other.desc_tokens))
        score = _vector_score(member, other, vectors)
        if score is not None and (vector_best is None or score > vector_best):
            vector_best = score
        exact = exact or member.key == other.key
    return {
        "nameSimilarity": round(name_best, 4),
        "descriptionSimilarity": round(desc_best, 4),
        "vectorSimilarity": None if vector_best is None else round(vector_best, 4),
        "exactKey": exact,
    }


def _build_cluster(
    members: list[_Repo],
    pairs: list[_Pair],
    vectors: dict[tuple[str, str], _VectorEntry],
) -> dict[str, Any]:
    canonical = _pick_canonical(members)
    confidence = max(pair.confidence for pair in pairs)
    kinds = {pair.kind for pair in pairs}
    kind = next(iter(kinds)) if len(kinds) == 1 else _KIND_MIXED
    reasons: list[str] = []
    for pair in sorted(pairs, key=lambda item: item.confidence, reverse=True):
        for reason in pair.reasons:
            if reason not in reasons:
                reasons.append(reason)
    roles = {
        (member.source, member.repo_id): "canonical" if member is canonical else "merge"
        for member in members
    }
    items = []
    for member in sorted(
        members,
        key=lambda item: (0 if item is canonical else 1, -item.stars, item.repo_id),
    ):
        items.append(
            {
                "source": member.source,
                "repoId": member.repo_id,
                "fullName": member.repo_id,
                "name": member.name,
                "description": member.description,
                "language": member.language,
                "stars": member.stars,
                "url": member.html_url,
                "platform": member.platform,
                "categoryId": member.category_id,
                "readmeSummary": member.readme_summary,
                "techStack": member.tech_stack,
                "role": roles[(member.source, member.repo_id)],
                "signals": _member_signals(member, members, vectors),
            }
        )
    return {
        "id": cluster_key(members),
        "kind": kind,
        "confidence": round(confidence, 4),
        "reasons": reasons[:5],
        "members": items,
        "suggestion": build_merge_suggestion(members, confidence=confidence),
    }


def detect_duplicates(
    db: Session,
    scope: str = "all",
    *,
    my_repo_ids: Optional[list[str]] = None,
    min_score: Optional[float] = None,
    name_threshold: Optional[float] = None,
    max_repos: Optional[int] = None,
    max_clusters: Optional[int] = None,
) -> dict[str, Any]:
    """扫描并返回重复 / 相似项目簇（只读，不落库）。"""
    started = time.perf_counter()
    settings = get_settings()
    normalized_scope = normalize_scope(scope)
    effective_min = float(
        settings.DUPLICATE_MIN_CONFIDENCE if min_score is None else min_score
    )
    effective_name = float(
        settings.DUPLICATE_NAME_THRESHOLD if name_threshold is None else name_threshold
    )
    effective_desc = float(settings.DUPLICATE_DESCRIPTION_THRESHOLD)
    effective_vector = float(settings.DUPLICATE_VECTOR_THRESHOLD)
    effective_max_repos = max(2, int(max_repos or settings.DUPLICATE_MAX_REPOS))
    effective_max_clusters = max(1, int(max_clusters or settings.DUPLICATE_MAX_CLUSTERS))
    if not 0 <= effective_min <= 1:
        raise DuplicateError("minScore 需在 0~1")
    if not 0.5 <= effective_name <= 1:
        raise DuplicateError("nameThreshold 需在 0.5~1")

    repos = _load_repos(db, normalized_scope, my_repo_ids, effective_max_repos)
    vectors = _load_vectors(db, repos)

    pairs: list[_Pair] = []
    compared = 0
    for left_index, left in enumerate(repos):
        for right in repos[left_index + 1 :]:
            if left.platform.lower() != right.platform.lower():
                continue
            compared += 1
            pair = _evaluate_pair(
                left,
                right,
                vectors,
                name_threshold=effective_name,
                description_threshold=effective_desc,
                vector_threshold=effective_vector,
                min_confidence=effective_min,
            )
            if pair is not None:
                pairs.append(pair)

    union = _UnionFind(len(repos))
    index_by_key = {(repo.source, repo.repo_id): index for index, repo in enumerate(repos)}
    for pair in pairs:
        union.union(
            index_by_key[(pair.a.source, pair.a.repo_id)],
            index_by_key[(pair.b.source, pair.b.repo_id)],
        )

    grouped: dict[int, list[int]] = {}
    for index in range(len(repos)):
        grouped.setdefault(union.find(index), []).append(index)

    clusters: list[dict[str, Any]] = []
    for indexes in grouped.values():
        if len(indexes) < 2:
            continue
        members = [repos[index] for index in indexes]
        member_keys = {(member.source, member.repo_id) for member in members}
        group_pairs = [
            pair
            for pair in pairs
            if (pair.a.source, pair.a.repo_id) in member_keys
            and (pair.b.source, pair.b.repo_id) in member_keys
        ]
        if not group_pairs:
            continue
        clusters.append(_build_cluster(members, group_pairs, vectors))

    clusters.sort(key=lambda item: (item["confidence"], len(item["members"])), reverse=True)
    clusters = clusters[:effective_max_clusters]
    return {
        "scanId": f"dup_{uuid.uuid4().hex[:12]}",
        "scope": normalized_scope,
        "scanned": len(repos),
        "compared": compared,
        "clusters": clusters,
        "tookMs": int((time.perf_counter() - started) * 1000),
        "thresholds": {
            "minScore": effective_min,
            "nameThreshold": effective_name,
            "descriptionThreshold": effective_desc,
            "vectorThreshold": effective_vector,
            "maxRepos": effective_max_repos,
            "maxClusters": effective_max_clusters,
        },
    }
