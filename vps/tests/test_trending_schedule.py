"""Celery beat 定时计划测试：每日抓取 + 多语言页参数。"""
from __future__ import annotations

from app.config import get_settings
from app.tasks.celery_app import celery_app


def test_trending_crawl_runs_daily_with_languages() -> None:
    settings = get_settings()
    schedule = celery_app.conf.beat_schedule

    assert "crawl-trending-daily" in schedule
    assert "crawl-trending-every-6h" not in schedule

    entry = schedule["crawl-trending-daily"]
    assert entry["task"] == "app.tasks.jobs.crawl_trending"
    assert entry["schedule"].hour == {settings.TRENDING_CRAWL_HOUR}
    assert entry["schedule"].minute == {settings.TRENDING_CRAWL_MINUTE}
    assert entry["kwargs"] == {
        "platform": "github",
        "languages": settings.TRENDING_LANGUAGES,
    }
    assert celery_app.conf.timezone == "Asia/Shanghai"


def test_default_languages_cover_common_stacks() -> None:
    languages = {
        part.strip()
        for part in get_settings().TRENDING_LANGUAGES.split(",")
        if part.strip()
    }
    assert {"python", "javascript", "typescript", "go", "rust", "java"} <= languages
