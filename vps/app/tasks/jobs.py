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
    """每日推荐生成：画像 → 热榜候选 → 去重已收藏 → 阈值过滤 → 综合打分 → 落库。

    参数为空时使用配置默认值（`RECOMMEND_DAILY_TOP_K` / `RECOMMEND_MIN_SCORE`）；
    外部依赖异常由服务层降级为结构化结果，不向 Celery 抛错。
    """
    from app.services.embedding import get_embedding_service
    from app.services.recommendation_service import generate_daily_recommendations

    db = SessionLocal()
    try:
        result = generate_daily_recommendations(
            db,
            user_id=user_id,
            service=get_embedding_service(),
            top_k=top_k,
            min_score=min_score,
        )
    finally:
        db.close()

    logger.info(
        "推荐生成任务完成: status=%s users=%s created=%d updated=%d expired=%d",
        result.get("status"),
        result.get("users"),
        result.get("created", 0),
        result.get("updated", 0),
        result.get("expired", 0),
    )
    return result


@celery_app.task(name="app.tasks.jobs.evaluate_recommendations")
def evaluate_recommendations(
    user_id: Optional[str] = None,
    match_threshold: Optional[float] = None,
    quality_threshold: Optional[float] = None,
) -> dict[str, Any]:
    """每日推荐评估（M4-01）：质量分 + 匹配度阈值，产出 `qualified` / `filtered`。

    参数为空时使用配置默认值（`EVAL_MATCH_THRESHOLD` / `EVAL_QUALITY_THRESHOLD`）；
    单用户异常由服务层降级为结构化结果，不向 Celery 抛错。
    """
    from app.services.recommendation_eval import evaluate_daily

    db = SessionLocal()
    try:
        result = evaluate_daily(
            db,
            user_id=user_id,
            match_threshold=match_threshold,
            quality_threshold=quality_threshold,
        )
    except Exception as exc:  # noqa: BLE001 - 任务失败降级返回结构化结果
        logger.exception("每日推荐评估任务失败")
        return {"status": "error", "error": str(exc)[:300], "userId": user_id}
    finally:
        db.close()

    logger.info(
        "每日推荐评估任务完成: run=%s total=%d qualified=%d filtered=%d",
        result.get("runId"),
        result.get("total", 0),
        result.get("qualified", 0),
        result.get("filtered", 0),
    )
    return result


@celery_app.task(name="app.tasks.jobs.daily_push")
def daily_push(limit: int = 50) -> dict[str, Any]:
    """每日推送准备：只把通过评估的 `qualified` 推荐标记为 `pushed`。

    真实下发由边缘侧（M4-02 站内通知中心及后续通道）负责；未通过评估的
    `new` / `filtered` 记录不会被推送。
    """
    db = SessionLocal()
    try:
        rows = (
            db.execute(
                select(Recommendation)
                .where(Recommendation.status == "qualified")
                .order_by(Recommendation.quality_score.desc(), Recommendation.score.desc())
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


@celery_app.task(name="app.tasks.jobs.send_bark_notifications")
def send_bark_notifications(
    user_id: Optional[str] = None,
    limit: Optional[int] = None,
) -> dict[str, Any]:
    """Bark 通道（M4-03）：把 `pushed` 且未投递的推荐推送到 iOS。

    参数为空时使用配置默认值（`BARK_MAX_PER_RUN`）；Bark 未启用 / 未配置 /
    网络失败均由服务层降级为结构化结果，不向 Celery 抛错。
    """
    from app.services.bark import dispatch_bark_notifications

    db = SessionLocal()
    try:
        result = dispatch_bark_notifications(db, user_id=user_id, limit=limit)
    except Exception as exc:  # noqa: BLE001 - 任务失败降级返回结构化结果
        logger.exception("Bark 推送任务失败")
        return {"status": "error", "error": str(exc)[:300], "userId": user_id}
    finally:
        db.close()

    logger.info(
        "Bark 推送任务完成: status=%s candidates=%d sent=%d failed=%d",
        result.get("status"),
        result.get("candidates", 0),
        result.get("sent", 0),
        result.get("failed", 0),
    )
    return result


@celery_app.task(name="app.tasks.jobs.send_email_digest")
def send_email_digest(
    user_id: Optional[str] = None,
    limit: Optional[int] = None,
    force: bool = False,
) -> dict[str, Any]:
    """Email 每日精选推送（M4-05）：把 `pushed` 推荐渲染为摘要邮件并投递。

    通道关闭 / 未配置 / 无数据时返回结构化 `disabled` / `not_configured` /
    `empty`；SMTP 异常由服务层降级为 `failed`，不向 Celery 抛错。
    """
    from app.services.email_channel import send_digest

    db = SessionLocal()
    try:
        result = send_digest(db, user_id=user_id, limit=limit, force=force)
    except Exception as exc:  # noqa: BLE001 - 任务失败降级返回结构化结果
        logger.exception("Email 摘要任务失败")
        return {"status": "error", "ok": False, "error": str(exc)[:300]}
    finally:
        db.close()

    logger.info(
        "Email 摘要任务完成: status=%s items=%d",
        result.get("status"),
        result.get("itemCount", 0),
    )
    return result


@celery_app.task(name="app.tasks.jobs.send_telegram_digest")
def send_telegram_digest(
    user_id: Optional[str] = None,
    limit: Optional[int] = None,
    force: bool = False,
) -> dict[str, Any]:
    """Telegram 每日摘要（M4-04）：读取最近进入 pushed 的推荐并下发。

    未启用 / 未配置 / 无数据均返回结构化状态；发送失败写 `telegram_deliveries`
    并返回 error，不向 Celery 抛错，便于边缘侧安全重试。
    """
    from app.services.telegram import send_digest

    db = SessionLocal()
    try:
        result = send_digest(db, user_id=user_id, limit=limit, force=force)
    except Exception as exc:  # noqa: BLE001 - 任务失败降级返回结构化结果
        logger.exception("Telegram 摘要任务失败")
        return {"status": "error", "sent": False, "error": str(exc)[:300]}
    finally:
        db.close()

    logger.info(
        "Telegram 摘要任务完成: status=%s items=%d messages=%d",
        result.get("status"),
        result.get("itemCount", 0),
        result.get("messageCount", 0),
    )
    return result


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
