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
