"""Pydantic 出入参模型（API 层）。"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class ORMModel(BaseModel):
    """可从 SQLAlchemy 模型直接序列化的基类。"""

    model_config = ConfigDict(from_attributes=True)


class RepoOut(ORMModel):
    """仓库输出。"""

    id: str
    platform: str
    name: str
    description: Optional[str] = None
    html_url: str
    stars: int = 0
    language: Optional[str] = None
    readme_summary: Optional[str] = None
    category_id: Optional[str] = None
    created_at: Optional[datetime] = None


class TrendingRepoOut(ORMModel):
    """热榜仓库输出。"""

    id: str
    platform: str
    name: str
    html_url: str
    stars_today: Optional[int] = 0
    description: Optional[str] = None
    tech_stack: Optional[str] = None
    crawled_at: Optional[date] = None


class RecommendQuery(BaseModel):
    """语义查询请求。"""

    query: str = Field(min_length=1, description="自然语言查询，如「支付系统脚手架」")
    top_k: int = Field(default=10, ge=1, le=50, description="返回条数")


class RecommendItem(BaseModel):
    """单条推荐结果。"""

    repo_id: str
    name: str
    html_url: str
    language: str = ""
    description: str = ""
    score: float
    reason: str


class RecommendResponse(BaseModel):
    """语义查询响应。"""

    query: str
    count: int
    items: list[RecommendItem]


class TaskEnqueued(BaseModel):
    """任务入队响应（与边缘 Worker 的契约，字段名保持 camelCase）。"""

    taskId: str


class TaskStatus(BaseModel):
    """任务状态响应。"""

    taskId: str
    status: str  # pending | started | success | failure
    result: Any = None
    error: Optional[str] = None


class VectorSyncRequest(BaseModel):
    """Vectorize 索引同步请求。"""

    kind: Literal["sync", "reconcile"] = "sync"
    scope: Literal["my", "trending", "all"] = "all"
    limit: Optional[int] = Field(default=None, ge=1, le=100000, description="本次最多处理的向量数")
    batchSize: Optional[int] = Field(default=None, ge=1, le=1000, description="单批 upsert 条数")
    force: bool = Field(default=False, description="忽略增量状态，全量重传")


class VectorSyncRunOut(BaseModel):
    """一次同步运行的统计输出。"""

    runId: str
    kind: str
    scope: str
    status: str
    batchSize: int
    maxRetries: int
    force: bool
    limit: int
    total: int
    processed: int
    synced: int
    skipped: int
    failed: int
    deleted: int
    checked: int
    missing: int
    repaired: int
    orphanScan: str = ""
    cursorSource: str = ""
    cursorRepoId: str = ""
    error: Optional[str] = None
    createdAt: Optional[datetime] = None
    updatedAt: Optional[datetime] = None
    finishedAt: Optional[datetime] = None


class VectorizeEnqueued(TaskEnqueued):
    """向量化任务入队响应（附带运行 id，可用于续跑 / 查询）。"""

    runId: str


class VectorRunOut(BaseModel):
    """向量化运行状态。"""

    runId: str
    scope: str
    status: str  # running | completed | failed
    model: str = ""
    backend: str = ""
    dim: int = 0
    force: bool = False
    limit: int = 0
    batchSize: int = 0
    total: int = 0
    processed: int = 0
    vectorized: int = 0
    skipped: int = 0
    failed: int = 0
    cursorSource: str = ""
    cursorRepoId: str = ""
    error: Optional[str] = None
    createdAt: Optional[datetime] = None
    updatedAt: Optional[datetime] = None
    finishedAt: Optional[datetime] = None


class VectorSyncStatusOut(BaseModel):
    """索引同步状态：本地覆盖率、状态分布与最近运行。"""

    enabled: bool
    configured: bool
    indexName: str
    dim: int
    localVectors: int
    states: dict[str, int]
    pending: int
    lastRuns: list[VectorSyncRunOut]


class VectorModelStats(BaseModel):
    """按模型 / 后端分组的向量数量。"""

    model: str
    backend: str
    count: int


class VectorSourceStats(BaseModel):
    """单个来源的向量覆盖情况。"""

    total: int
    vectorized: int
    pending: int


class VectorStatsResponse(BaseModel):
    """向量化统计响应。"""

    totalVectors: int
    bySource: dict[str, int]
    byModel: list[VectorModelStats]
    repositories: dict[str, VectorSourceStats]
    latestRuns: list[VectorRunOut]


class VectorDetail(BaseModel):
    """单条向量详情（调试 / 后续 Vectorize 同步使用）。"""

    source: str
    repoId: str
    model: str
    backend: str
    dim: int
    textHash: str
    vector: list[float]
    updatedAt: Optional[datetime] = None


class SearchQuery(BaseModel):
    """语义搜索请求（内部接口共用）。"""

    query: str = Field(min_length=1, max_length=200, description="自然语言查询")
    topK: Optional[int] = Field(default=None, ge=1, le=50, description="返回条数（默认 10，最大 50）")
    scope: Literal["my", "trending", "all"] = "all"
    minScore: Optional[float] = Field(default=None, ge=-1.0, le=1.0, description="最低余弦相似度")
    expand: bool = Field(default=True, description="是否启用同义词 / 技术栈词表扩展")


class SearchUnderstandingOut(BaseModel):
    """查询理解结果（同义词 / 技术栈词表）。"""

    query: str
    rewritten: str
    expanded: bool
    techStack: list[str]
    concepts: list[str]
    terms: list[str]
    keywordTerms: list[str]
    maxTerms: int


class SearchEmbedResponse(BaseModel):
    """查询向量：供 edge 调用 Vectorize.query 使用。"""

    vector: list[float]
    dim: int
    model: str
    backend: str
    understanding: SearchUnderstandingOut


class SearchHitOut(BaseModel):
    """本地向量命中（未水合）。"""

    source: str
    repoId: str
    score: float


class SearchQueryResponse(BaseModel):
    """本地向量检索响应。"""

    query: str
    scope: str
    count: int
    topK: int
    minScore: float
    model: str
    backend: str
    dim: int
    scanned: int
    understanding: SearchUnderstandingOut
    items: list[SearchHitOut]


class SearchItem(BaseModel):
    """水合后的搜索结果条目。"""

    id: str
    source: str
    fullName: str
    name: str
    description: str = ""
    language: str = ""
    stars: int = 0
    starsToday: int = 0
    url: str = ""
    score: float = 0.0
    reason: str = ""


class SearchSemanticResponse(BaseModel):
    """本地语义搜索完整结果（内部 / 调试 / CLI）。"""

    query: str
    scope: str
    count: int
    model: str
    backend: str
    dim: int
    scanned: int
    understanding: SearchUnderstandingOut
    items: list[SearchItem]


class SearchStatusResponse(BaseModel):
    """语义搜索可用性：向量覆盖率与最近向量化运行。"""

    totalVectors: int
    bySource: dict[str, int]
    byModel: list[VectorModelStats]
    dimensions: list[int]
    vocabulary: dict[str, int]
    latestRuns: list[VectorRunOut]
