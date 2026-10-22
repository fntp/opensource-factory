"""Celery 任务：GitHub 同步 / 热榜抓取 / 推荐生成 / 每日推送准备。

任务均为**薄封装**：调用 services 完成业务，再落库；
所有外部依赖失败一律降级为结构化返回值（不抛异常），保证边缘侧可安全重试。
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import logging
from datetime import date
from typing import Any, Coroutine, Optional
from uuid import uuid4

from sqlalchemy import select

from app.config import get_settings
from app.db import SessionLocal
from app.models import MyRepository, Recommendation, TrendingRepository, User
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


def _run_async(coro: Coroutine[Any, Any, Any]) -> Any:
    """在同步 Celery 任务中执行协程；若已处于事件循环（eager 模式），另起线程执行。"""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


@celery_app.task(name="app.tasks.jobs.sync_repositories")
def sync_repositories(include_starred: bool = True) -> dict[str, Any]:
    """同步 GitHub 仓库（自己的 + 可选 Starred）到本地镜像表。"""
    settings = get_settings()
    token = (settings.GITHUB_TOKEN or "").strip()
    if not token:
        return {"status": "skipped", "reason": "GITHUB_TOKEN 未配置，跳过 GitHub 同步"}

    from app.services.github_service import list_user_repos

    try:
        repos = _run_async(list_user_repos(token, include_starred=include_starred))
    except Exception as exc:  # noqa: BLE001 - 同步失败降级返回，等待下次重试
        logger.exception("GitHub 同步失败")
        return {"status": "error", "error": str(exc)[:300]}

    created = 0
    updated = 0
    db = SessionLocal()
    try:
        for item in repos:
            repo_id = item.get("id") or ""
            if not repo_id:
                continue
            row = db.get(MyRepository, repo_id)
            if row is None:
                db.add(
                    MyRepository(
                        id=repo_id,
                        platform=item.get("platform") or "github",
                        name=item.get("name") or repo_id.split("/")[-1],
                        description=item.get("description") or "",
                        html_url=item.get("html_url") or f"https://github.com/{repo_id}",
                        stars=int(item.get("stars") or 0),
                        language=item.get("language") or None,
                    )
                )
                created += 1
            else:
                row.name = item.get("name") or row.name
                row.description = item.get("description") or row.description
                row.html_url = item.get("html_url") or row.html_url
                row.stars = int(item.get("stars") or 0)
                row.language = item.get("language") or row.language
                updated += 1
        db.commit()
    finally:
        db.close()

    logger.info("GitHub 同步完成: 共 %d 个仓库（新增 %d / 更新 %d）", len(repos), created, updated)
    return {"status": "ok", "total": len(repos), "created": created, "updated": updated}


@celery_app.task(name="app.tasks.jobs.crawl_trending")
def crawl_trending(
    platform: str = "github",
    language: Optional[str] = None,
    languages: Optional[list[str] | str] = None,
    since: str = "daily",
) -> dict[str, Any]:
    """抓取热榜（GitHub Trending 全局页 + 多语言页，可选 Gitee）并 upsert。

    - 未指定 `language` 时按 `languages`（默认 `TRENDING_LANGUAGES`）抓取多语言页；
    - 页面级失败不中断整轮，返回 `pages` / `failedPages` 供告警与排查。
    """
    from app.services.readme import extract_tech_stack
    from app.services.trending_crawler import (
        crawl_gitee_explore,
        crawl_github_trending_pages,
    )

    settings = get_settings()
    items: list[dict[str, Any]] = []
    pages: list[dict[str, Any]] = []
    try:
        if platform in ("github", "all", ""):
            if language:
                result = _run_async(
                    crawl_github_trending_pages(
                        languages=[language],
                        since=since,
                        include_global=False,
                    )
                )
            else:
                configured = settings.TRENDING_LANGUAGES if languages is None else languages
                result = _run_async(
                    crawl_github_trending_pages(languages=configured, since=since)
                )
            items.extend(result.get("items") or [])
            pages.extend(result.get("pages") or [])
        if platform in ("gitee", "all"):
            items.extend(_run_async(crawl_gitee_explore()))
    except Exception as exc:  # noqa: BLE001 - 抓取失败降级返回空结果
        logger.exception("热榜抓取失败")
        return {"status": "error", "error": str(exc)[:300], "pages": pages}

    # 跨平台 / 多页去重（同一 owner/repo 只保留一条）
    unique: dict[str, dict[str, Any]] = {}
    for item in items:
        repo_id = str(item.get("id") or "").strip()
        if repo_id and repo_id not in unique:
            unique[repo_id] = item
    items = list(unique.values())

    created = 0
    updated = 0
    today = date.today()
    db = SessionLocal()
    try:
        for item in items:
            repo_id = str(item.get("id") or "").strip()
            if not repo_id:
                continue
            owner = item.get("owner") or repo_id.split("/")[0]
            language_name = (item.get("language") or "").strip() or None
            stars = int(item.get("stars") or 0)
            stars_today = int(item.get("stars_today") or 0)
            tech_stack = extract_tech_stack(
                " ".join(filter(None, [item.get("description"), language_name]))
            )
            row = db.get(TrendingRepository, repo_id)
            if row is None:
                db.add(
                    TrendingRepository(
                        id=repo_id,
                        platform=item.get("platform") or "github",
                        name=item.get("name") or repo_id.split("/")[-1],
                        html_url=item.get("html_url") or "",
                        stars_today=stars_today,
                        description=item.get("description") or "",
                        tech_stack=tech_stack,
                        owner=owner,
                        language=language_name,
                        stars=stars,
                        crawled_at=today,
                    )
                )
                created += 1
            else:
                row.platform = item.get("platform") or row.platform
                row.name = item.get("name") or row.name
                row.html_url = item.get("html_url") or row.html_url
                row.owner = owner or row.owner
                row.language = language_name or row.language
                row.stars = stars
                row.stars_today = stars_today
                if item.get("description"):
                    row.description = item["description"]
                row.tech_stack = tech_stack or row.tech_stack
                row.crawled_at = today
                updated += 1
        db.commit()
    finally:
        db.close()

    failed_pages = [page for page in pages if not page.get("ok", True)]
    if not items and failed_pages:
        status = "error"
    elif failed_pages:
        status = "partial"
    else:
        status = "ok"

    logger.info(
        "热榜抓取完成: 共 %d 条（新增 %d / 更新 %d，失败页 %d）",
        len(items),
        created,
        updated,
        len(failed_pages),
    )
    return {
        "status": status,
        "platform": platform,
        "total": len(items),
        "created": created,
        "updated": updated,
        "pages": pages,
        "failedPages": failed_pages,
    }


@celery_app.task(name="app.tasks.jobs.generate_recommendations")
def generate_recommendations(user_id: Optional[str] = None, top_k: int = 20) -> dict[str, Any]:
    """生成推荐：以本地仓库集合的平均向量为用户画像，对热榜候选排序后落库。"""
    from app.services.embedding import get_embedding_service
    from app.services.recommender import build_reason, recommend

    service = get_embedding_service()
    db = SessionLocal()
    try:
        # 目标用户：指定用户 → 全部用户 → 兜底创建 default（单机自测友好）
        if user_id:
            target_users = [user_id]
        else:
            target_users = [u.id for u in db.execute(select(User)).scalars().all()]
            if not target_users:
                if db.get(User, "default") is None:
                    db.add(User(id="default", username="default"))
                    db.commit()
                target_users = ["default"]

        # 用户画像：本地镜像仓库文本的平均向量
        my_repos = db.execute(select(MyRepository).limit(1000)).scalars().all()
        profile_texts = [
            " ".join(filter(None, [r.name, r.description or "", r.readme_summary or "", r.language or ""]))
            for r in my_repos
        ]
        if not profile_texts:
            return {"status": "skipped", "reason": "本地没有仓库数据，无法构建用户画像"}

        profile_vectors = service.encode(profile_texts)
        dim = len(profile_vectors[0])
        profile_vec = service.normalize(
            [sum(vec[i] for vec in profile_vectors) / len(profile_vectors) for i in range(dim)]
        )

        # 候选：热榜仓库
        trending_rows = db.execute(select(TrendingRepository).limit(500)).scalars().all()
        if not trending_rows:
            return {"status": "skipped", "reason": "热榜数据为空，请先执行 crawl-trending"}
        candidate_texts = [
            " ".join(filter(None, [r.name, r.description or "", r.tech_stack or ""]))
            for r in trending_rows
        ]
        candidate_vectors = service.encode(candidate_texts)
        ranked = recommend(
            profile_vec,
            [(row.id, vec) for row, vec in zip(trending_rows, candidate_vectors)],
            top_k=max(1, int(top_k)),
        )

        by_id = {row.id: row for row in trending_rows}
        created = 0
        for repo_id, score in ranked:
            row = by_id.get(repo_id)
            if row is None:
                continue
            for uid in target_users:
                existing = db.execute(
                    select(Recommendation).where(
                        Recommendation.user_id == uid, Recommendation.repo_id == repo_id
                    )
                ).scalar_one_or_none()
                if existing is not None:
                    existing.score = float(score)
                    existing.reason = build_reason(row, score)
                    continue
                db.add(
                    Recommendation(
                        id=uuid4().hex,
                        user_id=uid,
                        repo_id=repo_id,
                        score=float(score),
                        reason=build_reason(row, score),
                        status="new",
                    )
                )
                created += 1
        db.commit()
    finally:
        db.close()

    logger.info("推荐生成完成: 用户 %s，新增 %d 条", target_users, created)
    return {"status": "ok", "users": target_users, "created": created}


@celery_app.task(name="app.tasks.jobs.daily_push")
def daily_push(limit: int = 50) -> dict[str, Any]:
    """每日推送准备（占位）：把 `new` 状态的推荐标记为 `pushed`，由边缘侧负责真正下发。"""
    db = SessionLocal()
    try:
        rows = (
            db.execute(
                select(Recommendation)
                .where(Recommendation.status == "new")
                .order_by(Recommendation.score.desc())
                .limit(max(1, int(limit)))
            )
            .scalars()
            .all()
        )
        for row in rows:
            row.status = "pushed"
        db.commit()
        pushed = len(rows)
    finally:
        db.close()

    logger.info("每日推送准备完成: %d 条", pushed)
    return {"status": "ok", "pushed": pushed}
