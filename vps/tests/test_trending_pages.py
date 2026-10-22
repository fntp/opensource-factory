"""多语言 Trending 页抓取测试：httpx.MockTransport，不访问网络。"""
from __future__ import annotations

import asyncio

import httpx

from app.services.trending_crawler import (
    build_trending_url,
    crawl_github_trending,
    crawl_github_trending_pages,
    merge_trending_items,
    normalize_languages,
)

GLOBAL_HTML = """
<div class="Box">
  <article class="Box-row">
    <h2><a href="/openai/whisper"><span class="text-normal">openai /</span> whisper</a></h2>
    <p class="col-9">Robust Speech Recognition via Large-Scale Weak Supervision</p>
    <div class="f6">
      <span itemprop="programmingLanguage">Python</span>
      <a href="/openai/whisper/stargazers">65,432</a>
      <span class="d-inline-block float-sm-right">1,234 stars today</span>
    </div>
  </article>
  <article class="Box-row">
    <h2><a href="/golang/go">golang / go</a></h2>
    <p class="col-9">The Go programming language</p>
    <div class="f6">
      <span itemprop="programmingLanguage">Go</span>
      <a href="/golang/go/stargazers">123,456</a>
      <span class="d-inline-block float-sm-right">987 stars today</span>
    </div>
  </article>
</div>
"""

PYTHON_HTML = """
<article class="Box-row">
  <h2><a href="/openai/whisper">openai / whisper</a></h2>
  <div class="f6">
    <span itemprop="programmingLanguage">Python</span>
    <a href="/openai/whisper/stargazers">65,432</a>
    <span class="d-inline-block float-sm-right">1,234 stars today</span>
  </div>
</article>
<article class="Box-row">
  <h2><a href="/django/django">django / django</a></h2>
  <p class="col-9">The Web framework for perfectionists with deadlines.</p>
  <div class="f6">
    <span itemprop="programmingLanguage">Python</span>
    <a href="/django/django/stargazers">80,000</a>
    <span class="d-inline-block float-sm-right">321 stars today</span>
  </div>
</article>
"""


def test_normalize_languages_accepts_csv_and_sequences() -> None:
    assert normalize_languages("python, Rust ,, python") == ["python", "rust"]
    assert normalize_languages(["Go", "go", " C++ "]) == ["go", "c++"]
    assert normalize_languages(None) == []


def test_build_trending_url_encodes_language_and_since() -> None:
    assert build_trending_url() == "https://github.com/trending?since=daily"
    assert build_trending_url("python") == "https://github.com/trending/python?since=daily"
    assert build_trending_url("c++", "weekly") == "https://github.com/trending/c%2B%2B?since=weekly"
    # 非法 since 回退 daily
    assert build_trending_url("go", "yearly").endswith("?since=daily")


def test_merge_trending_items_dedupes_and_fills_fields() -> None:
    merged = merge_trending_items(
        [
            ("all", [{"id": "a/b", "name": "b", "description": "", "stars": 10, "stars_today": 5}]),
            (
                "python",
                [
                    {
                        "id": "a/b",
                        "name": "b",
                        "description": "richer description",
                        "language": "Python",
                        "stars": 12,
                        "stars_today": 3,
                    }
                ],
            ),
        ]
    )
    assert len(merged) == 1
    item = merged[0]
    assert item["description"] == "richer description"
    assert item["language"] == "Python"
    assert item["stars"] == 12
    assert item["stars_today"] == 5
    assert item["trending_pages"] == ["all", "python"]


def test_crawl_multi_pages_dedupes_and_reports_failed_page() -> None:
    seen_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_paths.append(request.url.path)
        if request.url.path == "/trending":
            return httpx.Response(200, text=GLOBAL_HTML)
        if request.url.path == "/trending/python":
            return httpx.Response(200, text=PYTHON_HTML)
        if request.url.path == "/trending/rust":
            return httpx.Response(500, text="boom")
        return httpx.Response(404)

    async def run() -> dict:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            return await crawl_github_trending_pages(
                ["python", "rust"], client=client, delay_seconds=0
            )

    result = asyncio.run(run())
    assert seen_paths == ["/trending", "/trending/python", "/trending/rust"]
    assert len(result["items"]) == 3  # whisper / go / django
    assert len(result["pages"]) == 3
    assert [page["language"] for page in result["pages"]] == ["all", "python", "rust"]
    assert len(result["failedPages"]) == 1
    assert result["failedPages"][0]["language"] == "rust"
    assert result["failedPages"][0]["error"] == "HTTP 500"

    by_id = {item["id"]: item for item in result["items"]}
    whisper = by_id["openai/whisper"]
    assert whisper["description"].startswith("Robust Speech")
    assert whisper["trending_pages"] == ["all", "python"]
    assert by_id["django/django"]["language"] == "Python"


def test_crawl_all_pages_failed_returns_empty_items() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    async def run() -> dict:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            return await crawl_github_trending_pages(
                ["python"], client=client, delay_seconds=0
            )

    result = asyncio.run(run())
    assert result["items"] == []
    assert len(result["failedPages"]) == 2


def test_single_page_crawl_accepts_injected_client() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/trending/python"
        return httpx.Response(200, text=PYTHON_HTML)

    async def run() -> list[dict]:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            return await crawl_github_trending("python", client=client)

    items = asyncio.run(run())
    assert {item["id"] for item in items} == {"openai/whisper", "django/django"}


def test_crawl_pages_can_skip_global_page() -> None:
    seen_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_paths.append(request.url.path)
        return httpx.Response(200, text=PYTHON_HTML)

    async def run() -> dict:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            return await crawl_github_trending_pages(
                ["python"], include_global=False, client=client, delay_seconds=0
            )

    result = asyncio.run(run())
    assert seen_paths == ["/trending/python"]
    assert [page["language"] for page in result["pages"]] == ["python"]
    assert {item["id"] for item in result["items"]} == {"openai/whisper", "django/django"}
