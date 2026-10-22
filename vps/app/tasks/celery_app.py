"""Celery 应用与定时计划。

- broker / backend：`REDIS_URL`（默认 `redis://localhost:6379/0`）；
- `CELERY_TASK_ALWAYS_EAGER=1` 时任务同步执行（本地调试 / 测试）；
- beat 计划：每日抓取热榜（全局页 + 多语言页）、每日 08:30 生成推荐、08:45 评估推荐、
  每 10 分钟按用户偏好检查推送窗口（M4-06）、09:05 Bark 投递与 Telegram 摘要、
  09:10 Email 每日精选、按 `PUSH_RETRY_INTERVAL_MINUTES` 重试静默期推迟的推送（M4-07）、
  每日 SQLite 快照（默认 03:50）与每周日恢复演练（默认 04:20），以及每日向量索引同步与对账。
"""
from __future__ import annotations

from datetime import timedelta

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
    # 推送偏好（M4-06）：每 10 分钟检查一次，按用户时区与推送窗口筛选；
    # 窗口默认 10 分钟，与调度间隔一致，避免漏推或重复推送。
    "daily-push-preferences": {
        "task": "app.tasks.jobs.daily_push",
        "schedule": crontab(minute="*/10"),
        "kwargs": {"respect_schedule": True},
    },
    # 静默结束后重试（M4-07）：非静默且存在 qualified 时才会真正执行
    "retry-deferred-push": {
        "task": "app.tasks.jobs.retry_deferred_push",
        "schedule": timedelta(
            minutes=max(1, int(settings.PUSH_RETRY_INTERVAL_MINUTES or 30))
        ),
    },
    # Bark 通道（M4-03）：09:05 投递 09:00 推送准备产生的 pushed 推荐
    "send-bark-notifications-daily": {
        "task": "app.tasks.jobs.send_bark_notifications",
        "schedule": crontab(minute=5, hour=9),
    },
    # Telegram 每日摘要（M4-04）：09:05 在推送准备之后下发；未启用时任务直接跳过
    "send-telegram-digest-daily": {
        "task": "app.tasks.jobs.send_telegram_digest",
        "schedule": crontab(minute=5, hour=9),
    },
    # Email 每日精选（M4-05）：09:10 在推送准备后取 pushed 推荐发送摘要；
    # 未启用 / 未配置 / 无数据时任务自动跳过
    "send-email-digest-daily": {
        "task": "app.tasks.jobs.send_email_digest",
        "schedule": crontab(minute=10, hour=9),
    },
    # 项目健康度元数据刷新（M6-05）：每日 06:12，避开抓取 / 推荐高峰
    "refresh-repo-health-daily": {
        "task": "app.tasks.jobs.refresh_repo_health",
        "schedule": crontab(
            minute=settings.REPO_HEALTH_MINUTE,
            hour=settings.REPO_HEALTH_HOUR,
        ),
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
    # 监控与告警（M5-03）：每 MONITOR_INTERVAL_MINUTES 分钟检查一次
    "monitor-system-health": {
        "task": "app.tasks.jobs.monitor_system_health",
        "schedule": float(settings.MONITOR_INTERVAL_MINUTES * 60),
    },
    # 日志 / 检查历史清理：每日 04:23
    "cleanup-monitoring-logs-daily": {
        "task": "app.tasks.jobs.cleanup_monitoring_logs",
        "schedule": crontab(minute=23, hour=4),
    },
    # README 全文索引补录（M6-01）：默认 04:47，为历史 / 新增仓库补齐 FTS 镜像
    "readme-fts-sync-daily": {
        "task": "app.tasks.jobs.sync_readmes",
        "schedule": crontab(
            minute=settings.FTS_SYNC_MINUTE,
            hour=settings.FTS_SYNC_HOUR,
        ),
        "kwargs": {"source": "all"},
    },
}

# 兼容 `celery -A app.tasks.celery_app`（默认按属性名 app/celery 查找）
app = celery_app
