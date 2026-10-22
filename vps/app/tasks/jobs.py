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
from app.models import Category, MyRepository, Recommendation, TrendingRepository
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
def sync_repositories(
    include_starred: bool = True,
    with_summary: bool = True,
    summary_limit: Optional[int] = None,
    summary_batch_size: Optional[int] = None,
) -> dict[str, Any]:
    """同步 GitHub 仓库（自己的 + 可选 Starred）到本地镜像表。

    `with_summary=True` 时，upsert 完成后把本次变化的仓库交给独立的摘要批量队列，
    同步任务本身不被 LLM 阻塞。
    """
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

    from app.services.repo_health import evaluate_health, utcnow

    created = 0
    updated = 0
    changed_ids: list[str] = []
    db = SessionLocal()
    try:
        for item in repos:
            repo_id = item.get("id") or ""
            if not repo_id:
                continue
            row = db.get(MyRepository, repo_id)
            if row is None:
                row = MyRepository(
                    id=repo_id,
                    platform=item.get("platform") or "github",
                    name=item.get("name") or repo_id.split("/")[-1],
                    description=item.get("description") or "",
                    html_url=item.get("html_url") or f"https://github.com/{repo_id}",
                    stars=int(item.get("stars") or 0),
                    language=item.get("language") or None,
                )
                db.add(row)
                created += 1
                changed_ids.append(repo_id)
            else:
                row.name = item.get("name") or row.name
                row.description = item.get("description") or row.description
                row.html_url = item.get("html_url") or row.html_url
                row.stars = int(item.get("stars") or 0)
                row.language = item.get("language") or row.language
                updated += 1
                changed_ids.append(repo_id)
            # M6-05：同步时顺带落 GitHub 元数据并计算健康度
            if "pushed_at" in item:
                row.pushed_at = item.get("pushed_at")
            if "updated_at" in item:
                row.updated_at = item.get("updated_at")
            if "open_issues_count" in item:
                row.open_issues_count = int(item.get("open_issues_count") or 0)
            if "archived" in item:
                row.archived = bool(item.get("archived"))
            if "disabled" in item:
                row.disabled = bool(item.get("disabled"))
            snapshot = evaluate_health(
                pushed_at=row.pushed_at,
                open_issues_count=row.open_issues_count,
                archived=row.archived,
                disabled=row.disabled,
                stars=row.stars,
            )
            row.health_status = snapshot.status
            row.health_score = snapshot.score
            row.health_checked_at = utcnow()
        db.commit()
    finally:
        db.close()

    summary_task_id: Optional[str] = None
    if with_summary and changed_ids:
        limit = int(summary_limit if summary_limit is not None else settings.SUMMARY_MAX_PER_RUN)
        batch = int(
            summary_batch_size if summary_batch_size is not None else settings.SUMMARY_BATCH_SIZE
        )
        try:
            summary_task = summarize_readmes.delay(
                repo_ids=changed_ids[: max(1, limit)],
                limit=limit,
                batch_size=batch,
            )
            summary_task_id = getattr(summary_task, "id", None)
        except Exception:  # noqa: BLE001 - 入队失败不影响同步结果，可手动补跑
            logger.exception("摘要任务入队失败")

    if created or updated:
        _maybe_enqueue_vectorization("my")

    logger.info(
        "GitHub 同步完成: 共 %d 个仓库（新增 %d / 更新 %d），摘要任务 %s",
        len(repos),
        created,
        updated,
        summary_task_id or "未入队",
    )
    return {
        "status": "ok",
        "total": len(repos),
        "created": created,
        "updated": updated,
        "summaryTaskId": summary_task_id,
    }


@celery_app.task(name="app.tasks.jobs.refresh_repo_health")
def refresh_repo_health(
    repo_ids: Optional[list[str]] = None,
    limit: Optional[int] = None,
    push_to_edge: bool = True,
) -> dict[str, Any]:
    """刷新仓库元数据并重算健康度（M6-05）。

    - 只读 GitHub 公开仓库信息，不修改仓库本身；
    - 更新 VPS 本地镜像后，按配置把健康度快照回写 edge / D1；
    - 未配置 `GITHUB_TOKEN` 时跳过（匿名配额不足以支撑批量刷新）。
    """
    settings = get_settings()
    if not settings.REPO_HEALTH_ENABLED:
        return {"status": "skipped", "reason": "REPO_HEALTH_ENABLED=false"}
    token = (settings.GITHUB_TOKEN or "").strip()
    if not token:
        return {"status": "skipped", "reason": "GITHUB_TOKEN 未配置，跳过健康度刷新"}

    from app.services.repo_health import refresh_and_push

    max_count = int(limit if limit is not None else settings.REPO_HEALTH_MAX_PER_RUN)
    db = SessionLocal()
    try:
        result = _run_async(
            refresh_and_push(
                db,
                repo_ids,
                token=token,
                max_count=max_count,
                edge_base_url=settings.EDGE_BASE_URL if push_to_edge else "",
                internal_token=settings.INTERNAL_TOKEN,
            )
        )
    except Exception as exc:  # noqa: BLE001 - 任务失败降级返回结构化结果
        logger.exception("项目健康度刷新失败")
        return {"status": "error", "error": str(exc)[:300]}
    finally:
        db.close()

    logger.info(
        "项目健康度刷新完成: 检查 %d / 跳过 %d / edge=%s",
        result.get("checked", 0),
        result.get("skipped", 0),
        result.get("edge", {}).get("status"),
    )
    return result


@celery_app.task(bind=True, name="app.tasks.jobs.summarize_readmes")
def summarize_readmes(
    self,
    repo_ids: Optional[list[str]] = None,
    limit: Optional[int] = None,
    batch_size: Optional[int] = None,
    force: bool = False,
    max_chars: Optional[int] = None,
    source: str = "my",
) -> dict[str, Any]:
    """批量生成 README 中文摘要（Ollama → DeepSeek → 截断降级）。

    `source` 支持 `my` / `trending` / `all`；作为独立 Celery 任务排队执行，
    避免阻塞同步任务；`PROGRESS` 状态供边缘侧轮询。
    """
    from app.services.summary_pipeline import summarize_repositories

    def report(meta: dict[str, Any]) -> None:
        try:
            self.update_state(state="PROGRESS", meta=meta)
        except Exception:  # noqa: BLE001 - 进度上报失败不影响摘要生成
            logger.debug("摘要任务进度上报失败", exc_info=True)

    stats = summarize_repositories(
        repo_ids=repo_ids,
        limit=limit,
        batch_size=batch_size,
        force=force,
        max_chars=max_chars,
        source=source,
        batch_id=getattr(self.request, "id", None) or None,
        progress=report,
    )
    logger.info(
        "README 摘要批量完成（source=%s）: 共 %d 条（成功 %d / 跳过 %d / 失败 %d，抽检 %d）",
        stats.get("source", source),
        stats.get("total", 0),
        stats.get("summarized", 0),
        stats.get("skipped", 0),
        stats.get("failed", 0),
        stats.get("sampled", 0),
    )
    return stats


@celery_app.task(name="app.tasks.jobs.crawl_trending")
def crawl_trending(
    platform: str = "github",
    language: Optional[str] = None,
    languages: Optional[list[str] | str] = None,
    since: str = "daily",
    with_summary: bool = True,
    summary_limit: Optional[int] = None,
) -> dict[str, Any]:
    """抓取热榜（GitHub Trending 全局页 + 多语言页，可选 Gitee）并 upsert。

    - 未指定 `language` 时按 `languages`（默认 `TRENDING_LANGUAGES`）抓取多语言页；
    - 容错（M2-02）：单页失败只记录并继续其他页，抓取 / 解析 / 告警任何环节都不抛异常；
    - `with_summary=True` 时，抓取完成后把本次变化的热榜仓库交给摘要队列，
      由 M2-04 的批量管线生成中文摘要并回写 D1。
    """
    from app.services.crawl_guard import process_crawl_health
    from app.services.readme import extract_tech_stack
    from app.services.trending_crawler import (
        crawl_gitee_explore,
        crawl_github_trending_pages,
    )
    from app.services.trending_snapshot import push_trending_snapshots, save_trending_snapshots

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
            gitee_items = _run_async(crawl_gitee_explore())
            items.extend(gitee_items)
            pages.append(
                {
                    "platform": "gitee",
                    "language": "gitee",
                    "ok": True,
                    "count": len(gitee_items),
                    "error": None,
                }
            )
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
    changed_ids: list[str] = []
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
                " ".join(
                    filter(None, [item.get("name"), item.get("description"), item.get("language")])
                ),
                language=item.get("language"),
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
            changed_ids.append(repo_id)
        db.commit()
        # M2-05：写按日快照（去重 + 趋势字段）；失败不影响抓取主流程
        try:
            snapshot_result = save_trending_snapshots(db, items, snapshot_date=today)
        except Exception as exc:  # noqa: BLE001 - 快照失败降级，不影响最新状态
            logger.exception("热榜快照入库失败")
            snapshot_result = {
                "date": today.isoformat(),
                "total": 0,
                "created": 0,
                "updated": 0,
                "rows": [],
                "error": str(exc)[:300],
            }
    finally:
        db.close()

    # M2-05：快照批量回写边缘 D1（未配置 EDGE_BASE_URL / INTERNAL_TOKEN 时跳过）
    push_result = {"skipped": True, "pushed": 0, "failed": 0, "batches": 0}
    if snapshot_result.get("rows"):
        try:
            push_result = push_trending_snapshots(snapshot_result["rows"], today)
        except Exception as exc:  # noqa: BLE001 - 回写失败只记录，任务仍算成功
            logger.exception("热榜快照回写边缘失败")
            push_result = {"skipped": False, "pushed": 0, "failed": len(snapshot_result["rows"]), "batches": 0, "error": str(exc)[:300]}

    snapshots = {
        "date": snapshot_result.get("date"),
        "total": snapshot_result.get("total", 0),
        "created": snapshot_result.get("created", 0),
        "updated": snapshot_result.get("updated", 0),
        "pushed": push_result.get("pushed", 0),
        "pushFailed": push_result.get("failed", 0),
        "skipped": push_result.get("skipped", True),
    }
    if snapshot_result.get("error"):
        snapshots["error"] = snapshot_result["error"]
    if push_result.get("error"):
        snapshots["pushError"] = push_result["error"]

    # M2-02：页面健康判定与告警（独立会话，任何异常都不影响抓取结果）
    health: dict[str, Any] = {"created": 0, "deduplicated": 0, "alerts": []}
    try:
        health_db = SessionLocal()
        try:
            health = process_crawl_health(
                health_db,
                platform="github" if platform in ("github", "all", "") else platform,
                pages=pages,
                total_items=len(items),
                settings=settings,
            )
        finally:
            health_db.close()
    except Exception:  # noqa: BLE001 - 告警失败不能影响抓取
        logger.exception("热榜抓取告警处理失败（抓取结果已保留）")

    failed_pages = [page for page in pages if not page.get("ok", True)]
    if not items and failed_pages:
        status = "error"
    elif failed_pages:
        status = "partial"
    else:
        status = "ok"

    # M2-04：把本次变化的热榜仓库交给摘要队列（失败不影响抓取结果，可手动补跑）
    summary_task_id: Optional[str] = None
    if with_summary and changed_ids:
        limit = int(summary_limit if summary_limit is not None else settings.SUMMARY_MAX_PER_RUN)
        try:
            summary_task = summarize_readmes.delay(
                repo_ids=changed_ids[: max(1, limit)],
                limit=limit,
                source="trending",
            )
            summary_task_id = getattr(summary_task, "id", None)
        except Exception:  # noqa: BLE001 - 入队失败不影响抓取结果，可手动补跑
            logger.exception("热榜摘要任务入队失败")

    if items:
        _maybe_enqueue_vectorization("trending")

    logger.info(
        "热榜抓取完成: 共 %d 条（新增 %d / 更新 %d，失败页 %d，告警 %d），摘要任务 %s",
        len(items),
        created,
        updated,
        len(failed_pages),
        health.get("created", 0),
        summary_task_id or "未入队",
    )
    return {
        "status": status,
        "platform": platform,
        "total": len(items),
        "created": created,
        "updated": updated,
        "pages": pages,
        "failedPages": failed_pages,
        "snapshots": snapshots,
        "alerts": health,
        "summaryTaskId": summary_task_id,
    }


@celery_app.task(name="app.tasks.jobs.cleanup_trending_data")
def cleanup_trending_data(
    retention_days: Optional[int] = None,
    archive: Optional[bool] = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """热榜数据保留：本地归档 + 删除，随后清理 D1 同日期范围快照。

    归档失败时服务层会中止删除并返回 error；D1 清理失败只标记 partial，不影响本地结果。
    """
    from app.services.trending_retention import (
        cleanup_edge_trending_snapshots,
        cleanup_trending_snapshots,
    )

    db = SessionLocal()
    try:
        result = cleanup_trending_snapshots(
            db,
            retention_days=retention_days,
            archive=archive,
            dry_run=dry_run,
        )
    except Exception as exc:  # noqa: BLE001 - 任务失败降级为结构化结果
        logger.exception("热榜保留清理失败")
        return {"status": "error", "error": str(exc)[:300]}
    finally:
        db.close()

    cutoff = result.get("cutoff")
    if cutoff and result.get("status") in ("ok", "dry_run"):
        edge_result = cleanup_edge_trending_snapshots(
            date.fromisoformat(cutoff),
            dry_run=dry_run,
        )
        result["edge"] = edge_result
        if edge_result.get("error") and result.get("status") == "ok":
            result["status"] = "partial"

    return result


@celery_app.task(name="app.tasks.jobs.generate_recommendations")
def generate_recommendations(
    user_id: Optional[str] = None,
    top_k: Optional[int] = None,
    min_score: Optional[float] = None,
) -> dict[str, Any]:
    """每日推荐生成：反馈排除 → 画像 / 候选 / 打分 → 落库 → 回写 edge。

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


@celery_app.task(name="app.tasks.jobs.regenerate_recommendation_reasons")
def regenerate_recommendation_reasons(
    user_id: Optional[str] = None, limit: int = 500
) -> dict[str, Any]:
    """按当前模板重算存量推荐的中文理由与依据字段（模板升级 / 画像变化后使用）。"""
    from app.services.recommend_reason import build_reason_detail, build_user_profile
    from app.services.recommendation_feedback import push_recommendations

    db = SessionLocal()
    try:
        my_repos = db.execute(select(MyRepository).limit(1000)).scalars().all()
        category_names = {
            row.id: row.name for row in db.execute(select(Category)).scalars().all()
        }
        interest_profile = build_user_profile(my_repos, category_names)

        stmt = select(Recommendation).order_by(Recommendation.score.desc()).limit(max(1, int(limit)))
        if user_id:
            stmt = stmt.where(Recommendation.user_id == user_id)
        rows = list(db.execute(stmt).scalars().all())
        if not rows:
            return {"status": "skipped", "reason": "没有可回填的推荐", "updated": 0}

        repo_ids = {row.repo_id for row in rows}
        trending = {
            item.id: item
            for item in db.execute(
                select(TrendingRepository).where(TrendingRepository.id.in_(repo_ids))
            ).scalars().all()
        }
        mine = {
            item.id: item
            for item in db.execute(
                select(MyRepository).where(MyRepository.id.in_(repo_ids))
            ).scalars().all()
        }

        updated = 0
        for row in rows:
            source = trending.get(row.repo_id) or mine.get(row.repo_id)
            detail = build_reason_detail(
                source if source is not None else {"id": row.repo_id, "name": row.repo_id},
                float(row.score or 0),
                interest_profile,
            )
            row.reason = detail.reason
            row.based_on = detail.based_on_json
            updated += 1
        db.commit()

        # 回写 edge D1（推荐页读取）；失败只记日志
        target_users = sorted({str(row.user_id) for row in rows if row.user_id})
        pushed = {uid: push_recommendations(db, uid) for uid in target_users}
    finally:
        db.close()

    logger.info("推荐理由回填完成: %d 条", updated)
    return {"status": "ok", "updated": updated, "pushed": pushed}


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
    run_id: Optional[str] = None,
    mode: str = "incremental",
    scope: str = "all",
    limit: Optional[int] = None,
    batch_size: Optional[int] = None,
) -> dict[str, Any]:
    """Vectorize 索引同步（增量 / 全量），带 PROGRESS 进度。"""
    from app.services import vector_index

    def progress(meta: dict[str, Any]) -> None:
        try:
            if not self.request.is_eager:
                self.update_state(state="PROGRESS", meta=meta)
        except Exception:  # noqa: BLE001 - 进度上报失败不影响同步
            logger.debug("进度上报失败", exc_info=True)

    return vector_index.sync_vectors(
        run_id=run_id,
        mode=mode,
        scope=scope,
        limit=limit,
        batch_size=batch_size,
        progress=progress,
    )


@celery_app.task(name="app.tasks.jobs.reconcile_vector_index")
def reconcile_vector_index(
    scope: str = "all",
    repair: bool = False,
    limit: Optional[int] = None,
) -> dict[str, Any]:
    """Vectorize 索引对账（可选修复缺失 / 过期向量）。"""
    from app.services import vector_index

    return vector_index.reconcile_vectors(scope=scope, repair=repair, limit=limit)
