"""热榜抓取：GitHub Trending（主）+ Gitee 探索页（尽力而为）。

- `parse_trending_html` 为纯函数，便于离线单测；对页面结构变化容错，缺字段不崩溃；
- `crawl_github_trending` / `crawl_gitee_explore` 为异步抓取入口，网络失败返回空列表并记录日志。
"""
from __future__ import annotations

import logging
import re
from datetime import date
from typing import Any, Optional

import httpx
from bs4 import BeautifulSoup, Tag

logger = logging.getLogger(__name__)

GITHUB_TRENDING_URL = "https://github.com/trending"
GITEE_EXPLORE_URL = "https://gitee.com/explore"
USER_AGENT = "Mozilla/5.0 (compatible; OpenFactoryBot/1.0)"
_TIMEOUT = httpx.Timeout(30.0, connect=10.0)

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


async def crawl_github_trending(language: str | None = None) -> list[dict[str, Any]]:
    """抓取 GitHub Trending 页面并解析；网络失败返回空列表。"""
    url = GITHUB_TRENDING_URL
    if language:
        url = f"{GITHUB_TRENDING_URL}/{language.strip().lower()}"
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
            resp = await client.get(
                url,
                headers={"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"},
            )
        if resp.status_code != 200:
            logger.warning("GitHub Trending 返回 %s: %s", resp.status_code, url)
            return []
        items = parse_trending_html(resp.text)
    except httpx.HTTPError as exc:
        logger.warning("GitHub Trending 抓取失败: %s", exc)
        return []

    today = date.today().isoformat()
    for item in items:
        item["crawled_at"] = today
    return items


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
