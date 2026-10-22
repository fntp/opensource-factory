"""GitHub 仓库同步策略测试（纯函数 + MockTransport，无网络）。"""
from __future__ import annotations

import asyncio
from typing import Any

import httpx

from app.services.github_service import (
    RepoFilterPolicy,
    collect_user_repos,
    normalize_repo,
    repo_is_org,
)


def _repo(
    full_name: str,
    *,
    owner_type: str = "User",
    fork: bool = False,
    archived: bool = False,
    stars: int = 0,
    forks: int = 0,
) -> dict[str, Any]:
    owner, name = full_name.split("/", 1)
    return {
        "full_name": full_name,
        "name": name,
        "description": f"{name} 描述",
        "html_url": f"https://github.com/{full_name}",
        "stargazers_count": stars,
        "forks_count": forks,
        "language": "Python",
        "owner": {"login": owner, "type": owner_type},
        "fork": fork,
        "archived": archived,
        "private": False,
        "updated_at": "2026-10-20T08:00:00Z",
        "pushed_at": "2026-10-19T08:00:00Z",
    }


def test_normalize_repo_keeps_filter_and_metadata_fields() -> None:
    normalized = normalize_repo(
        _repo("acme/widgets", owner_type="Organization", fork=True, archived=True, forks=12)
    )
    assert normalized["id"] == "acme/widgets"
    assert normalized["owner"] == "acme"
    assert normalized["owner_type"] == "Organization"
    assert normalized["forks"] == 12
    assert normalized["fork"] is True
    assert normalized["archived"] is True
    assert normalized["updated_at"] == "2026-10-20T08:00:00Z"
    assert repo_is_org(_repo("acme/widgets", owner_type="Organization")) is True
    assert repo_is_org(_repo("fntp/dotfiles")) is False


def test_policy_defaults_keep_own_and_org_but_exclude_fork_and_archived() -> None:
    policy = RepoFilterPolicy()
    assert policy.evaluate(_repo("fntp/notes")) is None
    assert policy.evaluate(_repo("acme/widgets", owner_type="Organization")) is None
    assert policy.evaluate(_repo("fntp/old-fork", fork=True)) == "fork"
    assert policy.evaluate(_repo("fntp/legacy", archived=True)) == "archived"


def test_policy_switches_and_org_allowlist() -> None:
    own_only = RepoFilterPolicy(include_orgs=False)
    assert own_only.evaluate(_repo("fntp/notes")) is None
    assert own_only.evaluate(_repo("acme/widgets", owner_type="Organization")) == "org_disabled"

    org_only = RepoFilterPolicy(include_own=False)
    assert org_only.evaluate(_repo("fntp/notes")) == "own_disabled"
    assert org_only.evaluate(_repo("acme/widgets", owner_type="Organization")) is None

    allowlisted = RepoFilterPolicy(org_allowlist=("acme",))
    assert allowlisted.evaluate(_repo("acme/widgets", owner_type="Organization")) is None
    assert allowlisted.evaluate(_repo("other/widgets", owner_type="Organization")) == "org_not_allowed"

    permissive = RepoFilterPolicy(include_forks=True, include_archived=True)
    assert permissive.evaluate(_repo("fntp/old-fork", fork=True)) is None
    assert permissive.evaluate(_repo("fntp/legacy", archived=True)) is None


def test_policy_from_settings_and_overrides() -> None:
    class _Settings:
        GITHUB_SYNC_INCLUDE_OWN = "false"
        GITHUB_SYNC_INCLUDE_ORGS = True
        GITHUB_SYNC_INCLUDE_FORKS = "true"
        GITHUB_SYNC_INCLUDE_ARCHIVED = False
        GITHUB_SYNC_ORG_ALLOWLIST = " Acme, Other "

    policy = RepoFilterPolicy.from_settings(_Settings())
    assert policy.include_own is False
    assert policy.include_forks is True
    assert policy.org_allowlist == ("acme", "other")

    overridden = policy.with_overrides(include_own=True, include_archived=True)
    assert overridden.include_own is True
    assert overridden.include_archived is True
    assert overridden.include_forks is True


def test_collect_user_repos_uses_affiliation_and_filters() -> None:
    seen_affiliations: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/user/repos":
            seen_affiliations.append(request.url.params.get("affiliation", ""))
            return httpx.Response(
                200,
                json=[
                    _repo("fntp/notes", stars=5),
                    _repo("acme/widgets", owner_type="Organization", stars=9),
                    _repo("fntp/old-fork", fork=True),
                    _repo("fntp/legacy", archived=True),
                ],
            )
        if request.url.path == "/user/starred":
            return httpx.Response(
                200,
                json=[{"repo": _repo("someone/cool-project", fork=True, archived=True)}],
            )
        return httpx.Response(404, json={"message": "not found"})

    transport = httpx.MockTransport(handler)
    collection = asyncio.run(
        collect_user_repos("token", include_starred=True, transport=transport)
    )

    assert seen_affiliations == ["owner,organization_member"]
    assert [repo["id"] for repo in collection.repos] == [
        "fntp/notes",
        "acme/widgets",
        "someone/cool-project",
    ]
    assert collection.fetched == 4
    assert collection.own == 1
    assert collection.org == 1
    assert collection.starred == 1
    assert collection.excluded["fork"] == 1
    assert collection.excluded["archived"] == 1
    assert collection.filtered == 2


def test_collect_user_repos_paginates_and_can_skip_user_endpoint() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/user/repos"
        calls.append(int(request.url.params.get("page", "0")))
        if request.url.params.get("page") == "1":
            return httpx.Response(200, json=[_repo("fntp/a"), _repo("fntp/b")])
        if request.url.params.get("page") == "2":
            return httpx.Response(200, json=[_repo("fntp/c")])
        return httpx.Response(200, json=[])

    transport = httpx.MockTransport(handler)
    collection = asyncio.run(
        collect_user_repos(
            "token", include_starred=False, per_page=2, max_pages=3, transport=transport
        )
    )
    assert calls == [1, 2]
    assert collection.fetched == 3
    assert collection.own == 3

    def fail_user_repos(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"不应请求 {request.url.path}")

    disabled = asyncio.run(
        collect_user_repos(
            "token",
            include_starred=False,
            policy=RepoFilterPolicy(include_own=False, include_orgs=False),
            transport=httpx.MockTransport(fail_user_repos),
        )
    )
    assert disabled.repos == []
    assert disabled.fetched == 0
