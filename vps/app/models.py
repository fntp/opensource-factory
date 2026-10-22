"""数据库模型（SQLAlchemy 2.0 声明式）。

本地镜像与 Cloudflare D1 的表结构保持一致的列名与语义：
`my_repositories` / `trending_repositories` / `categories`，
并补充 `users`（最小）与 `recommendations`（推荐结果）。
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy import Date, DateTime, Float, Integer, String, Text
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
    # 与 D1 `my_repositories` 扩展列对齐（M1-06）
    owner: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    forks: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)  # GitHub updated_at（ISO 8601）
    synced_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)  # 最近一次同步时间


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
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="new")  # new | pushed | ...
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)
