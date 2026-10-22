"""收藏项目更新提醒（M7-04）：新版本 / 重大变更检测。

设计：
- `parse_version` / `classify_update` 为纯函数，便于测试；
- `scan_repositories` 从 GitHub 拉取最近 Release（无 Release 时回退 Tag），与本地
  `latest_release_tag` 对比；首次扫描只记录基线，不产生历史版本提醒；
- `push_updates_to_edge` 把事件回写 edge，由 edge 按仓库归属扇出到每个收藏用户。
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Iterable, Optional

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import MyRepository

logger = logging.getLogger(__name__)

DEFAULT_MAX_PER_RUN = 100
UPDATE_TYPE_RELEASE = "release"
UPDATE_TYPE_MAJOR = "major"

# 版本号：v1.2.3 / 1.2 / release-2.0.0；只取前三个数字段。
_VERSION_RE = re.compile(r"v?(\d+)(?:\.(\d+))?(?:\.(\d+))?")

# 命中即视为「重大变更」的关键词（大小写不敏感）。
MAJOR_KEYWORDS: tuple[str, ...] = (
    "breaking change",
    "breaking changes",
    "breaking-change",
    "breaking",
    "major release",
    "major version",
    "重大变更",
    "不兼容",
    "破坏性变更",
)

RepoReleaseFetcher = Callable[[str], Awaitable[Optional[list[dict[str, Any]]]]]


def utcnow() -> datetime:
    """与项目其他模块一致：无时区 UTC 时间。"""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.replace(microsecond=0).isoformat() + "Z"


def _parse_github_time(value: Any) -> datetime | None:
    """解析 GitHub ISO 时间；与 github_service 的解析口径保持一致。"""
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


def parse_version(tag: Any) -> tuple[int, ...] | None:
    """把 tag 归一为数字元组；无法识别返回 None。

    `v1.2.3` → (1, 2, 3)，`release-2.0` → (2, 0)，`nightly` → None。
    """
    if not isinstance(tag, str) or not tag.strip():
        return None
    match = _VERSION_RE.search(tag.strip().lower())
    if not match:
        return None
    return tuple(int(part) for part in match.groups() if part is not None)


def is_major_bump(previous_tag: Any, new_tag: Any) -> bool:
    """主版本号是否跃迁（如 v1.9.3 → v2.0.0）。"""
    previous = parse_version(previous_tag)
    current = parse_version(new_tag)
    if not previous or not current:
        return False
    return current[0] > previous[0]


def contains_breaking_change(title: Any, body: Any) -> bool:
    """标题 / 正文是否命中 breaking change 关键词。"""
    text = f"{title or ''}\n{body or ''}".lower()
    return any(keyword in text for keyword in MAJOR_KEYWORDS)


def classify_update(previous_tag: Any, new_tag: Any, title: Any = "", body: Any = "") -> str:
    """判定更新类型：主版本跃迁或 breaking 关键词 → major，否则 release。"""
    if is_major_bump(previous_tag, new_tag):
        return UPDATE_TYPE_MAJOR
    if contains_breaking_change(title, body):
        return UPDATE_TYPE_MAJOR
    return UPDATE_TYPE_RELEASE


def clean_release_body(body: Any, *, max_chars: int = 800) -> str:
    """压缩 Release 正文为适合通知展示的摘要。"""
    if not isinstance(body, str):
        return ""
    text = re.sub(r"```.*?```", " ", body, flags=re.S)
    text = re.sub(r"[#>*_`~\-]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_chars]


def select_latest_release(
    releases: Iterable[dict[str, Any]] | None,
    *,
    include_prerelease: bool = False,
) -> dict[str, Any] | None:
    """从 GitHub Release 列表中选择最新一条（跳过草稿 / 可选预发布）。"""
    candidates: list[dict[str, Any]] = []
    for item in releases or []:
        if not isinstance(item, dict):
            continue
        tag = str(item.get("tag_name") or "").strip()
        if not tag or item.get("draft"):
            continue
        if item.get("prerelease") and not include_prerelease:
            continue
        candidates.append(item)
    if not candidates:
        return None

    def sort_key(item: dict[str, Any]) -> tuple[datetime, tuple[int, ...]]:
        published = _parse_github_time(item.get("published_at"))
        version = parse_version(item.get("tag_name")) or ()
        return (published or datetime.min, version)

    return max(candidates, key=sort_key)


def _load_rows(
    db: Session,
    repo_ids: list[str] | None,
    limit: int,
) -> list[MyRepository]:
    """按 id 读取或选取最久未扫描的仓库。"""
    if not repo_ids:
        stmt = (
            select(MyRepository)
            .where(MyRepository.platform == "github")
            .order_by(
                MyRepository.latest_release_checked_at.asc(),
                MyRepository.stars.desc(),
            )
            .limit(limit)
        )
        return list(db.execute(stmt).scalars().all())

    rows: list[MyRepository] = []
    for start in range(0, len(repo_ids), 100):
        chunk = repo_ids[start : start + 100]
        stmt = select(MyRepository).where(MyRepository.id.in_(chunk))
        rows.extend(db.execute(stmt).scalars().all())
    return rows[:limit]


def _build_event(
    row: MyRepository,
    latest: dict[str, Any],
    *,
    previous_tag: str,
    detected_at: datetime,
) -> dict[str, Any]:
    """把 Release 转为 edge 契约（camelCase）。"""
    tag = str(latest.get("tag_name") or "").strip()
    title = str(latest.get("name") or tag).strip() or tag
    body = latest.get("body") or ""
    html_url = str(latest.get("html_url") or "").strip()
    if not html_url:
        html_url = f"https://github.com/{row.id}/releases/tag/{tag}"
    return {
        "repoId": row.id,
        "repoName": row.name or row.id.split("/")[-1],
        "repoUrl": row.html_url,
        "type": classify_update(previous_tag, tag, title, body),
        "version": tag,
        "title": title,
        "summary": clean_release_body(body),
        "url": html_url,
        "publishedAt": _iso(_parse_github_time(latest.get("published_at"))),
        "detectedAt": _iso(detected_at),
    }


async def scan_repositories(
    db: Session,
    repo_ids: list[str] | None = None,
    *,
    token: str = "",
    fetcher: RepoReleaseFetcher | None = None,
    include_prerelease: bool = False,
    max_count: int = DEFAULT_MAX_PER_RUN,
    now: datetime | None = None,
) -> dict[str, Any]:
    """扫描仓库的最新 Release，返回新增更新事件。

    `fetcher` 注入时优先使用（测试 / 自定义数据源）；否则用 GitHub Token 调 REST。
    首次扫描（`latest_release_tag` 为空）只记录基线，不生成事件。
    """
    current = now or utcnow()
    requested = (
        list(dict.fromkeys(str(item).strip() for item in repo_ids if str(item).strip()))
        if repo_ids
        else None
    )
    rows = _load_rows(db, requested, max(1, int(max_count)))
    checked = 0
    skipped = 0
    events: list[dict[str, Any]] = []

    for row in rows:
        try:
            if fetcher is not None:
                releases = await fetcher(row.id)
            elif token:
                from app.services.github_service import list_releases

                releases = await list_releases(token, row.id)
            else:
                releases = None
        except Exception:  # noqa: BLE001 - 单仓库失败不影响整批
            logger.warning("扫描仓库更新失败: %s", row.id, exc_info=True)
            releases = None

        row.latest_release_checked_at = current
        if releases is None:
            skipped += 1
            continue

        latest = select_latest_release(releases, include_prerelease=include_prerelease)
        if latest is None:
            skipped += 1
            continue

        tag = str(latest.get("tag_name") or "").strip()
        if not tag:
            skipped += 1
            continue

        previous_tag = row.latest_release_tag
        row.latest_release_tag = tag[:128]
        row.latest_release_name = str(latest.get("name") or tag)[:255]
        row.latest_release_url = str(
            latest.get("html_url") or f"https://github.com/{row.id}/releases/tag/{tag}"
        )
        row.latest_release_at = _parse_github_time(latest.get("published_at"))
        checked += 1

        if previous_tag and previous_tag != tag:
            events.append(
                _build_event(
                    row,
                    latest,
                    previous_tag=previous_tag,
                    detected_at=current,
                )
            )

    db.commit()
    return {"checked": checked, "skipped": skipped, "events": events}


async def push_updates_to_edge(
    events: list[dict[str, Any]],
    *,
    edge_base_url: str,
    internal_token: str = "",
    timeout: float = 15.0,
) -> dict[str, Any]:
    """把更新事件批量回写 edge；未配置或失败时返回结构化降级结果。"""
    base = (edge_base_url or "").strip().rstrip("/")
    if not base:
        return {"status": "skipped", "reason": "EDGE_BASE_URL 未配置"}
    if not events:
        return {"status": "skipped", "reason": "没有可回写的更新事件"}
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                f"{base}/api/internal/repo-updates/ingest",
                headers={"X-Internal-Token": internal_token or ""},
                json={"items": events},
            )
    except httpx.HTTPError as exc:
        logger.warning("更新提醒回写 edge 失败: %s", exc)
        return {"status": "error", "error": str(exc)[:300]}
    if resp.status_code >= 400:
        return {"status": "error", "httpStatus": resp.status_code}
    try:
        body = resp.json()
    except ValueError:
        body = {}
    return {
        "status": "ok",
        "created": int(body.get("created") or 0),
        "skipped": int(body.get("skipped") or 0),
    }


async def scan_and_push(
    db: Session,
    repo_ids: list[str] | None = None,
    *,
    token: str = "",
    fetcher: RepoReleaseFetcher | None = None,
    include_prerelease: bool = False,
    max_count: int = DEFAULT_MAX_PER_RUN,
    now: datetime | None = None,
    edge_base_url: str = "",
    internal_token: str = "",
) -> dict[str, Any]:
    """扫描 + 回写 edge，返回任务可序列化的摘要。"""
    result = await scan_repositories(
        db,
        repo_ids,
        token=token,
        fetcher=fetcher,
        include_prerelease=include_prerelease,
        max_count=max_count,
        now=now,
    )
    events = result.pop("events", [])
    result["edge"] = await push_updates_to_edge(
        events,
        edge_base_url=edge_base_url,
        internal_token=internal_token,
    )
    result["events"] = len(events)
    return result
