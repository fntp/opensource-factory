"""GitHub REST v3 异步客户端（httpx）。

职责：拉取用户仓库 / Starred 列表、仓库详情与 README。

容错策略（REQ-202610-0897）：
- **分页**：按 `Link` 响应头跟进，默认 100 条/页，Starred 默认不设页数上限；
- **限流**：请求间隔节流；识别 `X-RateLimit-*` 与 `Retry-After`，额度耗尽时等待重置；
- **重试**：网络错误 / 5xx / 429 指数退避重试；401 / 404 / 非限流 403 不重试；
- **进度**：逐页回调 `SyncProgress`，供 Celery 任务上报；
- **降级**：`get_repo` / `get_readme` 保持优雅降级；列表接口抛结构化异常，由调用方决定部分结果。
"""
from __future__ import annotations

import asyncio
import base64
import logging
import re
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Iterable

import httpx

logger = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"
_TIMEOUT = httpx.Timeout(30.0, connect=10.0)

_LINK_RE = re.compile(r'<([^>]+)>\s*;\s*rel="([^"]+)"')


class GitHubServiceError(Exception):
    """GitHub 调用异常基类。

    `partial_items` 保留失败前已抓取的数据，便于全量同步落库部分结果。
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        partial_items: Iterable[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.partial_items: list[dict[str, Any]] = list(partial_items or [])


class GitHubAuthError(GitHubServiceError):
    """鉴权失败（401），不重试。"""


class GitHubNotFoundError(GitHubServiceError):
    """资源不存在（404），不重试。"""


class GitHubRateLimitError(GitHubServiceError):
    """限流且重试次数耗尽。"""


class GitHubRequestError(GitHubServiceError):
    """网络错误 / 5xx / 非预期状态。"""


@dataclass(frozen=True)
class GitHubClientConfig:
    """客户端行为配置（测试可整体替换）。"""

    per_page: int = 100
    min_interval: float = 0.2  # 相邻请求最小间隔（秒），避免触发二级限流
    max_retries: int = 3
    backoff_base: float = 1.0
    backoff_max: float = 30.0
    max_rate_limit_wait: float = 3600.0  # 单次等待额度重置的上限（秒）


@dataclass(frozen=True)
class SyncProgress:
    """同步进度快照（每页一次 + 完成时一次）。"""

    phase: str
    page: int
    pages_total: int | None
    fetched: int
    total: int | None = None
    done: bool = False

    @property
    def percent(self) -> int:
        """进度百分比：未知总页数时为 0，完成后为 100。"""
        if self.done:
            return 100
        if self.pages_total and self.pages_total > 0:
            return max(0, min(99, round(self.page * 100 / self.pages_total)))
        return 0

    def to_dict(self) -> dict[str, Any]:
        """转为 camelCase 字典，供 Celery meta / HTTP 返回。"""
        return {
            "phase": self.phase,
            "page": self.page,
            "pagesTotal": self.pages_total,
            "fetched": self.fetched,
            "total": self.total,
            "percent": self.percent,
            "done": self.done,
        }


def _headers(token: str | None = None, accept: str | None = None) -> dict[str, str]:
    """构造请求头；token 为空时走匿名（受更严格限流）。"""
    headers = {
        "Accept": accept or "application/vnd.github+json",
        "User-Agent": "OpenFactory-VPS/1.0",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def parse_link_header(header: str | None) -> dict[str, str]:
    """解析 RFC 5988 `Link` 响应头，返回 `{rel: url}`。"""
    return {rel: url for url, rel in _LINK_RE.findall(header or "")}


def _page_number(url: str) -> int | None:
    """从分页 URL 中提取 `page` 参数。"""
    match = re.search(r"[?&]page=(\d+)", url)
    return int(match.group(1)) if match else None


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
    }


def normalize_starred(items: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """标准化 Starred 列表，兼容裸仓库对象与 `{starred_at, repo}` 包装。"""
    repos: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        repo = item.get("repo") if isinstance(item.get("repo"), dict) else item
        if not isinstance(repo, dict):
            continue
        full_name = repo.get("full_name")
        if not full_name or full_name in seen:
            continue
        seen.add(full_name)
        repos.append(normalize_repo(repo))
    return repos


class GitHubClient:
    """带节流 / 限流等待 / 重试 / 分页进度的 GitHub REST 客户端。

    用法::

        async with GitHubClient(token) as client:
            items, pages = await client.paginate(
                f"{GITHUB_API}/user/starred", on_progress=callback
            )

    `http_client` / `sleep` / `time_func` 可注入，测试不访问网络、不真实等待。
    """

    def __init__(
        self,
        token: str | None = None,
        *,
        config: GitHubClientConfig | None = None,
        http_client: httpx.AsyncClient | None = None,
        sleep: Callable[[float], Awaitable[None]] | None = None,
        time_func: Callable[[], float] = time.time,
    ) -> None:
        self.token = token or ""
        self.config = config or GitHubClientConfig()
        self._http = http_client
        self._owns_http = http_client is None
        self._sleep = sleep or asyncio.sleep
        self._time = time_func
        self._last_request_at: float | None = None
        self._rate_remaining: int | None = None
        self._rate_reset_at: float | None = None

    async def __aenter__(self) -> "GitHubClient":
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        """关闭自建的 httpx 客户端（注入的客户端由调用方管理）。"""
        if self._owns_http and self._http is not None:
            await self._http.aclose()
            self._http = None

    @property
    def http(self) -> httpx.AsyncClient:
        """惰性创建 httpx 客户端。"""
        if self._http is None:
            self._http = httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True)
        return self._http

    async def request(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        accept: str | None = None,
    ) -> httpx.Response:
        """发起 GET 请求，处理节流、限流等待与重试。

        成功返回 2xx / 3xx 响应；失败抛 `GitHubServiceError` 子类。
        """
        headers = _headers(self.token, accept)
        last_error: Exception | None = None

        for attempt in range(self.config.max_retries + 1):
            await self._wait_for_rate_limit()
            await self._throttle()
            try:
                resp = await self.http.get(url, headers=headers, params=params)
            except httpx.HTTPError as exc:
                last_error = exc
                if attempt >= self.config.max_retries:
                    raise GitHubRequestError(f"GitHub 请求失败: {exc}") from exc
                delay = self._backoff_delay(attempt)
                logger.warning("GitHub 网络错误，%.1fs 后重试（%s）: %s", delay, attempt + 1, exc)
                await self._sleep(delay)
                continue

            self._last_request_at = self._time()
            self._update_rate_limit(resp)

            if resp.status_code < 400:
                return resp
            if resp.status_code == 401:
                raise GitHubAuthError("GitHub 鉴权失败（401），请检查 token", status_code=401)
            if resp.status_code == 404:
                raise GitHubNotFoundError(f"GitHub 资源不存在（404）: {url}", status_code=404)
            if resp.status_code in (403, 429):
                delay = self._rate_limit_delay(resp)
                if delay is not None and attempt < self.config.max_retries:
                    logger.warning(
                        "GitHub 限流（HTTP %s），%.1fs 后重试（%s）", resp.status_code, delay, attempt + 1
                    )
                    await self._sleep(delay)
                    continue
                if resp.status_code == 429 or self._is_rate_limited(resp):
                    raise GitHubRateLimitError(
                        f"GitHub 限流未恢复（HTTP {resp.status_code}）: {url}",
                        status_code=resp.status_code,
                    )
                raise GitHubServiceError(
                    f"GitHub 拒绝访问（HTTP {resp.status_code}）: {url}",
                    status_code=resp.status_code,
                )
            if 500 <= resp.status_code < 600:
                last_error = GitHubRequestError(
                    f"GitHub 服务端错误（HTTP {resp.status_code}）: {url}",
                    status_code=resp.status_code,
                )
                if attempt >= self.config.max_retries:
                    raise last_error
                delay = self._backoff_delay(attempt)
                logger.warning(
                    "GitHub 服务端错误 %s，%.1fs 后重试（%s）", resp.status_code, delay, attempt + 1
                )
                await self._sleep(delay)
                continue
            raise GitHubRequestError(
                f"GitHub 异常状态（HTTP {resp.status_code}）: {url}", status_code=resp.status_code
            )

        # 理论上不可达；保留兜底便于类型检查与防御性编程。
        raise GitHubRequestError(f"GitHub 请求失败: {last_error}")

    async def paginate(
        self,
        url: str,
        *,
        per_page: int | None = None,
        max_pages: int | None = None,
        phase: str = "starred",
        accept: str | None = None,
        on_progress: Callable[[SyncProgress], None] | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        """按页拉取列表接口，返回 `(全部条目, 总页数)`。

        - 首页使用 `per_page` / `page=1`，后续页直接跟随 `Link rel="next"`；
        - `max_pages=None` 表示不设上限（全量同步）；
        - 失败时抛 `GitHubServiceError`，其 `partial_items` 保留已抓取条目。
        """
        size = per_page or self.config.per_page
        items: list[dict[str, Any]] = []
        next_url: str | None = url
        page = 1
        pages_total: int | None = None

        while next_url:
            params = {"per_page": size, "page": page} if page == 1 else None
            try:
                resp = await self.request(next_url, params=params, accept=accept)
            except GitHubServiceError as exc:
                exc.partial_items = list(items)
                raise
            try:
                payload = resp.json()
            except ValueError as exc:
                raise GitHubRequestError(f"GitHub 响应不是 JSON: {url}", partial_items=items) from exc

            if isinstance(payload, list):
                batch = [item for item in payload if isinstance(item, dict)]
            elif isinstance(payload, dict):
                raw_items = payload.get("items")
                batch = (
                    [item for item in raw_items if isinstance(item, dict)]
                    if isinstance(raw_items, list)
                    else []
                )
            else:
                batch = []

            items.extend(batch)
            links = parse_link_header(resp.headers.get("link"))
            if pages_total is None and links.get("last"):
                pages_total = _page_number(links["last"])

            if on_progress is not None:
                on_progress(
                    SyncProgress(
                        phase=phase,
                        page=page,
                        pages_total=pages_total,
                        fetched=len(items),
                    )
                )

            next_url = links.get("next")
            if not next_url:
                break
            if max_pages is not None and page >= max_pages:
                break
            page += 1
            if page > 10000:  # 防御：异常 Link 头导致死循环
                logger.warning("GitHub 分页超过 10000 页，提前终止: %s", url)
                break

        if on_progress is not None:
            on_progress(
                SyncProgress(
                    phase=phase,
                    page=page,
                    pages_total=pages_total,
                    fetched=len(items),
                    total=len(items),
                    done=True,
                )
            )
        return items, pages_total or page

    async def _throttle(self) -> None:
        """保证相邻请求间隔不小于 `min_interval`。"""
        if self._last_request_at is None or self.config.min_interval <= 0:
            return
        wait = self.config.min_interval - (self._time() - self._last_request_at)
        if wait > 0:
            await self._sleep(wait)

    async def _wait_for_rate_limit(self) -> None:
        """额度已耗尽时，等待到重置时间再发请求。"""
        if self._rate_remaining != 0 or self._rate_reset_at is None:
            return
        wait = self._rate_reset_at - self._time() + 1.0
        if wait <= 0:
            return
        wait = min(wait, self.config.max_rate_limit_wait)
        logger.warning("GitHub API 额度耗尽，等待 %.0fs 后重试", wait)
        await self._sleep(wait)
        # 等待结束后由下一次响应刷新真实额度，避免重复等待。
        self._rate_remaining = None

    def _update_rate_limit(self, resp: httpx.Response) -> None:
        """从响应头记录剩余额度与重置时间。"""
        remaining = resp.headers.get("x-ratelimit-remaining")
        if remaining is not None:
            try:
                self._rate_remaining = int(remaining)
            except ValueError:
                pass
        reset = resp.headers.get("x-ratelimit-reset")
        if reset is not None:
            try:
                self._rate_reset_at = float(reset)
            except ValueError:
                pass

    def _is_rate_limited(self, resp: httpx.Response) -> bool:
        """判断 403 是否属于限流（而非权限不足）。"""
        return resp.headers.get("retry-after") is not None or resp.headers.get("x-ratelimit-remaining") == "0"

    def _rate_limit_delay(self, resp: httpx.Response) -> float | None:
        """计算限流后的等待时间；非限流返回 None。"""
        retry_after = resp.headers.get("retry-after")
        if retry_after:
            try:
                return max(0.0, float(retry_after))
            except ValueError:
                logger.debug("无法解析 Retry-After: %s", retry_after)
        if resp.headers.get("x-ratelimit-remaining") == "0" and self._rate_reset_at is not None:
            wait = self._rate_reset_at - self._time() + 1.0
            return max(1.0, min(wait, self.config.max_rate_limit_wait))
        return None

    def _backoff_delay(self, attempt: int) -> float:
        """指数退避：base * 2^attempt，封顶 backoff_max。"""
        return min(self.config.backoff_base * (2**attempt), self.config.backoff_max)


async def list_starred_repos(
    token: str,
    *,
    per_page: int = 100,
    max_pages: int | None = None,
    on_progress: Callable[[SyncProgress], None] | None = None,
    client: GitHubClient | None = None,
) -> list[dict[str, Any]]:
    """全量拉取当前用户的 Starred 仓库。

    `max_pages=None` 时不设页数上限；返回标准化字典列表（按 full_name 去重）。
    失败时抛 `GitHubServiceError`，`partial_items` 为原始条目（调用方可自行标准化）。
    """
    if client is None:
        async with GitHubClient(token) as owned:
            items, _ = await owned.paginate(
                f"{GITHUB_API}/user/starred",
                per_page=per_page,
                max_pages=max_pages,
                phase="starred",
                on_progress=on_progress,
            )
            return normalize_starred(items)
    items, _ = await client.paginate(
        f"{GITHUB_API}/user/starred",
        per_page=per_page,
        max_pages=max_pages,
        phase="starred",
        on_progress=on_progress,
    )
    return normalize_starred(items)


async def list_user_repos(
    token: str,
    include_starred: bool = True,
    *,
    per_page: int = 100,
    max_pages: int = 10,
    starred_max_pages: int | None = None,
    on_progress: Callable[[SyncProgress], None] | None = None,
) -> list[dict[str, Any]]:
    """列出 token 对应用户自己的仓库（含协作者仓库）以及可选的 Starred 仓库。

    - 自有仓库默认最多 10 页（M1-06 再做全量与过滤策略）；
    - Starred 默认全量（`starred_max_pages=None`），逐页回调进度；
    - 任一阶段失败时保留已获取数据并记录日志（优雅降级）。

    返回标准化字典列表（按 full_name 去重），字段：
    id / platform / name / description / html_url / stars / language / forks。
    """
    collected: dict[str, dict[str, Any]] = {}

    async with GitHubClient(token) as client:
        try:
            own, _ = await client.paginate(
                f"{GITHUB_API}/user/repos",
                per_page=per_page,
                max_pages=max_pages,
                phase="own",
            )
        except GitHubServiceError as exc:
            logger.warning("自有仓库同步中断，使用已获取的 %d 条: %s", len(exc.partial_items), exc)
            own = exc.partial_items
        for item in own:
            if item.get("full_name"):
                collected[item["full_name"]] = normalize_repo(item)

        if include_starred:
            try:
                starred, _ = await client.paginate(
                    f"{GITHUB_API}/user/starred",
                    per_page=per_page,
                    max_pages=starred_max_pages,
                    phase="starred",
                    on_progress=on_progress,
                )
            except GitHubServiceError as exc:
                logger.warning("Starred 同步中断，使用已获取的 %d 条: %s", len(exc.partial_items), exc)
                starred = exc.partial_items
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
