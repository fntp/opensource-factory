"""Bark 推送通道（M4-03）。

职责：

- 把每日进入 `pushed` 状态的推荐转换成中文 Bark 消息；
- 通过 Bark HTTP API（`POST {server}/push`）投递，支持自建服务；
- 以 `recommendations.bark_sent_at` / `bark_error` 做最小幂等与失败可观测；
- 未配置、网络失败、Bark 返回异常时一律降级为结构化结果，不阻塞主流程。

本模块不访问网络以外的外部依赖；测试通过 `httpx.MockTransport` 注入，
不会发起真实请求。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.models import MyRepository, Recommendation, TrendingRepository
from app.services.push_records import (
    create_delivery,
    finish_delivery,
    record_delivery,
)

logger = logging.getLogger(__name__)

MAX_TITLE_LENGTH = 80
MAX_BODY_LENGTH = 600
MAX_ERROR_LENGTH = 300
MAX_BATCH_LIMIT = 100
VALID_LEVELS = ("active", "timeSensitive", "passive", "critical")
_LEVEL_ALIASES = {
    "active": "active",
    "timesensitive": "timeSensitive",
    "time-sensitive": "timeSensitive",
    "passive": "passive",
    "critical": "critical",
}


class BarkConfigError(ValueError):
    """Bark 通道未启用或缺少必要配置。"""


@dataclass(frozen=True)
class BarkMessage:
    """一条待投递的 Bark 消息。"""

    title: str
    body: str
    url: Optional[str] = None
    group: Optional[str] = None
    sound: Optional[str] = None
    icon: Optional[str] = None
    level: Optional[str] = None


@dataclass(frozen=True)
class BarkResult:
    """一次 Bark 投递的结果。"""

    ok: bool
    status_code: Optional[int] = None
    code: Optional[int] = None
    message: Optional[str] = None
    error: Optional[str] = None


def _utcnow() -> datetime:
    """统一使用无时区 UTC 时间（与模型默认值一致）。"""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def truncate_text(value: Any, limit: int) -> str:
    """去除首尾空白并按字符数截断。"""
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def normalize_server_url(raw: Optional[str]) -> str:
    """归一化 Bark 服务地址：去空白、去尾部斜杠、缺省协议补 https。"""
    value = str(raw or "").strip()
    if not value:
        return "https://api.day.app"
    if not value.startswith(("http://", "https://")):
        value = f"https://{value}"
    return value.rstrip("/")


def normalize_level(raw: Optional[str]) -> str:
    """归一化 Bark 级别，未知值回退 active。"""
    key = str(raw or "").strip().lower().replace("_", "-")
    return _LEVEL_ALIASES.get(key, "active")


def build_bark_payload(message: BarkMessage, settings: Settings) -> dict[str, Any]:
    """构建 Bark `POST /push` 的 JSON 请求体。"""
    payload: dict[str, Any] = {
        "device_key": str(settings.BARK_DEVICE_KEY or "").strip(),
        "title": truncate_text(message.title, MAX_TITLE_LENGTH) or "OpenFactory",
        "body": truncate_text(message.body, MAX_BODY_LENGTH) or "为你推荐的开源项目",
        "group": (message.group or settings.BARK_GROUP or "OpenFactory").strip(),
        "level": normalize_level(message.level or settings.BARK_LEVEL),
    }
    url = str(message.url or "").strip()
    if url:
        payload["url"] = url
    sound = (message.sound or settings.BARK_SOUND or "").strip()
    if sound:
        payload["sound"] = sound
    icon = (message.icon or settings.BARK_ICON or "").strip()
    if icon:
        payload["icon"] = icon
    return payload


def _repo_meta(repo: Any) -> dict[str, Any]:
    """从收藏库 / 热榜行提取展示字段（两种模型字段不完全一致）。"""
    if repo is None:
        return {}
    stars = getattr(repo, "stars", None)
    if stars is None:
        stars = getattr(repo, "stars_today", None)
    return {
        "name": getattr(repo, "name", None) or "",
        "description": getattr(repo, "description", None) or "",
        "html_url": getattr(repo, "html_url", None) or "",
        "language": getattr(repo, "language", None) or "",
        "stars": int(stars or 0),
        "stars_today": int(getattr(repo, "stars_today", 0) or 0),
    }


def format_recommendation_message(
    recommendation: Recommendation,
    repo: Any,
    settings: Optional[Settings] = None,
) -> BarkMessage:
    """把一条推荐转换成中文 Bark 消息。

    标题优先 `owner/name`；正文依次为项目简介、推荐理由、匹配度 / 语言 / Star 元信息。
    """
    cfg = settings or get_settings()
    meta = _repo_meta(repo)
    repo_id = str(recommendation.repo_id or "").strip()
    title = repo_id or meta["name"] or "为你推荐的开源项目"

    lines: list[str] = []
    description = str(meta["description"] or "").strip()
    reason = str(recommendation.reason or "").strip()
    if description:
        lines.append(description)
    if reason and reason != description:
        lines.append(reason)

    facts: list[str] = []
    match_score = float(recommendation.match_score or recommendation.score or 0.0)
    if match_score > 0:
        facts.append(f"匹配度 {round(match_score * 100)}%")
    if meta["language"]:
        facts.append(str(meta["language"]))
    if meta["stars_today"] > 0:
        facts.append(f"今日 +{meta['stars_today']}")
    elif meta["stars"] > 0:
        facts.append(f"⭐ {meta['stars']}")
    if facts:
        lines.append(" · ".join(facts))

    body = "\n".join(lines) or "为你推荐的开源项目"
    url = meta["html_url"] or (
        f"https://github.com/{repo_id}" if "/" in repo_id else ""
    )
    return BarkMessage(
        title=title,
        body=body,
        url=url or None,
        group=cfg.BARK_GROUP or "OpenFactory",
        level=cfg.BARK_LEVEL or "active",
    )


class BarkClient:
    """Bark HTTP 客户端（同步，便于 Celery 任务直接使用）。"""

    def __init__(
        self,
        settings: Optional[Settings] = None,
        *,
        transport: Optional[httpx.BaseTransport] = None,
    ) -> None:
        self.settings = settings or get_settings()
        self._transport = transport
        self._client: Optional[httpx.Client] = None

    @property
    def endpoint(self) -> str:
        return f"{normalize_server_url(self.settings.BARK_SERVER_URL)}/push"

    def _get_client(self) -> httpx.Client:
        if self._client is None:
            kwargs: dict[str, Any] = {
                "timeout": max(1.0, float(self.settings.BARK_TIMEOUT_SECONDS or 10.0))
            }
            if self._transport is not None:
                kwargs["transport"] = self._transport
            self._client = httpx.Client(**kwargs)
        return self._client

    def send(self, message: BarkMessage) -> BarkResult:
        """发送一条消息；所有异常都转成 `BarkResult(ok=False)`。"""
        payload = build_bark_payload(message, self.settings)
        if not payload.get("device_key"):
            return BarkResult(ok=False, error="BARK_DEVICE_KEY 未配置")
        try:
            response = self._get_client().post(self.endpoint, json=payload)
        except Exception as exc:  # noqa: BLE001 - 网络 / URL 异常统一降级为失败结果
            return BarkResult(
                ok=False,
                error=f"请求失败：{type(exc).__name__}: {truncate_text(exc, 200)}",
            )

        data: dict[str, Any] = {}
        try:
            parsed = response.json()
            if isinstance(parsed, dict):
                data = parsed
        except ValueError:
            data = {}

        code: Optional[int] = None
        raw_code = data.get("code")
        if raw_code is not None:
            try:
                code = int(raw_code)
            except (TypeError, ValueError):
                code = None
        message_text = str(data.get("message") or "").strip()

        if response.status_code >= 400:
            detail = message_text or response.reason_phrase or "HTTP 错误"
            return BarkResult(
                ok=False,
                status_code=response.status_code,
                code=code,
                message=message_text or None,
                error=f"HTTP {response.status_code}: {truncate_text(detail, 200)}",
            )
        if code is not None and code != 200:
            detail = message_text or "Bark 返回失败"
            return BarkResult(
                ok=False,
                status_code=response.status_code,
                code=code,
                message=message_text or None,
                error=f"Bark code={code}: {truncate_text(detail, 200)}",
            )
        return BarkResult(
            ok=True,
            status_code=response.status_code,
            code=code,
            message=message_text or None,
        )

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    def __enter__(self) -> "BarkClient":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()


def send_bark_test(
    *,
    title: Optional[str] = None,
    body: Optional[str] = None,
    url: Optional[str] = None,
    settings: Optional[Settings] = None,
    client: Optional[BarkClient] = None,
    db: Optional[Session] = None,
) -> BarkResult:
    """发送一条测试通知；未启用 / 未配置时抛出 `BarkConfigError`。"""
    cfg = settings or get_settings()
    if not bool(cfg.BARK_ENABLED):
        raise BarkConfigError("BARK_ENABLED 未开启")
    if not str(cfg.BARK_DEVICE_KEY or "").strip():
        raise BarkConfigError("BARK_DEVICE_KEY 未配置")

    message = BarkMessage(
        title=title or "OpenFactory 测试通知",
        body=body or "Bark 通道配置成功，后续推荐会推送到这里。",
        url=url or None,
        group=cfg.BARK_GROUP or "OpenFactory",
        level=cfg.BARK_LEVEL or "active",
    )
    bark = client or BarkClient(cfg)
    try:
        result = bark.send(message)
    except Exception as exc:  # noqa: BLE001 - 记录失败后继续向上抛
        if db is not None:
            record_delivery(
                db,
                channel="bark",
                kind="test",
                target=cfg.BARK_GROUP or "OpenFactory",
                target_type="group",
                ok=False,
                subject=message.title,
                error=f"发送异常：{type(exc).__name__}: {truncate_text(exc, 200)}",
            )
        raise
    finally:
        if client is None:
            bark.close()
    if db is not None:
        record_delivery(
            db,
            channel="bark",
            kind="test",
            target=cfg.BARK_GROUP or "OpenFactory",
            target_type="group",
            ok=result.ok,
            subject=message.title,
            error=result.error,
        )
    return result


def _count(db: Session, *conditions: Any) -> int:
    stmt = select(func.count()).select_from(Recommendation).where(*conditions)
    return int(db.execute(stmt).scalar() or 0)


def bark_status(db: Session, settings: Optional[Settings] = None) -> dict[str, Any]:
    """通道状态：不返回 device key，只暴露是否已配置与投递计数。"""
    cfg = settings or get_settings()
    pushed = Recommendation.status == "pushed"
    pending = _count(db, pushed, Recommendation.bark_sent_at.is_(None))
    sent = _count(db, pushed, Recommendation.bark_sent_at.is_not(None))
    failed = _count(
        db,
        pushed,
        Recommendation.bark_sent_at.is_(None),
        Recommendation.bark_error.is_not(None),
    )
    last_error = db.execute(
        select(Recommendation.bark_error)
        .where(Recommendation.bark_error.is_not(None))
        .order_by(Recommendation.created_at.desc())
        .limit(1)
    ).scalar()
    last_sent_at = db.execute(
        select(func.max(Recommendation.bark_sent_at))
    ).scalar()
    return {
        "enabled": bool(cfg.BARK_ENABLED),
        "configured": bool(str(cfg.BARK_DEVICE_KEY or "").strip()),
        "serverUrl": normalize_server_url(cfg.BARK_SERVER_URL),
        "group": cfg.BARK_GROUP or "OpenFactory",
        "level": normalize_level(cfg.BARK_LEVEL),
        "maxPerRun": max(1, int(cfg.BARK_MAX_PER_RUN or 5)),
        "dryRun": bool(cfg.BARK_DRY_RUN),
        "pending": pending,
        "sent": sent,
        "failed": failed,
        "lastError": truncate_text(last_error, MAX_ERROR_LENGTH) if last_error else None,
        "lastSentAt": last_sent_at,
    }


def dispatch_bark_notifications(
    db: Session,
    *,
    user_id: Optional[str] = None,
    limit: Optional[int] = None,
    settings: Optional[Settings] = None,
    client: Optional[BarkClient] = None,
) -> dict[str, Any]:
    """把 `pushed` 且未投递的推荐逐条推送到 Bark。

    返回结构化统计；单条失败不会中断后续投递，失败原因写入 `bark_error`，
    成功则写入 `bark_sent_at` 并清空错误，等待下次任务重试失败项。
    """
    cfg = settings or get_settings()
    if not bool(cfg.BARK_ENABLED):
        return {"status": "skipped", "reason": "BARK_ENABLED 未开启", "sent": 0, "failed": 0}
    if not str(cfg.BARK_DEVICE_KEY or "").strip():
        return {
            "status": "skipped",
            "reason": "BARK_DEVICE_KEY 未配置",
            "sent": 0,
            "failed": 0,
        }

    max_per_run = int(limit or cfg.BARK_MAX_PER_RUN or 5)
    max_per_run = max(1, min(max_per_run, MAX_BATCH_LIMIT))

    stmt = select(Recommendation).where(
        Recommendation.status == "pushed",
        Recommendation.bark_sent_at.is_(None),
    )
    if user_id:
        stmt = stmt.where(Recommendation.user_id == user_id)
    stmt = (
        stmt.order_by(
            Recommendation.quality_score.desc(),
            Recommendation.score.desc(),
            Recommendation.created_at.asc(),
        )
        .limit(max_per_run)
    )
    rows = list(db.execute(stmt).scalars().all())

    stats: dict[str, Any] = {
        "status": "ok",
        "candidates": len(rows),
        "sent": 0,
        "failed": 0,
        "skipped": 0,
        "dryRun": bool(cfg.BARK_DRY_RUN),
        "errors": [],
        "previews": [],
        "deliveryIds": [],
    }
    if not rows:
        return stats

    bark = client or BarkClient(cfg)
    try:
        for row in rows:
            try:
                repo = db.get(TrendingRepository, row.repo_id) or db.get(
                    MyRepository, row.repo_id
                )
                message = format_recommendation_message(row, repo, cfg)
            except Exception as exc:  # noqa: BLE001 - 单条数据异常不阻塞整批
                row.bark_error = truncate_text(
                    f"构建消息失败：{type(exc).__name__}: {exc}", MAX_ERROR_LENGTH
                )
                record = record_delivery(
                    db,
                    channel="bark",
                    kind="single",
                    target=cfg.BARK_GROUP or "OpenFactory",
                    target_type="group",
                    ok=False,
                    item_count=1,
                    dedupe_key=f"bark:{row.id}",
                    source_id=row.id,
                    user_id=row.user_id,
                    error=row.bark_error,
                )
                stats["deliveryIds"].append(record.id)
                stats["failed"] += 1
                stats["errors"].append(
                    {"recommendationId": row.id, "error": row.bark_error}
                )
                db.commit()
                continue

            if cfg.BARK_DRY_RUN:
                record = create_delivery(
                    db,
                    channel="bark",
                    kind="single",
                    target=cfg.BARK_GROUP or "OpenFactory",
                    target_type="group",
                    status="skipped",
                    item_count=1,
                    subject=message.title,
                    dedupe_key=f"bark:{row.id}",
                    source_id=row.id,
                    user_id=row.user_id,
                    error="dry_run",
                )
                stats["deliveryIds"].append(record.id)
                stats["skipped"] += 1
                stats["previews"].append(
                    {
                        "recommendationId": row.id,
                        "repoId": row.repo_id,
                        "title": message.title,
                        "body": message.body,
                        "url": message.url,
                    }
                )
                continue

            record = create_delivery(
                db,
                channel="bark",
                kind="single",
                target=cfg.BARK_GROUP or "OpenFactory",
                target_type="group",
                status="pending",
                item_count=1,
                subject=message.title,
                dedupe_key=f"bark:{row.id}",
                source_id=row.id,
                user_id=row.user_id,
            )
            stats["deliveryIds"].append(record.id)
            try:
                result = bark.send(message)
            except Exception as exc:  # noqa: BLE001 - 客户端异常同样降级为失败
                result = BarkResult(
                    ok=False,
                    error=f"发送异常：{type(exc).__name__}: {truncate_text(exc, 200)}",
                )
            if result.ok:
                row.bark_sent_at = _utcnow()
                row.bark_error = None
                finish_delivery(db, record, status="sent")
                stats["sent"] += 1
            else:
                row.bark_error = truncate_text(result.error or "未知错误", MAX_ERROR_LENGTH)
                finish_delivery(
                    db, record, status="failed", error=row.bark_error
                )
                stats["failed"] += 1
                stats["errors"].append(
                    {"recommendationId": row.id, "error": row.bark_error}
                )
            db.commit()
    finally:
        if client is None:
            bark.close()

    if stats["dryRun"]:
        stats["status"] = "dry_run"
    elif stats["failed"]:
        stats["status"] = "partial" if stats["sent"] else "error"
    logger.info(
        "Bark 投递完成: status=%s candidates=%d sent=%d failed=%d skipped=%d",
        stats["status"],
        stats["candidates"],
        stats["sent"],
        stats["failed"],
        stats["skipped"],
    )
    return stats
