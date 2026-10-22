"""GitHub 客户端测试：分页 / 限流 / 重试 / 进度（httpx.MockTransport，无网络）。"""
from __future__ import annotations

import asyncio
import time

import httpx
import pytest

from app.services.github_service import (
    GITHUB_API,
    GitHubAuthError,
    GitHubClient,
    GitHubClientConfig,
    GitHubRateLimitError,
    SyncProgress,
    list_starred_repos,
    parse_link_header,
)

STARRED_URL = f"{GITHUB_API}/user/starred"


class FakeClock:
    """可注入的时钟：sleep 推进时间并记录等待时长。"""

    def __init__(self, now: float = 1000.0) -> None:
        self.now = now
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def _repo(name: str, stars: int = 1) -> dict:
    return {
        "full_name": name,
        "name": name.split("/")[-1],
        "description": f"{name} 描述",
        "html_url": f"https://github.com/{name}",
        "stargazers_count": stars,
        "language": "Python",
    }


def _client(handler, *, clock: FakeClock | None = None, **config_kwargs) -> GitHubClient:
    config_kwargs.setdefault("min_interval", 0)
    config = GitHubClientConfig(**config_kwargs)
    clock = clock or FakeClock()
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return GitHubClient("test-token", config=config, http_client=http, sleep=clock.sleep, time_func=clock)


def test_parse_link_header() -> None:
    header = (
        f'<{STARRED_URL}?per_page=2&page=2>; rel="next", '
        f'<{STARRED_URL}?per_page=2&page=5>; rel="last"'
    )
    links = parse_link_header(header)
    assert links["next"].endswith("page=2")
    assert links["last"].endswith("page=5")


def test_paginate_follows_link_headers_and_reports_progress() -> None:
    pages = {
        1: [_repo("a/one"), _repo("b/two")],
        2: [_repo("c/three"), _repo("d/four")],
        3: [_repo("e/five")],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params.get("page", "1"))
        headers = {}
        if page < 3:
            headers["link"] = (
                f'<{STARRED_URL}?per_page=2&page={page + 1}>; rel="next", '
                f'<{STARRED_URL}?per_page=2&page=3>; rel="last"'
            )
        return httpx.Response(200, json=pages[page], headers=headers)

    async def scenario() -> tuple[list[dict], int, list[SyncProgress]]:
        progress: list[SyncProgress] = []
        async with _client(handler) as client:
            items, pages_total = await client.paginate(
                STARRED_URL, per_page=2, on_progress=progress.append
            )
        return items, pages_total, progress

    items, pages_total, progress = asyncio.run(scenario())
    assert [item["full_name"] for item in items] == ["a/one", "b/two", "c/three", "d/four", "e/five"]
    assert pages_total == 3
    assert [p.page for p in progress] == [1, 2, 3, 3]
    assert progress[0].pages_total == 3
    assert progress[0].percent == 33
    assert progress[-1].done is True
    assert progress[-1].percent == 100
    assert progress[-1].total == 5


def test_paginate_respects_max_pages() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params.get("page", "1"))
        return httpx.Response(
            200,
            json=[_repo(f"a/repo{page}")],
            headers={"link": f'<{STARRED_URL}?per_page=1&page={page + 1}>; rel="next"'},
        )

    async def scenario() -> tuple[list[dict], int]:
        async with _client(handler) as client:
            return await client.paginate(STARRED_URL, per_page=1, max_pages=2)

    items, pages = asyncio.run(scenario())
    assert len(items) == 2
    assert pages == 2


def test_request_retries_on_5xx_with_backoff() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(502, json={"message": "bad gateway"})
        return httpx.Response(200, json=[_repo("a/ok")])

    clock = FakeClock()

    async def scenario() -> list[dict]:
        async with _client(handler, clock=clock, max_retries=2, backoff_base=0.5) as client:
            items, _ = await client.paginate(STARRED_URL, per_page=2)
        return items

    items = asyncio.run(scenario())
    assert calls["n"] == 2
    assert len(items) == 1
    assert clock.sleeps and clock.sleeps[0] == 0.5


def test_request_retries_on_429_retry_after() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, headers={"retry-after": "2"}, json={"message": "slow down"})
        return httpx.Response(200, json=[])

    clock = FakeClock()

    async def scenario() -> None:
        async with _client(handler, clock=clock, max_retries=1) as client:
            await client.paginate(STARRED_URL, per_page=2)

    asyncio.run(scenario())
    assert calls["n"] == 2
    assert 2.0 in clock.sleeps


def test_request_waits_for_rate_limit_reset() -> None:
    reset_at = int(time.time()) + 30
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(
                403,
                headers={
                    "x-ratelimit-remaining": "0",
                    "x-ratelimit-reset": str(reset_at),
                },
                json={"message": "API rate limit exceeded"},
            )
        return httpx.Response(200, json=[])

    clock = FakeClock(now=float(reset_at - 30))

    async def scenario() -> None:
        async with _client(handler, clock=clock, max_retries=1) as client:
            await client.paginate(STARRED_URL, per_page=2)

    asyncio.run(scenario())
    assert calls["n"] == 2
    assert any(wait >= 1 for wait in clock.sleeps)


def test_request_does_not_retry_on_401() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(401, json={"message": "Bad credentials"})

    async def scenario() -> None:
        async with _client(handler, max_retries=3) as client:
            with pytest.raises(GitHubAuthError):
                await client.paginate(STARRED_URL, per_page=2)

    asyncio.run(scenario())
    assert calls["n"] == 1


def test_rate_limit_error_after_retries_exhausted() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429,
            headers={"retry-after": "0", "x-ratelimit-remaining": "0"},
            json={"message": "rate limited"},
        )

    async def scenario() -> None:
        async with _client(handler, max_retries=1) as client:
            with pytest.raises(GitHubRateLimitError):
                await client.paginate(STARRED_URL, per_page=2)

    asyncio.run(scenario())


def test_list_starred_repos_handles_wrapped_and_plain_items() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[
                {"starred_at": "2026-10-01T00:00:00Z", "repo": _repo("a/wrapped")},
                _repo("b/plain"),
                _repo("a/wrapped"),  # 重复项应去重
            ],
        )

    async def scenario() -> list[dict]:
        return await list_starred_repos("token", per_page=3, client=_client(handler))

    repos = asyncio.run(scenario())
    assert [repo["id"] for repo in repos] == ["a/wrapped", "b/plain"]
    assert repos[0]["platform"] == "github"
