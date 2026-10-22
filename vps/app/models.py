"""数据库模型（SQLAlchemy 2.0 声明式）。

本地镜像与 Cloudflare D1 的表结构保持一致的列名与语义：
`my_repositories` / `trending_repositories` / `categories`，
并补充 `users`（最小）、`recommendations`（推荐结果）、
`repo_vectors`（M3-02 向量化）与 `vector_index_*`（M3-03 索引同步）。
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Optional

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
    # M1-12 检索索引：列表按 stars 排序，分类筛选后同样按 stars 排序
    __table_args__ = (
        Index("idx_my_repositories_stars", "stars"),
        Index("idx_my_repositories_category_stars", "category_id", "stars"),
    )

    id: Mapped[str] = mapped_column(String(255), primary_key=True)  # 例如 "owner/repo"
    platform: Mapped[str] = mapped_column(String(32), nullable=False, default="github")  # 'github' | 'gitee'
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    html_url: Mapped[str] = mapped_column(Text, nullable=False, default="")
    stars: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    language: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    readme_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # VPS 大模型生成的项目摘要
    category_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)  # 关联分类 ID
    # License 识别（M6-06）：spdx / 展示名 / 来源（github / readme / none）/ 最近识别时间
    license_spdx: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    license_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    license_source: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    license_checked_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)
    # M6-05 项目健康度：GitHub 元数据 + 计算结果
    pushed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)  # 最后 push 时间
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)  # GitHub 元数据更新时间
    open_issues_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)  # 未关闭 issue + PR
    archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    disabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    health_status: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    health_score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    health_checked_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    # M7-04 收藏项目更新提醒：最近一次扫描到的最新 Release / Tag
    latest_release_tag: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    latest_release_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    latest_release_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    latest_release_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    latest_release_checked_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    @property
    def license(self) -> Optional[dict[str, Any]]:
        """API 序列化用的合规提示；从未识别过时返回 None。"""
        if not (self.license_spdx or self.license_source):
            return None
        from app.services.license import build_compliance_hint

        return build_compliance_hint(
            self.license_spdx,
            self.license_name,
            source=self.license_source,
            checked_at=self.license_checked_at,
        )


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
    # License 识别（M6-06）
    license_spdx: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    license_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    license_source: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    license_checked_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    crawled_at: Mapped[date] = mapped_column(Date, nullable=False, default=date.today)

    @property
    def license(self) -> Optional[dict[str, Any]]:
        """API 序列化用的合规提示；从未识别过时返回 None。"""
        if not (self.license_spdx or self.license_source):
            return None
        from app.services.license import build_compliance_hint

        return build_compliance_hint(
            self.license_spdx,
            self.license_name,
            source=self.license_source,
            checked_at=self.license_checked_at,
        )


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


class SummaryQualitySample(Base):
    """摘要质量抽检样本（REQ-202610-0912 / M2-04）。

    每次批量摘要任务按比例留存样本，并强制留存低质量样本；样本附带自动评分，
    等待人工复核（passed / failed）。`(batch_id, repo_source, repo_id)` 唯一，
    重跑只更新不新增；同一仓库同时出现在我的仓库与热榜时也能各留一条。
    """

    __tablename__ = "summary_quality_samples"
    __table_args__ = (
        UniqueConstraint(
            "batch_id", "repo_source", "repo_id", name="uq_summary_quality_batch_source_repo"
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    batch_id: Mapped[str] = mapped_column(String(128), nullable=False, default="", index=True)
    repo_id: Mapped[str] = mapped_column(String(255), nullable=False)
    repo_source: Mapped[str] = mapped_column(String(32), nullable=False, default="my")  # my | trending
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="")  # ollama | deepseek | truncated
    model: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    max_chars: Mapped[int] = mapped_column(Integer, nullable=False, default=800)
    score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    verdict: Mapped[str] = mapped_column(String(16), nullable=False, default="fail")  # pass | fail
    checks: Mapped[str] = mapped_column(Text, nullable=False, default="[]")  # JSON 数组
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")  # pending | passed | failed
    reviewer: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    review_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)


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
    # Rerank 精排（M7-07）：粗排分 / 精排分 / 精排名次 / 可解释明细
    base_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    rerank_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    rerank_rank: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    rerank_detail: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    reranked_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
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


class PushDelivery(Base):
    """统一推送投递记录（M4-08）。

    三个站外通道（Bark / Telegram / Email）每次实际发送都写一条，字段口径统一，
    供 `/api/push/records` 查询与统计；通道原表继续保留，`source_id` 指向原表 id
    以便对账。`target` 可能是邮箱 / chat id / group 名，API 输出时统一脱敏。
    """

    __tablename__ = "push_deliveries"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    channel: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="digest")
    target: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    target_type: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending", index=True
    )  # pending | sent | delivered | failed | skipped
    item_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    message_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    message_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    subject: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    dedupe_key: Mapped[str] = mapped_column(
        String(255), nullable=False, default="", index=True
    )
    receipt_status: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    receipt_detail: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    source_id: Mapped[str] = mapped_column(String(64), nullable=False, default="", index=True)
    user_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=_utcnow, index=True
    )
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    delivered_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class PushReceipt(Base):
    """推送送达回执流水（M4-08）。

    一个 delivery 可有多条回执（服务商异步回调 / 人工补记），
    `delivery_id + external_id + status` 用于幂等去重。
    """

    __tablename__ = "push_receipts"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    delivery_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    channel: Mapped[str] = mapped_column(String(16), nullable=False, default="", index=True)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, index=True
    )  # accepted | delivered | bounced | failed
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="provider")
    external_id: Mapped[str] = mapped_column(String(255), nullable=False, default="", index=True)
    detail: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)


class MonitoringAlert(Base):
    """监控告警（M5-03）：资源红线 / 依赖故障 / 日志超预算。

    按 `dedupe_key`（kind + scope）在冷却窗口内合并，条件恢复后置为 resolved。
    """

    __tablename__ = "monitoring_alerts"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    kind: Mapped[str] = mapped_column(
        String(32), nullable=False
    )  # memory | disk | service | logs | edge | model
    severity: Mapped[str] = mapped_column(
        String(16), nullable=False, default="warning"
    )  # warning | critical
    message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    details: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON 文本
    dedupe_key: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="open", index=True
    )  # open | acknowledged | resolved
    occurrences: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)
    acknowledged_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class MonitoringCheckRun(Base):
    """监控检查运行记录（M5-03）：保存每轮健康检查与资源快照。"""

    __tablename__ = "monitoring_check_runs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="ok"
    )  # ok | warning | critical
    checks: Mapped[str] = mapped_column(Text, nullable=False, default="[]")  # JSON
    resources: Mapped[str] = mapped_column(Text, nullable=False, default="{}")  # JSON
    findings: Mapped[str] = mapped_column(Text, nullable=False, default="[]")  # JSON
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)
class RepoReadme(Base):
    """README 全文镜像（M6-01，VPS SQLite）。

    与 `repo_vectors` 一样使用 `(source, repo_id)` 联合主键；内容为 `clean_readme`
    清洗后的纯文本，供 FTS5 全文检索使用。D1 不保存全文，保持本地镜像先行。
    """

    __tablename__ = "repo_readmes"

    source: Mapped[str] = mapped_column(String(16), primary_key=True)  # my | trending
    repo_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    char_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=_utcnow, onupdate=_utcnow
    )


class RepoDependency(Base):
    """仓库依赖明细（M6-07 依赖分析）。

    一行 = 某仓库某清单里的一个依赖；`id` 由
    `sha1(repo_id|ecosystem|name|kind)` 生成，重复扫描按主键覆盖，
    不会产生重复行。依赖明细只落 VPS 本地库，不复制到 D1。
    """

    __tablename__ = "repo_dependencies"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    repo_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)  # owner/repo
    ecosystem: Mapped[str] = mapped_column(
        String(32), nullable=False, index=True
    )  # npm | pypi | go | cargo | maven | rubygems | composer
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    version: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)  # 原始版本约束
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="runtime")  # runtime | dev
    manifest: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)

    __table_args__ = (Index("idx_repo_dependencies_repo_eco", "repo_id", "ecosystem"),)


class RepoDependencyScan(Base):
    """仓库依赖清单扫描状态（每个仓库一条，记录命中清单与错误）。"""

    __tablename__ = "repo_dependency_scans"

    repo_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="ok"
    )  # ok | no_manifest | failed
    manifests: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # 逗号分隔
    dependency_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    scanned_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)
class ModelRouteConfig(Base):
    """任务级模型路由配置（REQ-202610-0965 / M7-06）。

    VPS 本地 SQLite 表；不镜像 D1。`task` 为主键，缺省配置不落库。
    """

    __tablename__ = "model_route_configs"

    task: Mapped[str] = mapped_column(String(32), primary_key=True)
    strategy: Mapped[str] = mapped_column(String(16), nullable=False, default="budget")
    model_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    updated_by: Mapped[str] = mapped_column(String(64), nullable=False, default="admin")
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)


class PrivacyEvent(Base):
    """本地隐私审计事件（REQ-202610-0983 / M9-06）。

    只记录事件类型、用户 id 哈希与聚合计数，不保存个人数据或令牌。
    `delete` 由边缘删除账号后的本地镜像清理写入，`retention_cleanup` 由每日任务写入。
    """

    __tablename__ = "privacy_events"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    actor_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    detail: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=_utcnow, index=True
    )
