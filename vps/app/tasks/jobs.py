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


def _report_progress(task: Any, progress: Any) -> None:
    """把同步进度写入 Celery 任务 meta；上报失败只记日志，不影响同步。"""
    try:
        task.update_state(state="PROGRESS", meta=progress.to_dict())
    except Exception as exc:  # noqa: BLE001 - 结果后端不可用时进度降级为日志
        logger.debug("Celery 进度上报失败: %s", exc)
    if getattr(progress, "done", False):
        logger.info("同步进度: %s 完成，共 %d 条", progress.phase, progress.fetched)
    else:
        logger.info(
            "同步进度: %s 第 %d/%s 页，已抓取 %d 条",
            progress.phase,
            progress.page,
            progress.pages_total or "?",
            progress.fetched,
        )


@celery_app.task(bind=True, name="app.tasks.jobs.sync_repositories")
def sync_repositories(
    self,
    include_starred: bool = True,
    per_page: int = 100,
    max_pages: int = 10,
) -> dict[str, Any]:
    """同步 GitHub 仓库（自己的 + 可选 Starred）到本地镜像表。

    Starred 走全量分页（不限页数）；自有仓库默认最多 `max_pages` 页（M1-06 再扩展）。
    """
    settings = get_settings()
    token = (settings.GITHUB_TOKEN or "").strip()
    if not token:
        return {"status": "skipped", "reason": "GITHUB_TOKEN 未配置，跳过 GitHub 同步"}

    from app.services.github_service import list_user_repos
    from app.services.sync import upsert_repositories

    def on_progress(progress: Any) -> None:
        _report_progress(self, progress)

    async def _run() -> dict[str, int]:
        db = SessionLocal()
        try:
            repos = await list_user_repos(
                token,
                include_starred=include_starred,
                per_page=per_page,
                max_pages=max_pages,
                on_progress=on_progress,
            )
            return upsert_repositories(db, repos)
        finally:
            db.close()

    try:
        counts = _run_async(_run())
    except Exception as exc:  # noqa: BLE001 - 同步失败降级返回，等待下次重试
        logger.exception("GitHub 同步失败")
        return {"status": "error", "error": str(exc)[:300]}

    logger.info(
        "GitHub 同步完成: 共 %d 个仓库（新增 %d / 更新 %d / 未变化 %d）",
        counts["total"],
        counts["created"],
        counts["updated"],
        counts["unchanged"],
    )
    return {"status": "ok", **counts}


@celery_app.task(bind=True, name="app.tasks.jobs.sync_starred_repositories")
def sync_starred_repositories(
    self,
    per_page: int = 100,
    max_pages: int | None = None,
) -> dict[str, Any]:
    """全量同步 Starred 仓库（分页 / 限流 / 重试 / 进度）。

    - `max_pages=None`：不设页数上限，拉取全部 Starred；
    - 每页通过 `update_state(state="PROGRESS")` 上报进度，`GET /api/tasks/{id}` 可查。
    """
    settings = get_settings()
    token = (settings.GITHUB_TOKEN or "").strip()
    if not token:
        return {"status": "skipped", "reason": "GITHUB_TOKEN 未配置，跳过 Starred 同步"}

    from app.services.sync import sync_starred_to_db

    def on_progress(progress: Any) -> None:
        _report_progress(self, progress)

    async def _run() -> dict[str, Any]:
        db = SessionLocal()
        try:
            return await sync_starred_to_db(
                db,
                token,
                per_page=per_page,
                max_pages=max_pages,
                on_progress=on_progress,
            )
        finally:
            db.close()

    try:
        result = _run_async(_run())
    except Exception as exc:  # noqa: BLE001 - 任务失败降级返回，边缘侧可安全重试
        logger.exception("Starred 同步失败")
        return {"status": "error", "error": str(exc)[:300]}

    logger.info("Starred 同步任务结束: %s", result.get("status"))
    return result


@celery_app.task(name="app.tasks.jobs.crawl_trending")
def crawl_trending(platform: str = "github", language: Optional[str] = None) -> dict[str, Any]:
    """抓取热榜（GitHub Trending，可选 Gitee）并 upsert 到 trending 表。"""
    from app.services.readme import extract_tech_stack
    from app.services.trending_crawler import crawl_gitee_explore, crawl_github_trending

    items: list[dict[str, Any]] = []
    try:
        if platform in ("github", "all", ""):
            items.extend(_run_async(crawl_github_trending(language=language)))
        if platform in ("gitee", "all"):
            items.extend(_run_async(crawl_gitee_explore()))
    except Exception as exc:  # noqa: BLE001 - 抓取失败降级返回空结果
        logger.exception("热榜抓取失败")
        return {"status": "error", "error": str(exc)[:300]}

    created = 0
    updated = 0
    db = SessionLocal()
    try:
        for item in items:
            repo_id = item.get("id") or ""
            if not repo_id:
                continue
            tech_stack = extract_tech_stack(
                " ".join(filter(None, [item.get("description"), item.get("language")]))
            )
            row = db.get(TrendingRepository, repo_id)
            if row is None:
                db.add(
                    TrendingRepository(
                        id=repo_id,
                        platform=item.get("platform") or "github",
                        name=item.get("name") or repo_id.split("/")[-1],
                        html_url=item.get("html_url") or "",
                        stars_today=int(item.get("stars_today") or 0),
                        description=item.get("description") or "",
                        tech_stack=tech_stack,
                        crawled_at=date.today(),
                    )
                )
                created += 1
            else:
                row.platform = item.get("platform") or row.platform
                row.name = item.get("name") or row.name
                row.html_url = item.get("html_url") or row.html_url
                row.stars_today = int(item.get("stars_today") or 0)
                row.description = item.get("description") or row.description
                row.tech_stack = tech_stack or row.tech_stack
                row.crawled_at = date.today()
                updated += 1
        db.commit()
    finally:
        db.close()

    logger.info("热榜抓取完成: 共 %d 条（新增 %d / 更新 %d）", len(items), created, updated)
    return {"status": "ok", "total": len(items), "created": created, "updated": updated}


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
