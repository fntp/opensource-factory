"""GitHub REST v3 异步客户端（httpx）。

职责：拉取用户仓库 / Starred 列表、仓库详情与 README。
容错策略：401/403/404 与网络错误一律优雅降级（返回空结果并记录日志），不向上抛异常。
"""
from __future__ import annotations

import base64
import logging
from datetime import datetime, timezone
from typing import Any

import httpx

logger = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"
_TIMEOUT = httpx.Timeout(30.0, connect=10.0)


def _parse_github_time(value: Any) -> datetime | None:
    """解析 GitHub ISO 时间（如 `2026-10-20T08:00:00Z`）为无时区 UTC。"""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


class GitHubServiceError(Exception):
    """GitHub 调用异常（保留给需要区分错误的调用方）。"""


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


def normalize_repo(repo: dict[str, Any]) -> dict[str, Any]:
    """把 GitHub API 仓库对象标准化为本地统一结构。"""
    full_name = repo.get("full_name") or ""
    return {
        "id": full_name,  # 以 "owner/repo" 作为主键
        "platform": "github",
        "name": repo.get("name") or (full_name.split("/")[-1] if full_name else ""),
        "description": repo.get("description") or "",
        "html_url": repo.get("html_url") or (f"https://github.com/{full_name}" if full_name else ""),
        "stars": int(repo.get("stargazers_count") or 0),
        "language": repo.get("language") or "",
        "forks": int(repo.get("forks_count") or 0),
        # M6-05 项目健康度：最后提交 / issue 活跃 / 归档标记
        "pushed_at": _parse_github_time(repo.get("pushed_at")),
        "updated_at": _parse_github_time(repo.get("updated_at")),
        "open_issues_count": int(repo.get("open_issues_count") or 0),
        "archived": bool(repo.get("archived")),
        "disabled": bool(repo.get("disabled")),
        "default_branch": repo.get("default_branch") or "",
    }


async def _paginate(
    client: httpx.AsyncClient,
    url: str,
    token: str,
    *,
    per_page: int = 100,
    max_pages: int = 10,
) -> list[dict[str, Any]]:
    """按页拉取列表接口；遇到 401/403/404 或网络错误时返回已获取的部分。"""
    items: list[dict[str, Any]] = []
    for page in range(1, max_pages + 1):
        try:
            resp = await client.get(
                url, headers=_headers(token), params={"per_page": per_page, "page": page}
            )
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


async def list_user_repos(
    token: str,
    include_starred: bool = True,
    *,
    per_page: int = 100,
    max_pages: int = 10,
) -> list[dict[str, Any]]:
    """列出 token 对应用户自己的仓库（含协作者仓库）以及可选的 Starred 仓库。

    返回标准化字典列表（按 full_name 去重），字段：
    id / platform / name / description / html_url / stars / language / forks。
    """
    collected: dict[str, dict[str, Any]] = {}
    async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
        own = await _paginate(
            client, f"{GITHUB_API}/user/repos", token, per_page=per_page, max_pages=max_pages
        )
        for item in own:
            if item.get("full_name"):
                collected[item["full_name"]] = normalize_repo(item)

        if include_starred:
            starred = await _paginate(
                client, f"{GITHUB_API}/user/starred", token, per_page=per_page, max_pages=max_pages
            )
            for item in starred:
                repo = item.get("repo") if isinstance(item.get("repo"), dict) else item
                if isinstance(repo, dict) and repo.get("full_name"):
                    collected.setdefault(repo["full_name"], normalize_repo(repo))
    return list(collected.values())


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
