"""Celery 任务包（薄封装：调用 services + 落库）。"""

from app.tasks.celery_app import celery_app

__all__ = ["celery_app"]
