"""抓取容错与结构变更判定测试（无网络）。"""
from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import models  # noqa: F401 - 注册所有模型
from app.db import Base
from app.services.crawl_guard import (
    ALERT_KIND_ALL_FAILED,
    ALERT_KIND_COUNT_DROP,
    ALERT_KIND_FETCH_FAILED,
    ALERT_KIND_STRUCTURE_CHANGE,
    CrawlRetryPolicy,
    evaluate_page_health,
    fetch_html_with_retry,
    get_page_baseline,
    process_crawl_health,
    record_alert,
)
from app.services.trending_crawler import (
    crawl_github_trending_page,
    crawl_github_trending_pages,
    parse_trending_html_with_report,
)


class FakeResponse:
    def __init__(self, status_code: int, text: str = "", headers: dict[str, str] | None = None):
        self.status_code = status_code
        self.text = text
        self.headers = headers or {}


class FakeClient:
    """按顺序返回响应或抛异常的 httpx 替身。"""

    def __init__(self, responses: list[Any]):
        self.responses = list(responses)
        self.calls = 0

    async def get(self, url: str, headers: dict[str, str] | None = None) -> Any:
        self.calls += 1
        index = min(self.calls - 1, len(self.responses) - 1)
        item = self.responses[index]
        if isinstance(item, Exception):
            raise item
        return item


HTML_ONE_REPO = """
<article class="Box-row">
  <h2><a href="/openai/whisper">openai / whisper</a></h2>
  <p class="col-9">Speech recognition</p>
  <span itemprop="programmingLanguage">Python</span>
  <a href="/openai/whisper/stargazers">65,432</a>
  <span class="d-inline-block float-sm-right">1,234 stars today</span>
</article>
"""


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


def test_retry_on_connect_error_then_success() -> None:
    client = FakeClient([httpx.ConnectError("boom"), FakeResponse(200, "ok")])
    sleeps: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    result = _run(
        fetch_html_with_retry(
            client,
            "https://github.com/trending",
            policy=CrawlRetryPolicy(max_attempts=3, base_delay=1.0, max_delay=8.0),
            sleep=fake_sleep,
        )
    )
    assert result.ok is True
    assert result.attempts == 2
    assert client.calls == 2
    assert sleeps == [1.0]


def test_retry_honours_retry_after_on_429() -> None:
    client = FakeClient(
        [FakeResponse(429, headers={"Retry-After": "2"}), FakeResponse(200, "ok")]
    )
    sleeps: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    result = _run(
        fetch_html_with_retry(
            client,
            "https://github.com/trending",
            policy=CrawlRetryPolicy(max_attempts=2, base_delay=1.0, max_delay=8.0),
            sleep=fake_sleep,
        )
    )
    assert result.ok is True
    assert sleeps == [2.0]


def test_retry_exhausted_returns_error_without_raising() -> None:
    client = FakeClient([FakeResponse(503), FakeResponse(503), FakeResponse(503)])
    sleeps: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    result = _run(
        fetch_html_with_retry(
            client,
            "https://github.com/trending",
            policy=CrawlRetryPolicy(max_attempts=3, base_delay=1.0, max_delay=8.0),
            sleep=fake_sleep,
        )
    )
    assert result.ok is False
    assert result.attempts == 3
    assert result.status_code == 503
    assert sleeps == [1.0, 2.0]


def test_4xx_is_not_retried() -> None:
    client = FakeClient([FakeResponse(404)])
    result = _run(
        fetch_html_with_retry(
            client,
            "https://github.com/trending",
            policy=CrawlRetryPolicy(max_attempts=3, base_delay=0.0, max_delay=0.0),
        )
    )
    assert result.ok is False
    assert result.attempts == 1
    assert client.calls == 1


def test_parse_report_counts_rows_and_dropped() -> None:
    html = HTML_ONE_REPO + '<article class="Box-row"><h2><a href="/about">About</a></h2></article>'
    items, report = parse_trending_html_with_report(html)
    assert len(items) == 1
    assert report.rows == 2
    assert report.parsed == 1
    assert report.dropped == 1

    _items, empty_report = parse_trending_html_with_report("<html>nothing</html>")
    assert empty_report.rows == 0
    assert empty_report.parsed == 0


def test_evaluate_page_health_rules() -> None:
    failed = evaluate_page_health(page="python", ok=False, error="timeout")
    assert failed is not None and failed.kind == ALERT_KIND_FETCH_FAILED

    empty = evaluate_page_health(page="python", ok=True, rows=0, parsed=0)
    assert empty is not None and empty.kind == ALERT_KIND_STRUCTURE_CHANGE

    mismatch = evaluate_page_health(page="python", ok=True, rows=5, parsed=0)
    assert mismatch is not None and mismatch.kind == ALERT_KIND_STRUCTURE_CHANGE

    dropped = evaluate_page_health(page="python", ok=True, rows=25, parsed=2, baseline=20)
    assert dropped is not None and dropped.kind == ALERT_KIND_COUNT_DROP

    assert evaluate_page_health(page="python", ok=True, rows=25, parsed=20, baseline=20) is None
    # 基线不足 5 条时不判定骤降，避免小页面误报
    assert evaluate_page_health(page="python", ok=True, rows=3, parsed=1, baseline=3) is None


def test_record_alert_deduplicates_within_cooldown(db) -> None:
    first, created = record_alert(
        db,
        platform="github",
        page="python",
        kind=ALERT_KIND_STRUCTURE_CHANGE,
        severity="error",
        message="疑似改版",
        details={"rows": 0},
    )
    db.commit()
    assert created is True

    second, created_again = record_alert(
        db,
        platform="github",
        page="python",
        kind=ALERT_KIND_STRUCTURE_CHANGE,
        severity="error",
        message="疑似改版（再次）",
        details={"rows": 0},
        cooldown_minutes=360,
    )
    db.commit()
    assert created_again is False
    assert second.id == first.id
    assert second.occurrences == 2


def test_process_crawl_health_updates_baseline_and_detects_drop(db) -> None:
    healthy = [{"language": "python", "ok": True, "count": 10, "rows": 10, "parsed": 10}]
    result = process_crawl_health(db, platform="github", pages=healthy, total_items=10)
    assert result["created"] == 0
    assert get_page_baseline(db, "github", "python") == 10

    dropped = [{"language": "python", "ok": True, "count": 2, "rows": 10, "parsed": 2}]
    result = process_crawl_health(db, platform="github", pages=dropped, total_items=2)
    assert result["created"] == 1
    assert result["alerts"][0]["kind"] == ALERT_KIND_COUNT_DROP
    # 本次抓取成功，基线跟随最新成功条数
    assert get_page_baseline(db, "github", "python") == 2

    failed = [{"language": "python", "ok": False, "count": 0, "error": "timeout"}]
    process_crawl_health(db, platform="github", pages=failed, total_items=0)
    # 抓取失败时保留上次成功基线
    assert get_page_baseline(db, "github", "python") == 2


def test_notify_alert_webhook_is_best_effort(monkeypatch) -> None:
    from app.services import crawl_guard

    alert = models.CrawlAlert(
        id="a1",
        platform="github",
        page="python",
        kind=ALERT_KIND_STRUCTURE_CHANGE,
        severity="error",
        message="疑似改版",
        dedupe_key="github:python:structure_change",
        status="open",
        occurrences=1,
    )

    class FakePostResponse:
        status_code = 204

    monkeypatch.setattr(crawl_guard.httpx, "post", lambda *a, **k: FakePostResponse())
    assert crawl_guard.notify_alert_webhook(alert, "https://example.test/hook") is True

    def boom(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("network down")

    monkeypatch.setattr(crawl_guard.httpx, "post", boom)
    assert crawl_guard.notify_alert_webhook(alert, "https://example.test/hook") is False
    # 未配置地址时直接跳过
    assert crawl_guard.notify_alert_webhook(alert, "") is False


def test_process_crawl_health_all_failed_alert(db) -> None:
    pages = [
        {"language": "all", "ok": False, "count": 0, "error": "timeout"},
        {"language": "python", "ok": False, "count": 0, "error": "HTTP 503"},
    ]
    result = process_crawl_health(db, platform="github", pages=pages, total_items=0)
    kinds = {item["kind"] for item in result["alerts"]}
    assert ALERT_KIND_FETCH_FAILED in kinds
    assert ALERT_KIND_ALL_FAILED in kinds


def test_crawl_page_uses_retry_and_reports_diagnostics() -> None:
    client = FakeClient([FakeResponse(500), FakeResponse(200, HTML_ONE_REPO)])
    result = _run(
        crawl_github_trending_page(
            "python",
            client=client,
            policy=CrawlRetryPolicy(max_attempts=2, base_delay=0.0, max_delay=0.0),
        )
    )
    assert client.calls == 2
    assert result["page"]["ok"] is True
    assert result["page"]["attempts"] == 2
    assert result["page"]["rows"] == 1
    assert result["page"]["parsed"] == 1
    assert len(result["items"]) == 1


def test_crawl_pages_continues_after_one_page_failure() -> None:
    client = FakeClient(
        [
            FakeResponse(200, HTML_ONE_REPO),
            FakeResponse(503),
            FakeResponse(503),
            FakeResponse(200, HTML_ONE_REPO.replace("openai/whisper", "golang/go")),
        ]
    )

    async def fake_sleep(_delay: float) -> None:
        return None

    result = _run(
        crawl_github_trending_pages(
            ["python", "go"],
            client=client,
            policy=CrawlRetryPolicy(max_attempts=2, base_delay=0.0, max_delay=0.0),
            delay_seconds=0,
            sleep=fake_sleep,
        )
    )
    pages = {page["language"]: page for page in result["pages"]}
    assert pages["all"]["ok"] is True
    assert pages["python"]["ok"] is False
    assert pages["go"]["ok"] is True
    assert len(result["items"]) == 2
