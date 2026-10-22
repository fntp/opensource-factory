"""收藏项目更新提醒（M7-04）测试：版本解析 / 变更判定 / 增量扫描 / API。"""
from __future__ import annotations

import asyncio
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from app.db import SessionLocal, init_db
from app.main import app
from app.models import MyRepository
from app.services.repo_updates import (
    UPDATE_TYPE_MAJOR,
    UPDATE_TYPE_RELEASE,
    classify_update,
    clean_release_body,
    is_major_bump,
    parse_version,
    scan_repositories,
    select_latest_release,
)

NOW = datetime(2026, 10, 22, 6, 37, 0)


@pytest.fixture()
def db():
    init_db()
    session = SessionLocal()
    session.execute(delete(MyRepository).where(MyRepository.id.like("updates-test/%")))
    session.commit()
    yield session
    session.rollback()
    session.execute(delete(MyRepository).where(MyRepository.id.like("updates-test/%")))
    session.commit()
    session.close()


def _repo(db, repo_id: str, **kwargs) -> MyRepository:
    row = MyRepository(
        id=repo_id,
        platform="github",
        name=repo_id.split("/")[-1],
        description="",
        html_url=f"https://github.com/{repo_id}",
        stars=kwargs.pop("stars", 100),
        language="Python",
        **kwargs,
    )
    db.add(row)
    db.commit()
    return row


def _release(tag: str, *, name: str = "", body: str = "", published: str | None = None, **extra):
    return {
        "tag_name": tag,
        "name": name or tag,
        "body": body,
        "html_url": f"https://github.com/updates-test/repo/releases/tag/{tag}",
        "published_at": published,
        "prerelease": extra.pop("prerelease", False),
        "draft": extra.pop("draft", False),
        **extra,
    }


def test_parse_version_and_major_bump() -> None:
    assert parse_version("v1.2.3") == (1, 2, 3)
    assert parse_version("release-2.0") == (2, 0)
    assert parse_version("nightly") is None
    assert parse_version(None) is None

    assert is_major_bump("v1.9.3", "v2.0.0") is True
    assert is_major_bump("v2.0.0", "v2.1.0") is False
    assert is_major_bump("nightly", "v2.0.0") is False


def test_classify_update() -> None:
    assert classify_update("v1.2.0", "v2.0.0") == UPDATE_TYPE_MAJOR
    assert classify_update("v1.2.0", "v1.3.0", "v1.3.0", "普通修复") == UPDATE_TYPE_RELEASE
    assert (
        classify_update("v1.2.0", "v1.3.0", "v1.3.0", "This release contains BREAKING CHANGES")
        == UPDATE_TYPE_MAJOR
    )
    assert classify_update("v1.2.0", "v1.3.0", "v1.3.0", "包含破坏性变更") == UPDATE_TYPE_MAJOR


def test_clean_release_body_collapses_markdown() -> None:
    body = "## 更新\n\n```bash\nnpm i\n```\n\n- 修复 **A**\n- 优化 `B`"
    cleaned = clean_release_body(body)
    assert "```" not in cleaned
    assert "**" not in cleaned
    assert "修复" in cleaned and "优化" in cleaned


def test_select_latest_release_skips_draft_and_prerelease() -> None:
    releases = [
        _release("v1.0.0", published="2026-09-01T00:00:00Z"),
        _release("v2.0.0-beta", published="2026-10-20T00:00:00Z", prerelease=True),
        _release("v1.1.0", published="2026-10-01T00:00:00Z"),
        _release("v9.9.9", published="2026-10-21T00:00:00Z", draft=True),
    ]
    latest = select_latest_release(releases)
    assert latest is not None
    assert latest["tag_name"] == "v1.1.0"

    with_prerelease = select_latest_release(releases, include_prerelease=True)
    assert with_prerelease is not None
    assert with_prerelease["tag_name"] == "v2.0.0-beta"

    assert select_latest_release([]) is None
    assert select_latest_release([_release("v1.0.0", prerelease=True)]) is None


def test_scan_repositories_records_baseline_then_emits_update(db) -> None:
    _repo(db, "updates-test/repo")

    versions = {"tag": "v1.0.0"}

    async def fetcher(repo_id: str):
        if versions["tag"] == "missing":
            return None
        return [
            _release(versions["tag"], name=f"Release {versions['tag']}", body="常规更新",
                     published="2026-10-20T00:00:00Z")
        ]

    first = asyncio.run(
        scan_repositories(db, ["updates-test/repo"], fetcher=fetcher, now=NOW)
    )
    assert first["checked"] == 1
    assert first["events"] == []
    row = db.get(MyRepository, "updates-test/repo")
    assert row is not None
    assert row.latest_release_tag == "v1.0.0"
    assert row.latest_release_checked_at == NOW

    versions["tag"] = "v2.0.0"
    second = asyncio.run(
        scan_repositories(db, ["updates-test/repo"], fetcher=fetcher, now=NOW)
    )
    assert second["checked"] == 1
    assert len(second["events"]) == 1
    event = second["events"][0]
    assert event["repoId"] == "updates-test/repo"
    assert event["version"] == "v2.0.0"
    assert event["type"] == UPDATE_TYPE_MAJOR
    assert event["url"].endswith("/v2.0.0")

    # 同一版本重复扫描不重复产生事件
    third = asyncio.run(
        scan_repositories(db, ["updates-test/repo"], fetcher=fetcher, now=NOW)
    )
    assert third["events"] == []

    # 拉取失败只跳过，不覆盖既有基线
    versions["tag"] = "missing"
    fourth = asyncio.run(
        scan_repositories(db, ["updates-test/repo"], fetcher=fetcher, now=NOW)
    )
    assert fourth["skipped"] == 1
    assert db.get(MyRepository, "updates-test/repo").latest_release_tag == "v2.0.0"


def test_scan_repositories_skips_unknown_and_non_github(db) -> None:
    _repo(db, "updates-test/none")

    async def empty_fetcher(repo_id: str):
        return []

    result = asyncio.run(
        scan_repositories(
            db, ["updates-test/none", "updates-test/missing"], fetcher=empty_fetcher, now=NOW
        )
    )
    assert result["checked"] == 0
    assert result["skipped"] == 1
    assert result["events"] == []


def test_updates_scan_api_enqueues_task() -> None:
    with TestClient(app) as client:
        resp = client.post(
            "/api/repos/updates/scan",
            json={"repoIds": ["updates-test/repo"], "limit": 10},
        )
        assert resp.status_code == 202
        assert resp.json().get("taskId")
