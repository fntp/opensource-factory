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
