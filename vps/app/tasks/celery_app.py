"""Celery 应用与定时计划。

- broker / backend：`REDIS_URL`（默认 `redis://localhost:6379/0`）；
- `CELERY_TASK_ALWAYS_EAGER=1` 时任务同步执行（本地调试 / 测试）；
- beat 计划：每 6 小时抓取热榜、每日 08:30 生成推荐、08:45 评估推荐、
  09:00 推送准备、09:10 Email 每日精选推送（M4-05）。
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
    "crawl-trending-every-6h": {
        "task": "app.tasks.jobs.crawl_trending",
        "schedule": crontab(minute=15, hour="*/6"),
        "kwargs": {"platform": "github"},
    },
    # 每日推荐生成（M3-05）：08:30 生成，08:45 评估，09:00 推送准备使用最新结果
    "generate-recommendations-daily": {
        "task": "app.tasks.jobs.generate_recommendations",
        "schedule": crontab(minute=30, hour=8),
    },
    # 每日推荐评估（M4-01）：质量分 + 匹配度阈值，产出 qualified / filtered
    "evaluate-recommendations-daily": {
        "task": "app.tasks.jobs.evaluate_recommendations",
        "schedule": crontab(minute=45, hour=8),
    },
    "daily-push-at-9am": {
        "task": "app.tasks.jobs.daily_push",
        "schedule": crontab(minute=0, hour=9),
    },
    # Email 每日精选（M4-05）：09:10 在推送准备后取 pushed 推荐发送摘要；
    # 未启用 / 未配置 / 无数据时任务自动跳过
    "send-email-digest-daily": {
        "task": "app.tasks.jobs.send_email_digest",
        "schedule": crontab(minute=10, hour=9),
    },
    # Vectorize 索引增量同步：每 30 分钟一次（M3-03）；未配置 edge 时任务自动跳过
    "sync-vector-index-every-30m": {
        "task": "app.tasks.jobs.sync_vector_index",
        "schedule": crontab(minute="7,37"),
        "kwargs": {"kind": "sync", "scope": "all"},
    },
}

# 兼容 `celery -A app.tasks.celery_app`（默认按属性名 app/celery 查找）
app = celery_app
