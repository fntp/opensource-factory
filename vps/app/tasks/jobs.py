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

from sqlalchemy import select

from app.config import get_settings
from app.db import SessionLocal
from app.models import MyRepository, Recommendation, TrendingRepository
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


def _maybe_enqueue_vectorization(scope: str) -> None:
    """同步 / 抓取完成后自动入队增量向量化；失败不影响主任务。"""
    if not get_settings().VECTORIZE_AUTO:
        return
    try:
        vectorize_repositories.delay(scope=scope)
    except Exception:  # noqa: BLE001 - 自动任务失败只记录，不阻塞主流程
        logger.warning("自动入队向量化失败（scope=%s）", scope, exc_info=True)


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

    if created or updated:
        _maybe_enqueue_vectorization("my")
    logger.info("GitHub 同步完成: 共 %d 个仓库（新增 %d / 更新 %d）", len(repos), created, updated)
    return {"status": "ok", "total": len(repos), "created": created, "updated": updated}


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

    if items:
        _maybe_enqueue_vectorization("trending")
    logger.info("热榜抓取完成: 共 %d 条（新增 %d / 更新 %d）", len(items), created, updated)
    return {"status": "ok", "total": len(items), "created": created, "updated": updated}


@celery_app.task(name="app.tasks.jobs.generate_recommendations")
def generate_recommendations(
    user_id: Optional[str] = None,
    top_k: Optional[int] = None,
    min_score: Optional[float] = None,
) -> dict[str, Any]:
    """每日推荐生成：反馈排除 → 画像 / 候选 / 打分 → 落库 → 回写 edge。

    M3-05 提供画像、候选、阈值与打分；M3-07 在此之上先拉取用户反馈（saved /
    dismissed）做排除，生成后再把推荐快照回写 D1。edge 未配置或不可达时只影响
    回写，不影响本地生成。参数为空时使用配置默认值。
    """
    from app.models import User
    from app.services.embedding import get_embedding_service
    from app.services.recommendation_feedback import fetch_feedback, push_recommendations
    from app.services.recommendation_service import generate_daily_recommendations

    db = SessionLocal()
    try:
        if user_id:
            target_users = [str(user_id)]
        else:
            target_users = [
                str(item) for item in db.execute(select(User.id)).scalars().all()
            ]
            if not target_users:
                if db.get(User, "default") is None:
                    db.add(User(id="default", username="default"))
                    db.commit()
                target_users = ["default"]

        results: list[dict[str, Any]] = []
        pushed: dict[str, int] = {}
        feedback_excluded: dict[str, int] = {}
        embedding = get_embedding_service()
        for uid in target_users:
            snapshot = fetch_feedback(db, uid)
            feedback_excluded[uid] = len(snapshot.excluded_repo_ids)
            summary = generate_daily_recommendations(
                db,
                user_id=uid,
                service=embedding,
                top_k=top_k,
                min_score=min_score,
                excluded_repo_ids=snapshot.excluded_repo_ids,
            )
            results.extend(summary.get("results", []))
            pushed[uid] = push_recommendations(db, uid)

        ok_results = [item for item in results if item.get("status") == "ok"]
        error_results = [item for item in results if item.get("status") == "error"]
        if ok_results:
            status = "ok"
        elif error_results:
            status = "error"
        else:
            status = "skipped"

        effective_top_k = max(
            1, int(top_k if top_k is not None else get_settings().RECOMMEND_DAILY_TOP_K)
        )
        effective_min_score = float(
            get_settings().RECOMMEND_MIN_SCORE if min_score is None else min_score
        )
        result = {
            "status": status,
            "users": target_users,
            "userCount": len(target_users),
            "created": sum(int(item.get("created", 0)) for item in results),
            "updated": sum(int(item.get("updated", 0)) for item in results),
            "expired": sum(int(item.get("expired", 0)) for item in results),
            "selected": sum(int(item.get("selected", 0)) for item in results),
            "minScore": round(max(0.0, min(1.0, effective_min_score)), 4),
            "topK": effective_top_k,
            "feedbackExcluded": feedback_excluded,
            "pushed": pushed,
            "results": results,
        }
    finally:
        db.close()

    logger.info(
        "推荐生成任务完成: status=%s users=%s created=%d updated=%d expired=%d 反馈排除=%s 回写=%s",
        result.get("status"),
        result.get("users"),
        result.get("created", 0),
        result.get("updated", 0),
        result.get("expired", 0),
        feedback_excluded,
        pushed,
    )
    return result


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


@celery_app.task(bind=True, name="app.tasks.jobs.vectorize_repositories")
def vectorize_repositories(
    self,
    scope: str = "all",
    limit: Optional[int] = None,
    batch_size: Optional[int] = None,
    force: bool = False,
    run_id: Optional[str] = None,
) -> dict[str, Any]:
    """向量化任务：批量 / 增量 / 断点续跑。

    - `run_id` 为空时新建运行；传入失败运行的 id 时从游标续跑；
    - 进度通过 Celery `PROGRESS` 状态上报（eager 模式下后端不可用时静默跳过）。
    """
    from app.services.vector_pipeline import create_run, run_vectorization

    try:
        if run_id is None:
            db = SessionLocal()
            try:
                run = create_run(
                    db,
                    scope=scope,
                    limit=limit,
                    batch_size=batch_size,
                    force=force,
                )
                run_id = run.id
            finally:
                db.close()

        def progress(meta: dict[str, Any]) -> None:
            try:
                self.update_state(state="PROGRESS", meta=meta)
            except Exception:  # noqa: BLE001 - 进度上报失败不影响向量化
                logger.debug("向量化进度上报失败（run=%s）", run_id, exc_info=True)

        return run_vectorization(run_id, progress=progress)
    except Exception as exc:  # noqa: BLE001 - 任务失败降级返回结构化结果
        logger.exception("向量化任务失败（run=%s）", run_id)
        return {"status": "error", "error": str(exc)[:300], "runId": run_id}


@celery_app.task(bind=True, name="app.tasks.jobs.sync_vector_index")
def sync_vector_index(
    self,
    kind: str = "sync",
    scope: str = "all",
    limit: Optional[int] = None,
    batch_size: Optional[int] = None,
    force: bool = False,
) -> dict[str, Any]:
    """Vectorize 索引同步任务：批量 upsert / 对账。

    - `kind=sync`：增量（默认）或 `force=True` 全量；
    - `kind=reconcile`：先对账，仅修复缺失 / 过期向量；
    - 未配置 edge 地址 / 内部令牌时返回 `disabled`，不抛异常。
    """
    from app.services.vector_sync import (
        VectorIndexDisabled,
        VectorIndexError,
        sync_vector_index as run_sync,
    )

    def progress(meta: dict[str, Any]) -> None:
        try:
            self.update_state(state="PROGRESS", meta=meta)
        except Exception:  # noqa: BLE001 - 进度上报失败不影响同步
            logger.debug("索引同步进度上报失败", exc_info=True)

    try:
        return run_sync(
            kind=kind,
            scope=scope,
            limit=limit,
            batch_size=batch_size,
            force=force,
            progress=progress,
        )
    except VectorIndexDisabled as exc:
        logger.info("Vectorize 索引同步跳过：%s", exc)
        return {"status": "disabled", "error": str(exc)}
    except VectorIndexError as exc:
        logger.warning("Vectorize 索引同步失败：%s", exc)
        return {"status": "error", "error": str(exc)[:500]}
    except Exception as exc:  # noqa: BLE001 - 任务失败降级为结构化结果
        logger.exception("Vectorize 索引同步异常")
        return {"status": "error", "error": str(exc)[:500]}
