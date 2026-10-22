"""热榜抓取：GitHub Trending（主）+ Gitee 探索页（尽力而为）。

- `parse_trending_html` 为纯函数，便于离线单测；对页面结构变化容错，缺字段不崩溃；
- `crawl_github_trending_pages` 顺序抓取「全局页 + 多语言页」，按仓库去重合并，
  单页失败只记录、不中断整轮（页面级统计供 M2-02 告警使用）；
- `crawl_gitee_explore` 为尽力而为入口，网络失败返回空列表并记录日志。
"""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import date
from typing import Any, Optional, Sequence
from urllib.parse import quote

import httpx
from bs4 import BeautifulSoup, Tag

logger = logging.getLogger(__name__)

GITHUB_TRENDING_URL = "https://github.com/trending"
GITEE_EXPLORE_URL = "https://gitee.com/explore"
USER_AGENT = "Mozilla/5.0 (compatible; OpenFactoryBot/1.0)"
_TIMEOUT = httpx.Timeout(30.0, connect=10.0)
TRENDING_SINCE_VALUES = ("daily", "weekly", "monthly")

# 默认抓取的语言页（GitHub Trending 的 language slug）；可用 TRENDING_LANGUAGES 覆盖。
DEFAULT_TRENDING_LANGUAGES: tuple[str, ...] = (
    "python",
    "javascript",
    "typescript",
    "go",
    "rust",
    "java",
    "cpp",
    "c",
    "php",
    "ruby",
    "swift",
    "kotlin",
)

# GitHub 页面对部分语言使用缩写 slug，入库时换成可读名称。
_LANGUAGE_DISPLAY_NAMES = {
    "cpp": "C++",
    "csharp": "C#",
    "objective-c": "Objective-C",
    "jupyter-notebook": "Jupyter Notebook",
    "html": "HTML",
    "css": "CSS",
}

_STARS_TODAY_TEXT_RE = re.compile(r"([\d,]+)\s+stars?\s+today", re.IGNORECASE)
_NUMBER_RE = re.compile(r"[\d,]+")


def _text(node: Optional[Tag]) -> str:
    """安全取节点文本（None 返回空串）。"""
    if node is None:
        return ""
    return node.get_text(" ", strip=True)


def _parse_int(text: str) -> int:
    """从文本中提取第一个整数（支持千分位逗号）。"""
    match = _NUMBER_RE.search(text or "")
    if not match:
        return 0
    try:
        return int(match.group(0).replace(",", ""))
    except ValueError:
        return 0


def _display_language(slug: str) -> str:
    """把 Trending 页语言 slug 转成可读名称（未知 slug 首字母大写）。"""
    return _LANGUAGE_DISPLAY_NAMES.get(slug, slug.replace("-", " ").title())


def normalize_languages(value: str | Sequence[str] | None) -> list[str]:
    """归一化语言列表：支持 CSV / 序列，去空、去重、转小写。"""
    if value is None:
        return []
    raw_parts: Sequence[str] = value.split(",") if isinstance(value, str) else value
    result: list[str] = []
    for part in raw_parts:
        slug = str(part).strip().lower()
        if slug and slug not in result:
            result.append(slug)
    return result


def build_trending_url(language: str | None = None, since: str = "daily") -> str:
    """生成 Trending 页面 URL；`since` 非法时回退 daily。"""
    window = (since or "daily").strip().lower()
    if window not in TRENDING_SINCE_VALUES:
        window = "daily"
    url = GITHUB_TRENDING_URL
    slug = (language or "").strip().lower()
    if slug:
        url = f"{GITHUB_TRENDING_URL}/{quote(slug, safe='')}"
    return f"{url}?since={window}"


def _parse_github_row(row: Tag) -> Optional[dict[str, Any]]:
    """解析单条 Trending 行；字段缺失或结构异常时返回 None。"""
    link = row.select_one("h2 a[href]") or row.find("a", href=True)
    if link is None or not link.get("href"):
        return None
    href = str(link["href"]).strip()
    full_name = href.split("?", 1)[0].strip("/")
    if full_name.count("/") != 1:  # 必须是 "owner/repo"
        return None
    owner, name = full_name.split("/", 1)
    if not owner or not name:
        return None

    # 描述：优先 p.col-9，回退任意 <p>
    description = _text(row.select_one("p.col-9") or row.select_one("p"))

    # 语言：span[itemprop="programmingLanguage"]，回退 [itemprop="programmingLanguage"]
    language = _text(row.select_one('[itemprop="programmingLanguage"]'))

    # 今日新增 Star：span.d-inline-block.float-sm-right（"1,234 stars today"），回退正则全文匹配
    stars_today = 0
    for selector in ("span.d-inline-block.float-sm-right", "span.float-sm-right"):
        node = row.select_one(selector)
        if node is not None:
            text = _text(node)
            if "star" in text.lower():
                stars_today = _parse_int(text)
                break
    if stars_today == 0:
        match = _STARS_TODAY_TEXT_RE.search(row.get_text(" ", strip=True))
        if match:
            stars_today = _parse_int(match.group(1))

    # 总 Star：stargazers 链接文本，回退全文 "total stars" 匹配
    total_stars = 0
    star_link = row.select_one('a[href$="/stargazers"]')
    if star_link is not None:
        total_stars = _parse_int(_text(star_link))

    return {
        "id": full_name,
        "platform": "github",
        "owner": owner,
        "name": name,
        "html_url": f"https://github.com/{full_name}",
        "description": description,
        "language": language,
        "stars_today": stars_today,
        "stars": total_stars,
    }


def parse_trending_html(html: str) -> list[dict[str, Any]]:
    """解析 github.com/trending 页面 HTML，返回标准化条目列表。

    纯函数、对标记变化容错：优先 `article.Box-row`，回退所有 `article`；
    单行解析失败仅跳过该行，绝不抛出异常。
    """
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    rows = soup.select("article.Box-row") or soup.select("article")
    results: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        try:
            item = _parse_github_row(row)
        except Exception as exc:  # noqa: BLE001 - 单行解析失败不影响整体
            logger.debug("解析 Trending 行失败: %s", exc)
            continue
        if item and item["id"] not in seen:
            seen.add(item["id"])
            results.append(item)
    return results


async def _fetch_github_trending_page(
    client: httpx.AsyncClient,
    language: str | None,
    since: str,
) -> tuple[list[dict[str, Any]], Optional[str]]:
    """抓取并解析单个 Trending 页面，返回 (items, error)；失败不抛异常。"""
    url = build_trending_url(language=language, since=since)
    try:
        resp = await client.get(
            url,
            headers={"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"},
        )
    except httpx.HTTPError as exc:
        logger.warning("GitHub Trending 抓取失败 %s: %s", url, exc)
        return [], f"{type(exc).__name__}: {exc}"

    if resp.status_code != 200:
        logger.warning("GitHub Trending 返回 %s: %s", resp.status_code, url)
        return [], f"HTTP {resp.status_code}"

    try:
        items = parse_trending_html(resp.text)
    except Exception as exc:  # noqa: BLE001 - 解析异常按页面失败降级
        logger.warning("GitHub Trending 解析失败 %s: %s", url, exc)
        return [], f"parse error: {exc}"

    display = _display_language(language) if language else ""
    today = date.today().isoformat()
    for item in items:
        if not item.get("language") and display:
            item["language"] = display
        item["trending_page"] = language or "all"
        item["crawled_at"] = today
    return items, None


async def crawl_github_trending(
    language: str | None = None,
    since: str = "daily",
    *,
    client: httpx.AsyncClient | None = None,
) -> list[dict[str, Any]]:
    """抓取单个 GitHub Trending 页面并解析；网络失败返回空列表。"""
    owns_client = client is None
    if client is None:
        client = httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True)
    try:
        items, _error = await _fetch_github_trending_page(client, language=language, since=since)
        return items
    finally:
        if owns_client:
            await client.aclose()


def merge_trending_items(
    page_items: Sequence[tuple[str, Sequence[dict[str, Any]]]],
) -> list[dict[str, Any]]:
    """按仓库 id 合并多语言页结果：字段互补、数值取大、记录来源页。

    `page_items` 为 `[(language_slug_or_all, items), ...]`；返回保持首次出现顺序。
    """
    merged: dict[str, dict[str, Any]] = {}
    for page, items in page_items:
        for raw in items:
            repo_id = str(raw.get("id") or "").strip()
            if not repo_id:
                continue
            item = dict(raw)
            item["id"] = repo_id
            item.setdefault("trending_pages", [])
            pages = item["trending_pages"]
            if page not in pages:
                pages.append(page)

            existing = merged.get(repo_id)
            if existing is None:
                merged[repo_id] = item
                continue

            # 描述取更长的一份；空字段互补
            if len(item.get("description") or "") > len(existing.get("description") or ""):
                existing["description"] = item.get("description") or ""
            for key in ("platform", "owner", "name", "html_url", "language", "crawled_at"):
                if not existing.get(key) and item.get(key):
                    existing[key] = item[key]
            existing["stars"] = max(int(existing.get("stars") or 0), int(item.get("stars") or 0))
            existing["stars_today"] = max(
                int(existing.get("stars_today") or 0), int(item.get("stars_today") or 0)
            )
            for page_name in item.get("trending_pages") or []:
                if page_name not in existing["trending_pages"]:
                    existing["trending_pages"].append(page_name)
    return list(merged.values())


async def crawl_github_trending_pages(
    languages: str | Sequence[str] | None = None,
    since: str = "daily",
    *,
    include_global: bool = True,
    client: httpx.AsyncClient | None = None,
    delay_seconds: float = 1.0,
) -> dict[str, Any]:
    """抓取「全局页 + 多语言页」，返回条目与页面级统计。

    - `include_global=False` 时只抓 `languages` 指定的页面；
    - 顺序请求，页间默认等待 `delay_seconds` 秒，避免触发 GitHub 限流；
    - 单页失败仅记录到 `pages[].error` 与 `failedPages`，不影响其他页面；
    - 返回 `{"items": [...], "pages": [...], "failedPages": [...]}`。
    """
    slugs = normalize_languages(languages)
    page_specs: list[str | None] = ([None] if include_global else []) + slugs
    collected: list[tuple[str, list[dict[str, Any]]]] = []
    pages: list[dict[str, Any]] = []

    owns_client = client is None
    if client is None:
        client = httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True)
    try:
        for index, language in enumerate(page_specs):
            items, error = await _fetch_github_trending_page(client, language=language, since=since)
            page_name = language or "all"
            collected.append((page_name, items))
            pages.append(
                {
                    "language": page_name,
                    "url": build_trending_url(language=language, since=since),
                    "count": len(items),
                    "ok": error is None,
                    "error": error,
                }
            )
            if delay_seconds > 0 and index < len(page_specs) - 1:
                await asyncio.sleep(delay_seconds)
    finally:
        if owns_client:
            await client.aclose()

    merged = merge_trending_items(collected)
    failed_pages = [page for page in pages if not page["ok"]]
    logger.info(
        "GitHub Trending 多页抓取完成: %d 页（失败 %d），去重后 %d 条",
        len(pages),
        len(failed_pages),
        len(merged),
    )
    return {"items": merged, "pages": pages, "failedPages": failed_pages}


async def crawl_gitee_explore() -> list[dict[str, Any]]:
    """尽力而为地抓取 Gitee 探索页（结构多变，失败返回空列表）。"""
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
            resp = await client.get(
                GITEE_EXPLORE_URL,
                headers={"User-Agent": USER_AGENT, "Accept-Language": "zh-CN,zh;q=0.9"},
            )
        if resp.status_code != 200:
            logger.warning("Gitee 探索页返回 %s", resp.status_code)
            return []
    except httpx.HTTPError as exc:
        logger.warning("Gitee 探索页抓取失败: %s", exc)
        return []

    results: list[dict[str, Any]] = []
    seen: set[str] = set()
    try:
        soup = BeautifulSoup(resp.text, "html.parser")
        # 多组候选选择器，覆盖探索页常见卡片结构
        cards = soup.select(
            "div.explore-trending, div.explore-repo__list div.item, div.ui.card, div.item"
        )
        for card in cards:
            try:
                link = card.select_one("a.title[href]") or card.select_one("a[href]")
                if link is None or not link.get("href"):
                    continue
                href = str(link["href"]).split("?", 1)[0].strip("/")
                if href.count("/") != 1:
                    continue
                owner, name = href.split("/", 1)
                if not owner or not name or owner in {"explore", "login", "help", "users"}:
                    continue
                full_name = f"{owner}/{name}"
                if full_name in seen:
                    continue
                seen.add(full_name)
                description = _text(card.select_one("div.description") or card.select_one("p"))
                language = _text(card.select_one("span.language") or card.select_one('[itemprop="programmingLanguage"]'))
                results.append(
                    {
                        "id": full_name,
                        "platform": "gitee",
                        "owner": owner,
                        "name": name,
                        "html_url": f"https://gitee.com/{full_name}",
                        "description": description,
                        "language": language,
                        "stars_today": 0,
                        "stars": 0,
                    }
                )
            except Exception as exc:  # noqa: BLE001 - 单卡片解析失败仅跳过
                logger.debug("解析 Gitee 卡片失败: %s", exc)
                continue
    except Exception as exc:  # noqa: BLE001 - 页面结构整体异常时返回空列表
        logger.warning("解析 Gitee 探索页失败: %s", exc)
        return []

    today = date.today().isoformat()
    for item in results:
        item["crawled_at"] = today
    return results
