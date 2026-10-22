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
    owner: Optional[str] = None
    language: Optional[str] = None
    stars: int = 0
    crawled_at: Optional[date] = None


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
    status: str  # pending | started | success | failure
    result: Any = None
    error: Optional[str] = None
