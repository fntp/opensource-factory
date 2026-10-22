"""Celery 应用与定时计划。

- broker / backend：`REDIS_URL`（默认 `redis://localhost:6379/0`）；
- `CELERY_TASK_ALWAYS_EAGER=1` 时任务同步执行（本地调试 / 测试）；
- beat 计划：每日抓取热榜（全局页 + 多语言页）、每日 08:30 生成推荐、每日 09:00 推送准备、
  每日 SQLite 快照（默认 03:50）与每周日恢复演练（默认 04:20）。
"""
from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

from app.config import get_settings

settings = get_settings()

celery_app = Celery(
    "opensource_factory",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=["app.tasks.jobs"],
)

celery_app.conf.update(
    task_always_eager=settings.CELERY_TASK_ALWAYS_EAGER,
    task_eager_propagates=False,  # 急切模式下任务异常不向上抛，交由任务自身降级返回
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="Asia/Shanghai",
    enable_utc=True,
    task_track_started=True,
    broker_connection_retry_on_startup=True,
)

# 定时计划（配合 `celery -A app.tasks.celery_app beat` 使用）
# 热榜每日抓取：默认 03:27（Asia/Shanghai），全局页 + TRENDING_LANGUAGES 配置的多语言页。
celery_app.conf.beat_schedule = {
    "crawl-trending-daily": {
        "task": "app.tasks.jobs.crawl_trending",
        "schedule": crontab(
            minute=settings.TRENDING_CRAWL_MINUTE,
            hour=settings.TRENDING_CRAWL_HOUR,
        ),
        "kwargs": {"platform": "github", "languages": settings.TRENDING_LANGUAGES},
    },
    "cleanup-trending-daily": {
        "task": "app.tasks.jobs.cleanup_trending_data",
        "schedule": crontab(
            minute=settings.TRENDING_RETENTION_MINUTE,
            hour=settings.TRENDING_RETENTION_HOUR,
        ),
    },
    # 每日推荐生成（M3-05）：08:30 生成，09:00 推送准备使用最新结果
    "generate-recommendations-daily": {
        "task": "app.tasks.jobs.generate_recommendations",
        "schedule": crontab(minute=30, hour=8),
    },
    "daily-push-at-9am": {
        "task": "app.tasks.jobs.daily_push",
        "schedule": crontab(minute=0, hour=9),
    },
    # Vectorize 索引：每日增量同步 + 对账（M3-03）
    "vector-index-sync-daily": {
        "task": "app.tasks.jobs.sync_vector_index",
        "schedule": crontab(minute=37, hour=4),
        "kwargs": {"mode": "incremental", "scope": "all"},
    },
    "vector-index-reconcile-daily": {
        "task": "app.tasks.jobs.reconcile_vector_index",
        "schedule": crontab(minute=17, hour=5),
        "kwargs": {"scope": "all", "repair": False},
    },
    # 备份与恢复（M5-04）：每日 SQLite 快照 + 每周日恢复演练
    "backup-sqlite-daily": {
        "task": "app.tasks.jobs.backup_sqlite",
        "schedule": crontab(minute=settings.BACKUP_MINUTE, hour=settings.BACKUP_HOUR),
    },
    "backup-drill-weekly": {
        "task": "app.tasks.jobs.backup_drill",
        "schedule": crontab(
            minute=settings.BACKUP_DRILL_MINUTE,
            hour=settings.BACKUP_DRILL_HOUR,
            day_of_week="sunday",
        ),
    },
}

# 兼容 `celery -A app.tasks.celery_app`（默认按属性名 app/celery 查找）
app = celery_app
