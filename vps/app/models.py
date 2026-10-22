"""数据库模型（SQLAlchemy 2.0 声明式）。

本地镜像与 Cloudflare D1 的表结构保持一致的列名与语义：
`my_repositories` / `trending_repositories` / `categories`，
并补充 `users`（最小）、`recommendations`（推荐结果）、
`repo_vectors`（M3-02 向量化）与 `vector_index_*`（M3-03 索引同步）。
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
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
    readme_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # 热榜项目中文摘要（M2-04）
    owner: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)  # owner（与 D1 扩展列对齐）
    language: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)  # 主语言
    stars: Mapped[int] = mapped_column(Integer, nullable=False, default=0)  # 总 Star
    crawled_at: Mapped[date] = mapped_column(Date, nullable=False, default=date.today)


class TrendingSnapshot(Base):
    """热榜按日快照（M2-05）。

    同一仓库同一天只有一行：主键 `(snapshot_date, repo_id)` 保证重复抓取幂等；
    `star_delta` / `rank_delta` / `appearances` / `trend` 为对比上一有效快照的趋势字段。
    """

    __tablename__ = "trending_snapshots"

    snapshot_date: Mapped[date] = mapped_column(Date, primary_key=True)
    repo_id: Mapped[str] = mapped_column(String(255), primary_key=True)  # owner/repo
    platform: Mapped[str] = mapped_column(String(32), nullable=False, default="github")
    owner: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    html_url: Mapped[str] = mapped_column(Text, nullable=False, default="")
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    language: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    tech_stack: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    stars: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    stars_today: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rank: Mapped[int] = mapped_column(Integer, nullable=False, default=0)  # 全平台综合排名（1 起）
    language_rank: Mapped[int] = mapped_column(Integer, nullable=False, default=0)  # 同语言内排名
    star_delta: Mapped[int] = mapped_column(Integer, nullable=False, default=0)  # 对比上一快照的总 Star 增量
    rank_delta: Mapped[int] = mapped_column(Integer, nullable=False, default=0)  # 正数=排名上升
    appearances: Mapped[int] = mapped_column(Integer, nullable=False, default=1)  # 连续上榜天数
    is_new: Mapped[int] = mapped_column(Integer, nullable=False, default=0)  # 1=首次上榜
    trend: Mapped[str] = mapped_column(String(16), nullable=False, default="steady")  # new/up/down/steady
    trending_pages: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON 数组，来源语言页
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)


class CrawlPageStat(Base):
    """热榜抓取页面基线（按平台 + 页面记录上次成功条数）。"""

    __tablename__ = "crawl_page_stats"

    page_key: Mapped[str] = mapped_column(String(128), primary_key=True)  # 例如 "github:python"
    platform: Mapped[str] = mapped_column(String(32), nullable=False, default="github")
    page: Mapped[str] = mapped_column(String(64), nullable=False, default="all")  # all / 语言 slug
    last_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_status_code: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    last_rows: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    last_parsed: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    last_ok_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)


class CrawlAlert(Base):
    """热榜抓取告警（页面结构变更 / 抓取失败 / 条数骤降）。"""

    __tablename__ = "crawl_alerts"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    platform: Mapped[str] = mapped_column(String(32), nullable=False, default="github")
    page: Mapped[str] = mapped_column(String(64), nullable=False, default="all")
    kind: Mapped[str] = mapped_column(String(32), nullable=False)  # fetch_failed | structure_change | count_drop | all_failed
    severity: Mapped[str] = mapped_column(String(16), nullable=False, default="warning")  # warning | error
    message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    details: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON 文本
    dedupe_key: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open", index=True)  # open | acknowledged
    occurrences: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)
    acknowledged_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


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
    # Bark 通道投递标记（M4-03）：成功时间 / 最近一次失败原因
    bark_sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    bark_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    based_on: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON 数组字符串
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


class EmailDelivery(Base):
    """Email 通道送达记录（M4-05）。

    每次摘要 / 测试邮件投递写一条记录；`dedupe_key` 用于「日期 + 收件人」级
    最小幂等（同一批次重复触发时跳过已成功记录），`error` 保存脱敏后的失败原因。
    """

    __tablename__ = "email_deliveries"
    __table_args__ = (Index("ix_email_deliveries_dedupe", "dedupe_key", "status"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    recipient: Mapped[str] = mapped_column(Text, nullable=False, default="")
    kind: Mapped[str] = mapped_column(
        String(16), nullable=False, default="digest"
    )  # digest | test
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="sent"
    )  # sent | failed
    item_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    subject: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    message_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    dedupe_key: Mapped[str] = mapped_column(String(255), nullable=False, default="")
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


class VectorIndexState(Base):
    """Vectorize 索引中每条向量的同步状态。

    与 M3-02 的 `repo_vectors` 通过 `(source, repo_id)` 对齐；`text_hash` 是版本号，
    只有 hash / model / backend / dim 变化或上次同步失败时才需要重新 upsert。
    """

    __tablename__ = "vector_index_state"

    source: Mapped[str] = mapped_column(String(16), primary_key=True)  # my | trending
    repo_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    vector_id: Mapped[str] = mapped_column(String(64), nullable=False)
    text_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    model: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    backend: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    dim: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")  # synced | failed
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    synced_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    checked_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class VectorIndexRun(Base):
    """Vectorize 索引同步 / 对账运行记录。"""

    __tablename__ = "vector_index_runs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    mode: Mapped[str] = mapped_column(String(16), nullable=False, default="incremental")  # incremental | full | reconcile
    scope: Mapped[str] = mapped_column(String(16), nullable=False, default="all")  # my | trending | all
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="running")  # running | completed | failed | disabled
    batch_size: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    max_retries: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    processed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    upserted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    deleted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    skipped: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    dim_skipped: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    checked: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    missing: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    stale: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    repaired: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    batches: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # 断点续跑游标：已处理到的最后一条 (source, repo_id)
    cursor_source: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    cursor_repo_id: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=_utcnow, onupdate=_utcnow
    )
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class TelegramDelivery(Base):
    """Telegram 推送送达记录（M4-04）。

    每次摘要 / 测试消息发送写一条，记录目标会话、消息条数、Telegram
    message_id 与失败原因；`dedupe_key` 用于「同一天同一会话不重复发送」的
    最小幂等，完整去重与静默策略由 M4-07 承接。
    """

    __tablename__ = "telegram_deliveries"
    __table_args__ = (
        Index("ix_telegram_deliveries_dedupe", "dedupe_key", "status"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    chat_id: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="digest")  # digest | test
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending"
    )  # pending | sent | failed
    item_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    message_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    message_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    dedupe_key: Mapped[str] = mapped_column(String(255), nullable=False, default="", index=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class PushEvent(Base):
    """推送策略账本（M4-07）。

    记录一次推送准备 / 投递 / 跳过事件，用于跨通道、跨天的去重与每日上限。
    同一用户 + 仓库 + 通道 + 自然日由 `event_key` 唯一约束保证幂等；
    `dedupe_key` 固定为 `user_id:repo_id`，便于按去重窗口查询。
    """

    __tablename__ = "push_events"
    __table_args__ = (
        UniqueConstraint("event_key", name="uq_push_events_event_key"),
        Index("ix_push_events_user_repo_updated", "user_id", "repo_id", "updated_at"),
        Index("ix_push_events_user_updated", "user_id", "updated_at"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    repo_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    recommendation_id: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, index=True
    )
    channel: Mapped[str] = mapped_column(
        String(32), nullable=False, default="inapp"
    )  # inapp | bark | telegram | email
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="prepared"
    )  # prepared | sent | failed | skipped
    dedupe_key: Mapped[str] = mapped_column(String(512), nullable=False, index=True)
    event_key: Mapped[str] = mapped_column(String(512), nullable=False)
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=_utcnow, onupdate=_utcnow
    )
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
