"""GitHub REST v3 异步客户端（httpx）。

职责：拉取用户仓库 / Starred 列表、仓库详情与 README。
同步范围：本人 owner 的仓库 + 作为组织成员可见的组织仓库（显式 affiliation，
不含 collaborator 仓库），并按可配置策略过滤 fork / 归档仓库。
容错策略：401/403/404 与网络错误一律优雅降级（返回已获取的数据并记录日志），不向上抛异常。
"""
from __future__ import annotations

import base64
import logging
from dataclasses import dataclass, field, replace
from typing import Any

import httpx

logger = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"
_TIMEOUT = httpx.Timeout(30.0, connect=10.0)

# 过滤原因（用于任务结果统计，保持稳定英文 key）
EXCLUSION_REASONS: tuple[str, ...] = (
    "own_disabled",
    "org_disabled",
    "org_not_allowed",
    "fork",
    "archived",
)


class GitHubServiceError(Exception):
    """GitHub 调用异常（保留给需要区分错误的调用方）。"""


def _as_bool(value: Any, default: bool) -> bool:
    """宽松布尔转换：兼容 bool / 0-1 / true-false 字符串（环境变量场景）。"""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() not in {"", "0", "false", "no", "off"}
    return bool(value)


def _headers(token: str | None = None) -> dict[str, str]:
    """构造请求头；token 为空时走匿名（受更严格限流）。"""
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "OpenFactory-VPS/1.0",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _owner_of(repo: dict[str, Any]) -> dict[str, Any]:
    """取出仓库 owner 对象（GitHub 列表接口中的嵌套结构）。"""
    owner = repo.get("owner")
    return owner if isinstance(owner, dict) else {}


def repo_is_org(repo: dict[str, Any]) -> bool:
    """判断仓库是否归属组织（owner.type == Organization）。"""
    return str(_owner_of(repo).get("type") or "").lower() == "organization"


def repo_owner_login(repo: dict[str, Any]) -> str:
    """仓库 owner 登录名；缺失时从 full_name 前缀兜底。"""
    login = str(_owner_of(repo).get("login") or "")
    if login:
        return login
    full_name = str(repo.get("full_name") or "")
    return full_name.split("/")[0] if "/" in full_name else ""


@dataclass(frozen=True)
class RepoFilterPolicy:
    """自有 / 组织仓库的过滤策略（可部署级配置，也可单次任务覆盖）。"""

    include_own: bool = True
    include_orgs: bool = True
    include_forks: bool = False
    include_archived: bool = False
    org_allowlist: tuple[str, ...] = ()

    @classmethod
    def from_settings(cls, settings: Any) -> "RepoFilterPolicy":
        """从 Settings 构建策略；缺失字段按默认值处理。"""
        raw_allowlist = getattr(settings, "GITHUB_SYNC_ORG_ALLOWLIST", "") or ""
        allowlist = tuple(
            item.strip().lower() for item in str(raw_allowlist).split(",") if item.strip()
        )
        return cls(
            include_own=_as_bool(getattr(settings, "GITHUB_SYNC_INCLUDE_OWN", True), True),
            include_orgs=_as_bool(getattr(settings, "GITHUB_SYNC_INCLUDE_ORGS", True), True),
            include_forks=_as_bool(getattr(settings, "GITHUB_SYNC_INCLUDE_FORKS", False), False),
            include_archived=_as_bool(
                getattr(settings, "GITHUB_SYNC_INCLUDE_ARCHIVED", False), False
            ),
            org_allowlist=allowlist,
        )

    def with_overrides(
        self,
        *,
        include_own: bool | None = None,
        include_orgs: bool | None = None,
        include_forks: bool | None = None,
        include_archived: bool | None = None,
    ) -> "RepoFilterPolicy":
        """返回叠加单次任务覆盖后的新策略（None 表示沿用当前值）。"""
        return replace(
            self,
            include_own=self.include_own if include_own is None else bool(include_own),
            include_orgs=self.include_orgs if include_orgs is None else bool(include_orgs),
            include_forks=self.include_forks if include_forks is None else bool(include_forks),
            include_archived=(
                self.include_archived if include_archived is None else bool(include_archived)
            ),
        )

    def evaluate(self, repo: dict[str, Any]) -> str | None:
        """评估单条仓库：None = 保留，否则返回排除原因。"""
        is_org = repo_is_org(repo)
        if is_org and not self.include_orgs:
            return "org_disabled"
        if not is_org and not self.include_own:
            return "own_disabled"
        if is_org and self.org_allowlist:
            if repo_owner_login(repo).lower() not in self.org_allowlist:
                return "org_not_allowed"
        if bool(repo.get("fork")) and not self.include_forks:
            return "fork"
        if bool(repo.get("archived")) and not self.include_archived:
            return "archived"
        return None


@dataclass
class RepoCollection:
    """一次仓库同步拉取的结果与过滤统计。"""

    repos: list[dict[str, Any]] = field(default_factory=list)
    fetched: int = 0
    starred: int = 0
    own: int = 0
    org: int = 0
    excluded: dict[str, int] = field(
        default_factory=lambda: {reason: 0 for reason in EXCLUSION_REASONS}
    )

    @property
    def filtered(self) -> int:
        """被过滤策略排除的仓库数。"""
        return sum(self.excluded.values())


def normalize_repo(repo: dict[str, Any]) -> dict[str, Any]:
    """把 GitHub API 仓库对象标准化为本地统一结构。"""
    full_name = repo.get("full_name") or ""
    owner = repo_owner_login(repo)
    return {
        "id": full_name,  # 以 "owner/repo" 作为主键
        "platform": "github",
        "name": repo.get("name") or (full_name.split("/")[-1] if full_name else ""),
        "description": repo.get("description") or "",
        "html_url": repo.get("html_url") or (f"https://github.com/{full_name}" if full_name else ""),
        "stars": int(repo.get("stargazers_count") or 0),
        "language": repo.get("language") or "",
        "owner": owner,
        "owner_type": str(_owner_of(repo).get("type") or ""),
        "forks": int(repo.get("forks_count") or 0),
        "fork": bool(repo.get("fork")),
        "archived": bool(repo.get("archived")),
        "private": bool(repo.get("private")),
        "updated_at": str(repo.get("updated_at") or ""),
        "pushed_at": str(repo.get("pushed_at") or ""),
    }


async def _paginate(
    client: httpx.AsyncClient,
    url: str,
    token: str,
    *,
    params: dict[str, Any] | None = None,
    per_page: int = 100,
    max_pages: int = 10,
) -> list[dict[str, Any]]:
    """按页拉取列表接口；遇到 401/403/404 或网络错误时返回已获取的部分。"""
    items: list[dict[str, Any]] = []
    for page in range(1, max_pages + 1):
        query: dict[str, Any] = {"per_page": per_page, "page": page}
        if params:
            query.update(params)
        try:
            resp = await client.get(url, headers=_headers(token), params=query)
        except httpx.HTTPError as exc:
            logger.warning("GitHub 请求失败 %s: %s", url, exc)
            break
        if resp.status_code in (401, 403):
            logger.warning("GitHub 拒绝访问 %s（HTTP %s），返回已获取数据", url, resp.status_code)
            break
        if resp.status_code == 404:
            logger.info("GitHub 资源不存在: %s", url)
            break
        if resp.status_code != 200:
            logger.warning("GitHub 异常状态 %s: %s", resp.status_code, url)
            break
        try:
            batch = resp.json()
        except ValueError as exc:
            logger.warning("GitHub 响应不是 JSON %s: %s", url, exc)
            break
        if not isinstance(batch, list) or not batch:
            break
        items.extend(item for item in batch if isinstance(item, dict))
        if len(batch) < per_page:
            break
    return items


def _affiliation(policy: RepoFilterPolicy) -> str:
    """根据策略组合 GitHub `affiliation` 参数；两者都关时返回空串。"""
    scopes: list[str] = []
    if policy.include_own:
        scopes.append("owner")
    if policy.include_orgs:
        scopes.append("organization_member")
    return ",".join(scopes)


async def collect_user_repos(
    token: str,
    include_starred: bool = True,
    *,
    policy: RepoFilterPolicy | None = None,
    per_page: int = 100,
    max_pages: int = 10,
    transport: httpx.AsyncBaseTransport | None = None,
) -> RepoCollection:
    """拉取自有 + 组织仓库并按策略过滤，可选合并 Starred 仓库。

    - 自有 / 组织仓库：`GET /user/repos?affiliation=owner,organization_member`；
    - Starred：`GET /user/starred`，属于用户主动收藏，不应用自有/组织过滤策略；
    - 同一 full_name 去重（自有/组织优先），返回过滤统计供任务结果使用。
    """
    policy = policy or RepoFilterPolicy()
    result = RepoCollection()

    async with httpx.AsyncClient(
        timeout=_TIMEOUT, follow_redirects=True, transport=transport
    ) as client:
        affiliation = _affiliation(policy)
        if affiliation:
            own_and_org = await _paginate(
                client,
                f"{GITHUB_API}/user/repos",
                token,
                params={"affiliation": affiliation, "visibility": "all", "sort": "updated"},
                per_page=per_page,
                max_pages=max_pages,
            )
            collected: dict[str, dict[str, Any]] = {}
            for item in own_and_org:
                full_name = item.get("full_name")
                if not full_name or full_name in collected:
                    continue
                collected[full_name] = item

            result.fetched = len(collected)
            for item in collected.values():
                reason = policy.evaluate(item)
                if reason is not None:
                    result.excluded[reason] = result.excluded.get(reason, 0) + 1
                    continue
                repo = normalize_repo(item)
                result.repos.append(repo)
                if repo["owner_type"].lower() == "organization":
                    result.org += 1
                else:
                    result.own += 1
        else:
            logger.info("自有仓库与组织仓库同步均已关闭，跳过 /user/repos 拉取")

        if include_starred:
            starred = await _paginate(
                client,
                f"{GITHUB_API}/user/starred",
                token,
                per_page=per_page,
                max_pages=max_pages,
            )
            seen = {repo["id"] for repo in result.repos}
            starred_ids: set[str] = set()
            for item in starred:
                repo_obj = item.get("repo") if isinstance(item.get("repo"), dict) else item
                if not isinstance(repo_obj, dict):
                    continue
                full_name = repo_obj.get("full_name")
                if not full_name:
                    continue
                starred_ids.add(full_name)
                if full_name in seen:
                    continue
                seen.add(full_name)
                result.repos.append(normalize_repo(repo_obj))
            result.starred = len(starred_ids)

    return result


async def list_user_repos(
    token: str,
    include_starred: bool = True,
    *,
    policy: RepoFilterPolicy | None = None,
    per_page: int = 100,
    max_pages: int = 10,
    transport: httpx.AsyncBaseTransport | None = None,
) -> list[dict[str, Any]]:
    """列出 token 对应用户自己的仓库（含组织仓库）以及可选的 Starred 仓库。

    返回标准化字典列表（按 full_name 去重），字段：
    id / platform / name / description / html_url / stars / language / owner /
    owner_type / forks / fork / archived / private / updated_at / pushed_at。
    """
    collection = await collect_user_repos(
        token,
        include_starred=include_starred,
        policy=policy,
        per_page=per_page,
        max_pages=max_pages,
        transport=transport,
    )
    return collection.repos


async def get_repo(token: str | None, full_name: str) -> dict[str, Any] | None:
    """获取单个仓库信息；404/403 或网络异常时返回 None。"""
    async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
        try:
            resp = await client.get(f"{GITHUB_API}/repos/{full_name}", headers=_headers(token))
        except httpx.HTTPError as exc:
            logger.warning("获取仓库 %s 失败: %s", full_name, exc)
            return None
    if resp.status_code == 404:
        logger.info("仓库不存在: %s", full_name)
        return None
    if resp.status_code in (401, 403):
        logger.warning("无权限访问仓库 %s（HTTP %s）", full_name, resp.status_code)
        return None
    if resp.status_code != 200:
        logger.warning("获取仓库 %s 异常状态: %s", full_name, resp.status_code)
        return None
    return normalize_repo(resp.json())


async def get_readme(token: str | None, full_name: str, *, max_chars: int = 20000) -> str:
    """获取仓库 README 并 base64 解码；任何失败返回空字符串。"""
    async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
        try:
            resp = await client.get(
                f"{GITHUB_API}/repos/{full_name}/readme", headers=_headers(token)
            )
        except httpx.HTTPError as exc:
            logger.warning("获取 README %s 失败: %s", full_name, exc)
            return ""
    if resp.status_code in (403, 404):
        logger.info("README 不可用 %s（HTTP %s）", full_name, resp.status_code)
        return ""
    if resp.status_code != 200:
        return ""
    content = (resp.json() or {}).get("content") or ""
    if not content:
        return ""
    try:
        decoded = base64.b64decode(content).decode("utf-8", errors="replace")
    except Exception as exc:  # noqa: BLE001 - 解码失败一律降级为空字符串
        logger.warning("README base64 解码失败 %s: %s", full_name, exc)
        return ""
    return decoded[:max_chars]
