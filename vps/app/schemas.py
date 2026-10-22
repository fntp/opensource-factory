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
    """热榜仓库输出（含按日快照与趋势字段）。"""

    id: str
    platform: str
    name: str
    html_url: str
    stars_today: Optional[int] = 0
    description: Optional[str] = None
    tech_stack: Optional[str] = None
    readme_summary: Optional[str] = None
    owner: Optional[str] = None
    language: Optional[str] = None
    stars: int = 0
    crawled_at: Optional[date] = None
    snapshot_date: Optional[date] = None
    rank: Optional[int] = None
    rank_change: Optional[int] = None
    trend: Optional[str] = None


class TrendingRepoDetail(TrendingRepoOut):
    """热榜详情输出：摘要 + 元信息。"""

    summary: Optional[str] = None
    summary_source: str = "empty"  # readme | description | tech | empty


class TrendingSnapshotOut(ORMModel):
    """热榜按日快照输出（含趋势字段）。"""

    snapshot_date: date
    repo_id: str
    platform: str
    owner: Optional[str] = None
    name: str
    html_url: str
    description: Optional[str] = None
    language: Optional[str] = None
    tech_stack: Optional[str] = None
    stars: int = 0
    stars_today: int = 0
    rank: int = 0
    language_rank: int = 0
    star_delta: int = 0
    rank_delta: int = 0
    appearances: int = 1
    is_new: int = 0
    trend: str = "steady"
    trending_pages: Optional[str] = None


class TrendingSnapshotDateOut(BaseModel):
    """可用快照日期。"""

    date: date
    count: int


class CrawlAlertOut(ORMModel):
    """热榜抓取告警输出。"""

    id: str
    platform: str
    page: str
    kind: str
    severity: str
    message: str
    details: Optional[str] = None
    status: str
    occurrences: int = 1
    first_seen_at: Optional[datetime] = None
    last_seen_at: Optional[datetime] = None
    acknowledged_at: Optional[datetime] = None


class TrendingRetentionStatus(BaseModel):
    """热榜数据保留策略状态（M2-08，字段与运维接口保持一致）。"""

    enabled: bool
    retentionDays: int
    cutoff: Optional[date] = None
    archiveEnabled: bool
    archiveDir: str
    archiveKeepDays: int
    totalSnapshots: int
    expiredSnapshots: int
    oldestDate: Optional[date] = None
    latestDate: Optional[date] = None
    databaseBytes: int
    archiveFiles: int
    archiveBytes: int


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
    status: str  # pending | started | progress | success | failure
    result: Any = None
    error: Optional[str] = None
    progress: Optional[dict[str, Any]] = None


class QualityCheckOut(BaseModel):
    """单项摘要质量检查。"""

    key: str
    label: str
    weight: int
    critical: bool
    passed: bool
    detail: str


class QualitySampleOut(BaseModel):
    """抽检样本输出（camelCase 与前端契约一致）。"""

    id: str
    batchId: str
    repoId: str
    repoSource: str
    summary: str
    source: str
    model: str
    maxChars: int
    score: float
    verdict: str
    checks: list[QualityCheckOut] = Field(default_factory=list)
    status: str
    reviewer: Optional[str] = None
    reviewNote: Optional[str] = None
    reviewedAt: Optional[datetime] = None
    createdAt: Optional[datetime] = None


class QualitySampleList(BaseModel):
    """抽检样本分页列表。"""

    total: int
    items: list[QualitySampleOut]


class QualityStatsOut(BaseModel):
    """摘要质量统计。"""

    total: int
    pending: int
    passed: int
    failed: int
    passRate: float
    avgScore: float
    bySource: dict[str, int] = Field(default_factory=dict)
    byRepoSource: dict[str, int] = Field(default_factory=dict)
    recentBatches: list[dict[str, Any]] = Field(default_factory=list)


class QualityReviewIn(BaseModel):
    """人工复核请求。"""

    result: Literal["passed", "failed"]
    reviewer: Optional[str] = Field(default=None, max_length=128)
    note: Optional[str] = Field(default=None, max_length=2000)


class QualitySampleExistingIn(BaseModel):
    """存量摘要补抽样请求。"""

    source: Literal["my", "trending", "all"] = "my"
    limit: int = Field(default=200, ge=1, le=1000)
    rate: Optional[float] = Field(default=None, ge=0, le=1)
    batchId: Optional[str] = Field(default=None, max_length=128)


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


class VectorSyncRequest(BaseModel):
    """Vectorize 索引同步入参。"""

    mode: str = Field(default="incremental", pattern="^(incremental|full)$")
    scope: str = Field(default="all", pattern="^(my|trending|all)$")
    limit: Optional[int] = Field(default=None, ge=1, le=100000)
    batchSize: Optional[int] = Field(default=None, ge=1, le=1000)


class VectorSyncEnqueued(BaseModel):
    """同步入队响应。"""

    taskId: str
    runId: str


class VectorReconcileRequest(BaseModel):
    """Vectorize 对账入参。"""

    scope: str = Field(default="all", pattern="^(my|trending|all)$")
    repair: bool = False
    limit: Optional[int] = Field(default=None, ge=1, le=100000)

class SearchQuery(BaseModel):
    """语义搜索请求（内部接口共用）。"""

    query: str = Field(min_length=1, max_length=200, description="自然语言查询")
    topK: Optional[int] = Field(default=None, ge=1, le=50, description="返回条数（默认 10，最大 50）")
    scope: Literal["my", "trending", "all"] = "all"
    minScore: Optional[float] = Field(default=None, ge=-1.0, le=1.0, description="最低余弦相似度")


class SearchEmbedResponse(BaseModel):
    """查询向量：供 edge 调用 Vectorize.query 使用。"""

    vector: list[float]
    dim: int
    model: str
    backend: str


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
    items: list[SearchItem]


class SearchStatusResponse(BaseModel):
    """语义搜索可用性：向量覆盖率与最近向量化运行。"""

    totalVectors: int
    bySource: dict[str, int]
    byModel: list[VectorModelStats]
    dimensions: list[int]
    latestRuns: list[VectorRunOut]
