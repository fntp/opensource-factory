"""数据库模型（SQLAlchemy 2.0 声明式）。

本地镜像与 Cloudflare D1 的表结构保持一致的列名与语义：
`my_repositories` / `trending_repositories` / `categories`，
并补充 `users`（最小）、`recommendations`（推荐结果）、
`repo_vectors`（M3-02 向量化）与 `vector_sync_*`（M3-03 索引同步）。
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, Date, DateTime, Float, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def _utcnow() -> datetime:
    """统一使用无时区 UTC 时间（与 D1 CURRENT_TIMESTAMP 语义对齐）。"""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class MyRepository(Base):
    """我的仓库（GitHub / Gitee），镜像 D1 `my_repositories`。"""

    __tablename__ = "my_repositories"

    id: Mapped[str] = mapped_column(String(255), primary_key=True)  # 例如 "owner/repo"
    platform: Mapped[str] = mapped_column(String(32), nullable=False, default="github")  # 'github' | 'gitee'
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    html_url: Mapped[str] = mapped_column(Text, nullable=False, default="")
    stars: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    language: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    readme_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # VPS 大模型生成的项目摘要
    category_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)  # 关联分类 ID
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)


class TrendingRepository(Base):
    """热榜仓库（GitHub Trending / Gitee），镜像 D1 `trending_repositories`。"""

    __tablename__ = "trending_repositories"

    id: Mapped[str] = mapped_column(String(255), primary_key=True)  # 例如 "owner/repo"
    platform: Mapped[str] = mapped_column(String(32), nullable=False, default="github")
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    html_url: Mapped[str] = mapped_column(Text, nullable=False, default="")
    stars_today: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, default=0)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    tech_stack: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # 自动提取的技术栈描述
    crawled_at: Mapped[date] = mapped_column(Date, nullable=False, default=date.today)


class Category(Base):
    """分类（支持无限级父子层级），镜像 D1 `categories`。"""

    __tablename__ = "categories"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)  # 如：支付系统 / 脚手架
    parent_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)


class User(Base):
    """用户（最小实现：仅用于关联推荐结果）。"""

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    username: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)


class Recommendation(Base):
    """推荐结果（用户 × 仓库 + 得分 + 中文理由）。"""

    __tablename__ = "recommendations"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    repo_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    # 原始余弦相似度（M4-01 每日评估使用；历史数据缺失时回退到 score）
    match_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    # 每日评估产出的综合质量分与可解释明细
    quality_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    quality_detail: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    evaluation_run_id: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, index=True
    )
    evaluated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="new"
    )  # new | qualified | filtered | pushed | saved | dismissed | expired
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)


class RecommendationEvaluationRun(Base):
    """每日推荐评估运行记录（M4-01）。

    一次运行覆盖指定用户或全部用户，保存本次阈值与合格 / 过滤 / 跳过计数，
    供接口查询与问题排查；评估明细落在 `recommendations.quality_detail`。
    """

    __tablename__ = "recommendation_evaluation_runs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="running"
    )  # running | completed | failed
    match_threshold: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    quality_threshold: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    qualified: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    filtered: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    skipped: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class RepoVector(Base):
    """仓库向量（VPS 本地持久化，供增量向量化与语义检索使用）。

    联合主键 `(source, repo_id)`；`source` 为 `my`（收藏库）或 `trending`（热榜）。
    `text_hash` / `model` / `backend` 共同决定是否可以跳过重算。
    """

    __tablename__ = "repo_vectors"

    source: Mapped[str] = mapped_column(String(16), primary_key=True)
    repo_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    backend: Mapped[str] = mapped_column(String(32), nullable=False, default="hash")
    dim: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    text_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    vector: Mapped[str] = mapped_column(Text, nullable=False)  # JSON 数组
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=_utcnow, onupdate=_utcnow
    )

    __table_args__ = (Index("idx_repo_vectors_source_model", "source", "model"),)


class VectorizationRun(Base):
    """向量化运行记录（批量 / 增量 / 断点续跑的状态载体）。"""

    __tablename__ = "vectorization_runs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    scope: Mapped[str] = mapped_column(String(16), nullable=False)  # my | trending | all
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="running"
    )  # running | completed | failed
    model: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    backend: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    dim: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    force: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    limit: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    batch_size: Mapped[int] = mapped_column(Integer, nullable=False, default=32)
    total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    processed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    vectorized: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    skipped: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cursor_source: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    cursor_repo_id: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=_utcnow, onupdate=_utcnow
    )
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class VectorSyncState(Base):
    """单条向量在 Vectorize 索引中的同步状态。

    主键与 M3-02 的 `repo_vectors` 对齐（`source` + `repo_id`）；`text_hash` 用于
    增量判断，`status` 取 `pending` / `synced` / `failed` / `dim_mismatch`。
    """

    __tablename__ = "vector_sync_state"

    source: Mapped[str] = mapped_column(String(16), primary_key=True)  # my | trending
    repo_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    vector_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    text_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    model: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    backend: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    dim: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    synced_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    checked_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=_utcnow, onupdate=_utcnow
    )


class VectorSyncRun(Base):
    """一次 Vectorize 同步 / 对账运行的统计记录。"""

    __tablename__ = "vector_sync_runs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="sync")  # sync | reconcile
    scope: Mapped[str] = mapped_column(String(16), nullable=False, default="all")  # my | trending | all
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="running")
    batch_size: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    max_retries: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    force: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    limit: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    processed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    synced: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    skipped: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    deleted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    checked: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    missing: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    repaired: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    orphan_scan: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    cursor_source: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    cursor_repo_id: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=_utcnow, onupdate=_utcnow
    )
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
