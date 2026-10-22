"""增量同步策略单测（REQ-202610-0899）。

覆盖：字段标准化、变化判定、水位线、首次全量、增量拉取、Star 变化、
全量模式忽略水位线、失败不推进水位线。全部使用假拉取函数，不访问网络。
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import delete

from app.db import SessionLocal, init_db
from app.models import MyRepository, SyncState
from app.services.github_service import normalize_repo
from app.services.incremental import (
    SYNC_SOURCE_OWN,
    SYNC_SOURCE_STARRED,
    build_change_plan,
    max_updated_at,
    run_incremental_sync,
    should_full_sync,
)

NOW = datetime(2026, 10, 22, 4, 0, tzinfo=timezone.utc)


def _repo(
    full_name: str = "acme/demo",
    *,
    stars: int = 10,
    pushed_at: str = "2026-10-20T10:00:00Z",
    updated_at: str = "2026-10-21T10:00:00Z",
    description: str = "demo repo",
) -> dict:
    """构造标准化后的仓库条目。"""
    owner, name = full_name.split("/", 1)
    return {
        "id": full_name,
        "platform": "github",
        "name": name,
        "description": description,
        "html_url": f"https://github.com/{full_name}",
        "stars": stars,
        "language": "Python",
        "forks": 1,
        "owner": owner,
        "pushed_at": pushed_at,
        "updated_at": updated_at,
    }


def _row(item: dict) -> MyRepository:
    """按条目构造本地行（用于纯函数测试）。"""
    return MyRepository(
        id=item["id"],
        platform=item["platform"],
        name=item["name"],
        description=item["description"],
        html_url=item["html_url"],
        stars=item["stars"],
        language=item["language"],
        owner=item["owner"],
        forks=item["forks"],
        pushed_at=item["pushed_at"],
        updated_at=item["updated_at"],
    )


@pytest.fixture()
def db():
    """独立数据库会话：每次测试清空仓库与同步状态表。"""
    init_db()
    session = SessionLocal()
    session.execute(delete(MyRepository))
    session.execute(delete(SyncState))
    session.commit()
    try:
        yield session
    finally:
        session.close()


def test_normalize_repo_extracts_incremental_fields() -> None:
    item = normalize_repo(
        {
            "full_name": "acme/demo",
            "name": "demo",
            "description": "desc",
            "html_url": "https://github.com/acme/demo",
            "stargazers_count": 42,
            "forks_count": 3,
            "language": "Python",
            "owner": {"login": "acme"},
            "pushed_at": "2026-10-20T10:00:00Z",
            "updated_at": "2026-10-21T11:00:00Z",
        }
    )
    assert item["owner"] == "acme"
    assert item["forks"] == 3
    assert item["pushed_at"] == "2026-10-20T10:00:00Z"
    assert item["updated_at"] == "2026-10-21T11:00:00Z"


def test_build_change_plan_classifies_new_changed_unchanged() -> None:
    existing = {
        "acme/one": _row(_repo("acme/one")),
        "acme/keep": _row(_repo("acme/keep")),
    }
    changed = _repo("acme/one", stars=11)
    unchanged = _repo("acme/keep")
    new_item = _repo("acme/two")
    plan = build_change_plan(existing, [changed, unchanged, new_item])
    assert plan.total == 3
    assert len(plan.new_items) == 1
    assert plan.new_items[0]["id"] == "acme/two"
    assert len(plan.changed) == 1
    assert plan.changed[0][0].id == "acme/one"
    assert plan.changed[0][1]["stars"] == 11
    assert plan.unchanged == 1


def test_build_change_plan_marks_identical_rows_unchanged() -> None:
    item = _repo()
    plan = build_change_plan({"acme/demo": _row(item)}, [item, dict(item)])
    assert plan.total == 1
    assert plan.unchanged == 1
    assert not plan.new_items
    assert not plan.changed


def test_should_full_sync_by_interval() -> None:
    assert should_full_sync(None, NOW) is True

    recent = SyncState(source="github:own", last_full_synced_at="2026-10-21T04:00:00Z")
    assert should_full_sync(recent, NOW) is False

    old = SyncState(
        source="github:own",
        last_full_synced_at=(NOW - timedelta(days=8)).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    assert should_full_sync(old, NOW) is True

    malformed = SyncState(source="github:own", last_full_synced_at="not-a-time")
    assert should_full_sync(malformed, NOW) is True


def test_max_updated_at_picks_latest_valid_value() -> None:
    items = [
        _repo("a/one", updated_at="2026-10-20T00:00:00Z"),
        _repo("a/two", updated_at="2026-10-22T01:00:00Z"),
        {"id": "a/bad", "updated_at": "oops"},
    ]
    assert max_updated_at(items) == "2026-10-22T01:00:00Z"
    assert max_updated_at([]) is None


def test_first_run_is_full_then_incremental_uses_checkpoint(db) -> None:
    items = [
        _repo("acme/one", updated_at="2026-10-21T10:00:00Z"),
        _repo("acme/two", updated_at="2026-10-22T01:00:00Z"),
    ]
    calls: list[str | None] = []

    async def fake_own(token: str, *, since=None, **kwargs):
        calls.append(since)
        if since is None:
            return items
        return [_repo("acme/one", stars=99, updated_at="2026-10-22T02:00:00Z")]

    async def fake_starred(token: str, **kwargs):
        return []

    first = asyncio.run(
        run_incremental_sync(
            db,
            "token",
            include_starred=True,
            now=NOW,
            fetch_own=fake_own,
            fetch_starred=fake_starred,
        )
    )
    assert first["status"] == "ok"
    assert first["sources"][0]["mode"] == "full"
    assert first["created"] == 2
    state = db.get(SyncState, SYNC_SOURCE_OWN)
    assert state is not None
    assert state.last_synced_at == "2026-10-22T01:00:00Z"
    assert state.last_full_synced_at == "2026-10-22T04:00:00Z"

    second = asyncio.run(
        run_incremental_sync(
            db,
            "token",
            include_starred=True,
            now=NOW,
            fetch_own=fake_own,
            fetch_starred=fake_starred,
        )
    )
    # since 带 60s 重叠窗口，避免同一秒内更新的仓库被漏掉
    assert calls == [None, "2026-10-22T00:59:00Z"]
    assert second["sources"][0]["mode"] == "incremental"
    assert second["updated"] == 1
    assert second["created"] == 0
    db.refresh(state)
    assert state.last_synced_at == "2026-10-22T02:00:00Z"


def test_star_change_updates_only_changed_row(db) -> None:
    item = _repo("acme/starred", stars=10)
    db.add(_row(item))
    db.add(
        SyncState(
            source=SYNC_SOURCE_STARRED,
            last_synced_at="2026-10-21T00:00:00Z",
            last_full_synced_at="2026-10-22T00:00:00Z",
        )
    )
    db.commit()

    async def fake_own(token: str, **kwargs):
        return []

    async def fake_starred(token: str, **kwargs):
        return [_repo("acme/starred", stars=15)]

    result = asyncio.run(
        run_incremental_sync(
            db,
            "token",
            include_starred=True,
            now=NOW,
            fetch_own=fake_own,
            fetch_starred=fake_starred,
        )
    )
    assert result["updated"] == 1
    assert result["unchanged"] == 0
    row = db.get(MyRepository, "acme/starred")
    assert row is not None and row.stars == 15

    # 再次同步相同数据：不写库，计为 unchanged
    again = asyncio.run(
        run_incremental_sync(
            db,
            "token",
            include_starred=True,
            now=NOW,
            fetch_own=fake_own,
            fetch_starred=fake_starred,
        )
    )
    assert again["updated"] == 0
    assert again["unchanged"] == 1


def test_full_mode_ignores_checkpoint(db) -> None:
    db.add(
        SyncState(
            source=SYNC_SOURCE_OWN,
            last_synced_at="2026-10-21T00:00:00Z",
            last_full_synced_at="2026-10-22T00:00:00Z",
        )
    )
    db.commit()
    seen: list[str | None] = []

    async def fake_own(token: str, *, since=None, **kwargs):
        seen.append(since)
        return [_repo()]

    async def fake_starred(token: str, **kwargs):
        return []

    result = asyncio.run(
        run_incremental_sync(
            db,
            "token",
            include_starred=True,
            mode="full",
            now=NOW,
            fetch_own=fake_own,
            fetch_starred=fake_starred,
        )
    )
    assert seen == [None]
    assert result["sources"][0]["mode"] == "full"
    assert result["created"] == 1
    state = db.get(SyncState, SYNC_SOURCE_OWN)
    assert state is not None and state.last_full_synced_at == "2026-10-22T04:00:00Z"


def test_failed_source_keeps_old_checkpoint(db) -> None:
    db.add(
        SyncState(
            source=SYNC_SOURCE_OWN,
            last_synced_at="2026-10-20T00:00:00Z",
            last_full_synced_at="2026-10-22T00:00:00Z",
        )
    )
    db.commit()

    async def fake_own(token: str, **kwargs):
        raise RuntimeError("github unavailable")

    async def fake_starred(token: str, **kwargs):
        return []

    result = asyncio.run(
        run_incremental_sync(
            db,
            "token",
            include_starred=True,
            now=NOW,
            fetch_own=fake_own,
            fetch_starred=fake_starred,
        )
    )
    assert result["status"] == "partial"
    state = db.get(SyncState, SYNC_SOURCE_OWN)
    assert state is not None
    assert state.last_synced_at == "2026-10-20T00:00:00Z"
    assert state.last_status == "error"
    assert "github unavailable" in (state.last_result or "")
