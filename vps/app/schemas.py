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


class EvaluationRunOut(BaseModel):
    """单次推荐评估运行输出（M4-01）。"""

    runId: str
    userId: Optional[str] = None
    status: str
    matchThreshold: float
    qualityThreshold: float
    total: int = 0
    qualified: int = 0
    filtered: int = 0
    skipped: int = 0
    failed: int = 0
    error: Optional[str] = None
    createdAt: Optional[datetime] = None
    finishedAt: Optional[datetime] = None


class EvaluationRunListResponse(BaseModel):
    """评估运行列表。"""

    count: int
    items: list[EvaluationRunOut]


class QualifiedRecommendationOut(BaseModel):
    """通过每日评估、等待推送的推荐。"""

    id: str
    userId: str
    repoId: str
    score: float
    matchScore: float
    qualityScore: float
    qualityDetail: Optional[dict[str, Any]] = None
    reason: Optional[str] = None
    status: str
    evaluatedAt: Optional[datetime] = None


class QualifiedListResponse(BaseModel):
    """合格推荐列表。"""

    count: int
    items: list[QualifiedRecommendationOut]


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


# ---------------------------------------------------------------------------
# 推送去重与静默策略（M4-07）
# ---------------------------------------------------------------------------


class PushPolicyCheckRequest(BaseModel):
    """发送前预演请求。"""

    userId: str = Field(min_length=1, max_length=128)
    repoId: str = Field(min_length=1, max_length=255)
    recommendationId: Optional[str] = Field(default=None, max_length=64)
    channel: Literal["inapp", "bark", "telegram", "email"] = "inapp"


class PushPolicyDecision(BaseModel):
    """单条推送判定结果。"""

    allowed: bool
    reason: str
    userId: str
    repoId: str
    recommendationId: Optional[str] = None
    channel: str
    dedupeKey: str
    quietHours: bool = False
    nextAllowedAt: Optional[datetime] = None
    existingEventId: Optional[str] = None
    dailyUsed: int = 0
    dailyLimit: int = 0


class PushEventCreate(BaseModel):
    """通道投递事件上报。"""

    userId: str = Field(min_length=1, max_length=128)
    repoId: str = Field(min_length=1, max_length=255)
    recommendationId: Optional[str] = Field(default=None, max_length=64)
    channel: Literal["inapp", "bark", "telegram", "email"] = "inapp"
    status: Literal["prepared", "sent", "failed", "skipped"] = "sent"
    reason: Optional[str] = Field(default=None, max_length=500)


class PushEventOut(BaseModel):
    """推送事件输出。"""

    id: str
    userId: str
    repoId: str
    recommendationId: Optional[str] = None
    channel: str
    status: str
    dedupeKey: str
    eventKey: str
    reason: Optional[str] = None
    createdAt: Optional[datetime] = None
    updatedAt: Optional[datetime] = None
    sentAt: Optional[datetime] = None


class PushEventListResponse(BaseModel):
    """推送事件列表。"""

    count: int
    items: list[PushEventOut]


class PushEventWriteResponse(BaseModel):
    """推送事件写入结果。"""

    id: str
    created: bool
    updated: bool
    status: str
    eventKey: str
    dedupeKey: str
    sentAt: Optional[datetime] = None


class PushQuietHoursOut(BaseModel):
    """静默时段状态。"""

    start: Optional[str] = None
    end: Optional[str] = None
    timezone: str
    active: bool
    nextAllowedAt: Optional[datetime] = None


class PushLimitsOut(BaseModel):
    """推送限额配置。"""

    dailyLimit: int
    dedupeDays: int
    crossChannel: bool
    retryIntervalMinutes: int


class PushTodayOut(BaseModel):
    """今日事件计数。"""

    prepared: int = 0
    sent: int = 0
    failed: int = 0
    skipped: int = 0
    repos: int = 0


class PushPolicyStatusOut(BaseModel):
    """策略状态快照。"""

    enabled: bool
    quietHours: PushQuietHoursOut
    limits: PushLimitsOut
    today: PushTodayOut
    recentEvents: list[PushEventOut]
