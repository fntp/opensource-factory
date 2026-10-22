"""Celery 应用与定时计划。

- broker / backend：`REDIS_URL`（默认 `redis://localhost:6379/0`）；
- `CELERY_TASK_ALWAYS_EAGER=1` 时任务同步执行（本地调试 / 测试）；
- beat 计划：每日增量同步 GitHub 资产、每周全量对账、每 6 小时抓取热榜、每日 09:00 推送准备。
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
celery_app.conf.beat_schedule = {
    # 增量同步：每天凌晨按 pushed_at / star 变化拉取（REQ-202610-0899）
    "sync-repositories-incremental-daily": {
        "task": "app.tasks.jobs.sync_repositories",
        "schedule": crontab(minute=17, hour=3),
        "kwargs": {"include_starred": True, "mode": "incremental"},
    },
    # 全量对账：每周日扫描全部页，补偿 Star 变化 / 取消 Star 等增量盲区
    "sync-repositories-full-weekly": {
        "task": "app.tasks.jobs.sync_repositories",
        "schedule": crontab(minute=7, hour=4, day_of_week="sun"),
        "kwargs": {"include_starred": True, "mode": "full"},
    },
    "crawl-trending-every-6h": {
        "task": "app.tasks.jobs.crawl_trending",
        "schedule": crontab(minute=15, hour="*/6"),
        "kwargs": {"platform": "github"},
    },
    "daily-push-at-9am": {
        "task": "app.tasks.jobs.daily_push",
        "schedule": crontab(minute=0, hour=9),
    },
}

# 兼容 `celery -A app.tasks.celery_app`（默认按属性名 app/celery 查找）
app = celery_app
