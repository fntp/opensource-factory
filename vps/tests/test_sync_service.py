"""Starred 同步服务测试：upsert / 进度 / 部分失败（内存 SQLite，无网络）。"""
from __future__ import annotations

import asyncio

import httpx
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db import Base
from app.models import MyRepository
from app.services.github_service import GITHUB_API, GitHubClient, GitHubClientConfig
from app.services.github_service import SyncProgress
from app.services.sync import sync_starred_to_db, upsert_repositories

STARRED_URL = f"{GITHUB_API}/user/starred"


def _make_session() -> Session:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()


def _repo(name: str, stars: int = 1, description: str = "") -> dict:
    return {
        "id": name,
        "full_name": name,
        "platform": "github",
        "name": name.split("/")[-1],
        "description": description or f"{name} 描述",
        "html_url": f"https://github.com/{name}",
        "stars": stars,
        "language": "Python",
    }


def _mock_client(handler, **config_kwargs) -> GitHubClient:
    config_kwargs.setdefault("min_interval", 0)
    config = GitHubClientConfig(**config_kwargs)

    async def _noop_sleep(_: float) -> None:
        return None

    return GitHubClient(
        "token",
        config=config,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        sleep=_noop_sleep,
    )


def test_upsert_created_then_unchanged_then_updated() -> None:
    db = _make_session()
    try:
        items = [_repo("a/one", stars=10), _repo("b/two", stars=20)]
        first = upsert_repositories(db, items)
        assert first == {"total": 2, "created": 2, "updated": 0, "unchanged": 0}

        second = upsert_repositories(db, items)
        assert second == {"total": 2, "created": 0, "updated": 0, "unchanged": 2}

        changed = [_repo("a/one", stars=99), _repo("b/two", stars=20)]
        third = upsert_repositories(db, changed)
        assert third == {"total": 2, "created": 0, "updated": 1, "unchanged": 1}
        assert db.get(MyRepository, "a/one").stars == 99
    finally:
        db.close()


def test_upsert_deduplicates_and_ignores_empty_ids() -> None:
    db = _make_session()
    try:
        items = [_repo("a/one", stars=1), _repo("a/one", stars=2), {"id": "", "name": "x"}]
        result = upsert_repositories(db, items)
        assert result["total"] == 1
        assert db.get(MyRepository, "a/one").stars == 2
    finally:
        db.close()


def test_sync_starred_to_db_full_pagination_and_progress() -> None:
    pages = {
        1: [_repo("a/one"), _repo("b/two")],
        2: [_repo("c/three")],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params.get("page", "1"))
        headers = {}
        if page == 1:
            headers["link"] = (
                f'<{STARRED_URL}?per_page=2&page=2>; rel="next", '
                f'<{STARRED_URL}?per_page=2&page=2>; rel="last"'
            )
        return httpx.Response(200, json=pages[page], headers=headers)

    progress: list[dict] = []
    db = _make_session()
    try:
        result = asyncio.run(
            sync_starred_to_db(
                db,
                "token",
                per_page=2,
                on_progress=lambda p: progress.append(p.to_dict()),
                client=_mock_client(handler),
            )
        )
        assert result["status"] == "ok"
        assert result["total"] == 3
        assert result["created"] == 3
        assert result["pages"] == 2
        assert [p["phase"] for p in progress][:2] == ["starred", "starred"]
        assert progress[-1]["done"] is True
        assert progress[-1]["percent"] == 100

        again = asyncio.run(
            sync_starred_to_db(db, "token", per_page=2, client=_mock_client(handler))
        )
        assert again["unchanged"] == 3
        assert again["created"] == 0
    finally:
        db.close()


def test_sync_starred_keeps_partial_items_on_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params.get("page", "1"))
        if page == 1:
            return httpx.Response(
                200,
                json=[_repo("a/one"), _repo("b/two")],
                headers={"link": f'<{STARRED_URL}?per_page=2&page=2>; rel="next"'},
            )
        return httpx.Response(500, json={"message": "boom"})

    db = _make_session()
    try:
        result = asyncio.run(
            sync_starred_to_db(
                db,
                "token",
                per_page=2,
                client=_mock_client(handler, max_retries=1, backoff_base=0.01),
            )
        )
        assert result["status"] == "error"
        assert result["partial"] is True
        assert result["total"] == 2
        assert result["created"] == 2
        assert db.get(MyRepository, "a/one") is not None
        assert db.get(MyRepository, "b/two") is not None
    finally:
        db.close()


def test_sync_starred_task_reports_progress_and_upserts(monkeypatch) -> None:
    """Celery 任务薄封装：进度回调 + 落库 + 结构化返回。"""
    import app.tasks.jobs as jobs
    from app.db import init_db

    init_db()

    async def fake_list_starred(token: str, **kwargs):
        on_progress = kwargs.get("on_progress")
        if on_progress:
            on_progress(SyncProgress(phase="starred", page=1, pages_total=2, fetched=2))
            on_progress(
                SyncProgress(
                    phase="starred", page=2, pages_total=2, fetched=3, total=3, done=True
                )
            )
        return [
            _repo("task/one"),
            _repo("task/two"),
            _repo("task/three"),
        ]

    monkeypatch.setattr("app.services.sync.list_starred_repos", fake_list_starred)

    class _Settings:
        GITHUB_TOKEN = "test-token"

    monkeypatch.setattr(jobs, "get_settings", lambda: _Settings())
    result = jobs.sync_starred_repositories.apply().get()
    assert result["status"] == "ok"
    assert result["total"] == 3
    assert result["created"] == 3
    assert result["pages"] == 2
