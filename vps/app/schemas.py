"""Pydantic 出入参模型（API 层）。"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Optional

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
