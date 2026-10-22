"""Telegram 推送通道（M4-04）。

职责：

- 把每日评估后进入 `pushed` 的高质量推荐生成中文摘要，通过 Telegram Bot API 下发；
- 处理 HTML 转义、4096 字符分片、超时 / 429 / 5xx 指数退避重试；
- 记录每次发送结果到 `telegram_deliveries`，提供最小幂等（同一天同一会话不重复发送）；
- 未启用 / 未配置 / 无数据时返回结构化状态，不访问网络、不误报失败。

安全约束：Bot Token 只在内部拼接请求 URL，日志与错误信息一律脱敏；
状态接口不返回 token，chat id 只返回末四位。
"""
from __future__ import annotations

import html
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional, Sequence
from uuid import uuid4

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.models import Recommendation, TelegramDelivery, TrendingRepository

logger = logging.getLogger(__name__)

# Telegram Bot API 单条消息上限；摘要按 3800 字符打包，留出转义与标签余量
MAX_MESSAGE_CHARS = 4096
DIGEST_TARGET_CHARS = 3800
MAX_REASON_CHARS = 180
DEFAULT_TEST_TEXT = "OpenFactory Telegram 通道连通性测试 ✅"


class TelegramError(RuntimeError):
    """Telegram 发送失败（message 已脱敏）。"""

    def __init__(
        self,
        message: str,
        *,
        status_code: int = 0,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.retryable = retryable


class TelegramNotConfigured(TelegramError):
    """未配置 Bot Token 或 Chat ID。"""


@dataclass(frozen=True)
class DigestItem:
    """一条摘要条目（已从推荐 + 仓库元数据拼装）。"""

    repo_id: str
    title: str
    url: str
    reason: str
    match_score: float
    quality_score: float
    stars_today: int
    tech_stack: str


@dataclass(frozen=True)
class TelegramSendResult:
    """一次发送结果。"""

    message_ids: list[str]
    parts: int


def _utcnow() -> datetime:
    """统一使用无时区 UTC 时间（与模型默认值一致）。"""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _normalize_now(now: Optional[datetime]) -> datetime:
    """把注入时间统一为无时区 UTC；未提供时取当前 UTC。"""
    if now is None:
        return _utcnow()
    if now.tzinfo is not None:
        return now.astimezone(timezone.utc).replace(tzinfo=None)
    return now


def _escape(value: Any) -> str:
    """HTML 转义（含引号，避免 href 属性被截断）。"""
    return html.escape(str(value or ""), quote=True)


def _clean_text(value: Any, limit: Optional[int] = None) -> str:
    """压缩空白并按需截断，避免消息里出现大段换行 / 超长理由。"""
    text = " ".join(str(value or "").split())
    if limit and len(text) > limit:
        return text[: max(1, limit - 1)].rstrip() + "…"
    return text


def mask_chat_id(chat_id: str) -> str:
    """脱敏 chat id：只保留末四位。"""
    value = str(chat_id or "").strip()
    if not value:
        return ""
    return f"***{value[-4:]}" if len(value) > 4 else "***"


def split_text(text: str, limit: int = MAX_MESSAGE_CHARS) -> list[str]:
    """把纯文本按行安全拆分为不超过 limit 的片段。

    优先在换行处拆分；单行超长时按字符硬切（摘要走 build_digest_messages，
    不会触发硬切，因此不会截断 HTML 标签）。
    """
    value = str(text or "").strip()
    if not value:
        return []
    if len(value) <= limit:
        return [value]

    parts: list[str] = []
    current = ""
    for line in value.splitlines():
        candidate = line if not current else f"{current}\n{line}"
        if len(candidate) <= limit:
            current = candidate
            continue
        if current:
            parts.append(current)
            current = ""
        while len(line) > limit:
            parts.append(line[:limit])
            line = line[limit:]
        current = line
    if current:
        parts.append(current)
    return parts


def format_percent(score: Any) -> str:
    """把 0~1 分数格式化为百分比整数。"""
    try:
        number = float(score)
    except (TypeError, ValueError):
        number = 0.0
    number = max(0.0, min(1.0, number))
    return f"{round(number * 100)}%"


def build_item_block(index: int, item: DigestItem) -> str:
    """生成单条推荐的 HTML 区块（自包含，不跨消息拆分）。"""
    title = _escape(item.title or item.repo_id)
    lines = [f"<b>{index}. {title}</b>"]

    meta = [f"匹配度 {format_percent(item.match_score)}"]
    if item.quality_score:
        meta.append(f"质量分 {item.quality_score:.2f}")
    if item.stars_today:
        meta.append(f"今日 +{int(item.stars_today)} ⭐")
    lines.append(" · ".join(meta))

    if item.tech_stack:
        lines.append(f"技术栈：{_escape(_clean_text(item.tech_stack, 80))}")
    reason = _clean_text(item.reason, MAX_REASON_CHARS)
    if reason:
        lines.append(f"推荐理由：{_escape(reason)}")

    url = item.url or f"https://github.com/{item.repo_id}"
    lines.append(f'<a href="{_escape(url)}">查看项目</a>')
    return "\n".join(lines)


def build_digest_messages(items: Sequence[DigestItem], now: Optional[datetime] = None) -> list[str]:
    """把摘要条目打包为若干条 Telegram 消息（每条 ≤ 3800 字符）。"""
    if not items:
        return []
    date_text = _normalize_now(now).strftime("%Y-%m-%d")
    header = (
        "<b>🗂 开源项目工厂 · 每日精选</b>\n"
        f"<i>{date_text} · {len(items)} 个项目</i>"
    )
    blocks = [build_item_block(index, item) for index, item in enumerate(items, start=1)]

    messages: list[str] = []
    current = header
    for block in blocks:
        candidate = f"{current}\n\n{block}"
        if len(candidate) <= DIGEST_TARGET_CHARS:
            current = candidate
            continue
        messages.append(current)
        current = block
    if current:
        messages.append(current)
    return messages


def build_digest_items(
    recommendations: Sequence[Recommendation],
    repositories: dict[str, TrendingRepository],
) -> list[DigestItem]:
    """把推荐记录与热榜仓库元数据拼装为摘要条目。"""
    items: list[DigestItem] = []
    for row in recommendations:
        repo = repositories.get(row.repo_id)
        repo_id = row.repo_id
        title = repo_id
        url = f"https://github.com/{repo_id}"
        description = ""
        tech_stack = ""
        stars_today = 0
        if repo is not None:
            # 优先用 owner/repo 全名，避免同名仓库无法区分
            title = repo.id or repo.name
            url = repo.html_url or url
            description = repo.description or ""
            tech_stack = repo.tech_stack or ""
            stars_today = int(repo.stars_today or 0)
        reason = (row.reason or "").strip() or description
        match_score = row.match_score if row.match_score else row.score
        items.append(
            DigestItem(
                repo_id=repo_id,
                title=title,
                url=url,
                reason=reason,
                match_score=float(match_score or 0.0),
                quality_score=float(row.quality_score or 0.0),
                stars_today=stars_today,
                tech_stack=tech_stack,
            )
        )
    return items


def load_digest_items(
    db: Session,
    *,
    user_id: Optional[str] = None,
    limit: Optional[int] = None,
    now: Optional[datetime] = None,
    window_hours: Optional[int] = None,
) -> list[DigestItem]:
    """读取最近窗口内进入 `pushed` 的推荐，并水合热榜仓库元数据。"""
    settings = get_settings()
    max_items = max(1, min(int(limit or settings.TELEGRAM_DAILY_LIMIT), 50))
    hours = max(1, int(window_hours or settings.TELEGRAM_DIGEST_WINDOW_HOURS))
    cutoff = _normalize_now(now) - timedelta(hours=hours)

    stmt = select(Recommendation).where(
        Recommendation.status == "pushed",
        Recommendation.created_at >= cutoff,
    )
    if user_id:
        stmt = stmt.where(Recommendation.user_id == user_id)
    stmt = stmt.order_by(
        Recommendation.quality_score.desc(),
        Recommendation.score.desc(),
    ).limit(max_items)
    rows = list(db.execute(stmt).scalars().all())
    if not rows:
        return []

    repo_ids = {row.repo_id for row in rows}
    repos = {
        repo.id: repo
        for repo in db.execute(
            select(TrendingRepository).where(TrendingRepository.id.in_(repo_ids))
        )
        .scalars()
        .all()
    }
    return build_digest_items(rows, repos)


class TelegramClient:
    """Telegram Bot API 客户端（同步，供 Celery / FastAPI 调用）。

    `transport` / `sleep` 可注入，测试使用 `httpx.MockTransport` 且不真正等待。
    """

    def __init__(
        self,
        *,
        token: Optional[str] = None,
        chat_id: Optional[str] = None,
        api_base: Optional[str] = None,
        timeout: Optional[float] = None,
        max_retries: Optional[int] = None,
        retry_base: Optional[float] = None,
        transport: Optional[httpx.BaseTransport] = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        settings: Settings = get_settings()
        self._token = (token if token is not None else settings.TELEGRAM_BOT_TOKEN).strip()
        self.chat_id = (chat_id if chat_id is not None else settings.TELEGRAM_CHAT_ID).strip()
        self.api_base = (api_base if api_base is not None else settings.TELEGRAM_API_BASE).rstrip("/")
        self.timeout = float(timeout if timeout is not None else settings.TELEGRAM_TIMEOUT_SECONDS)
        self.max_retries = max(0, int(max_retries if max_retries is not None else settings.TELEGRAM_MAX_RETRIES))
        self.retry_base = max(0.0, float(retry_base if retry_base is not None else settings.TELEGRAM_RETRY_BASE_SECONDS))
        self._transport = transport
        self._sleep = sleep
        if not self._token or not self.chat_id:
            raise TelegramNotConfigured("Telegram 未配置：缺少 TELEGRAM_BOT_TOKEN 或 TELEGRAM_CHAT_ID")

    def _redact(self, text: str) -> str:
        """错误信息脱敏：Token 绝不外泄。"""
        value = str(text or "")
        if self._token:
            value = value.replace(self._token, "***")
        return value[:500]

    def _post(self, payload: dict[str, Any]) -> httpx.Response:
        url = f"{self.api_base}/bot{self._token}/sendMessage"
        with httpx.Client(timeout=self.timeout, transport=self._transport) as client:
            return client.post(url, json=payload)

    def _backoff(self, attempt: int) -> float:
        return min(30.0, self.retry_base * (2**attempt))

    def _extract_error(self, response: httpx.Response) -> str:
        description = ""
        retry_after: Optional[float] = None
        try:
            body = response.json()
            if not isinstance(body, dict):
                raise TypeError("unexpected body")
            description = str(body.get("description") or "")
            parameters = body.get("parameters") or {}
            raw_retry = parameters.get("retry_after") or body.get("retry_after")
            if raw_retry is not None:
                retry_after = float(raw_retry)
        except (ValueError, TypeError, AttributeError):
            description = (response.text or "")[:200]
        if response.status_code == 429:
            wait = max(0.0, min(60.0, retry_after if retry_after is not None else self.retry_base))
            return f"Telegram API 429（限流，建议等待 {wait:g}s）: {description}".strip()
        return f"Telegram API {response.status_code}: {description}".strip()

    def _request_with_retry(self, payload: dict[str, Any]) -> dict[str, Any]:
        attempt = 0
        while True:
            try:
                response = self._post(payload)
            except httpx.HTTPError as exc:
                if attempt >= self.max_retries:
                    raise TelegramError(
                        self._redact(f"Telegram 网络请求失败：{exc}"),
                        retryable=True,
                    ) from None
                self._sleep(self._backoff(attempt))
                attempt += 1
                continue

            if response.status_code == 200:
                try:
                    body = response.json()
                except ValueError:
                    raise TelegramError("Telegram 返回了非 JSON 响应", status_code=200) from None
                if body.get("ok"):
                    return body.get("result") or {}
                raise TelegramError(
                    self._redact(f"Telegram 返回失败：{body.get('description') or 'ok=false'}"),
                    status_code=200,
                )

            if response.status_code == 429:
                if attempt >= self.max_retries:
                    raise TelegramError(self._redact(self._extract_error(response)), status_code=429, retryable=True)
                retry_after = self.retry_base
                try:
                    body = response.json()
                    parameters = (body.get("parameters") or {}) if isinstance(body, dict) else {}
                    retry_after = float(parameters.get("retry_after") or retry_after)
                except (ValueError, TypeError, AttributeError):
                    pass
                self._sleep(max(0.0, min(60.0, retry_after)))
                attempt += 1
                continue

            if response.status_code >= 500:
                if attempt >= self.max_retries:
                    raise TelegramError(self._redact(self._extract_error(response)), status_code=response.status_code, retryable=True)
                self._sleep(self._backoff(attempt))
                attempt += 1
                continue

            # 其他 4xx（token 无效 / chat 不存在 / 参数错误）不重试
            raise TelegramError(
                self._redact(self._extract_error(response)),
                status_code=response.status_code,
            )

    def send_text(self, text: str, *, chat_id: Optional[str] = None) -> TelegramSendResult:
        """发送文本（自动分片），返回所有 message_id。"""
        parts = split_text(text)
        if not parts:
            raise ValueError("消息内容为空")
        return self.send_parts(parts, chat_id=chat_id)

    def send_parts(self, parts: Sequence[str], *, chat_id: Optional[str] = None) -> TelegramSendResult:
        """按给定分片逐条发送；任一分片失败即抛出（已发送条目不回滚）。"""
        target = (chat_id or self.chat_id).strip()
        message_ids: list[str] = []
        for part in parts:
            result = self._request_with_retry(
                {
                    "chat_id": target,
                    "text": part,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                }
            )
            message_id = result.get("message_id")
            message_ids.append(str(message_id) if message_id is not None else "")
        return TelegramSendResult(message_ids=message_ids, parts=len(message_ids))


def _create_delivery(
    db: Session,
    *,
    kind: str,
    chat_id: str,
    item_count: int,
    dedupe_key: str,
) -> TelegramDelivery:
    delivery = TelegramDelivery(
        id=uuid4().hex,
        chat_id=chat_id,
        kind=kind,
        status="pending",
        item_count=item_count,
        dedupe_key=dedupe_key,
    )
    db.add(delivery)
    db.commit()
    db.refresh(delivery)
    return delivery


def _finish_delivery(
    db: Session,
    delivery: TelegramDelivery,
    *,
    status: str,
    message_count: int = 0,
    message_ids: Optional[Sequence[str]] = None,
    error: Optional[str] = None,
) -> None:
    delivery.status = status
    delivery.message_count = int(message_count)
    if message_ids:
        delivery.message_id = next((item for item in message_ids if item), None)
    delivery.error = (error or "")[:500] or None
    delivery.finished_at = _utcnow()
    db.commit()


def send_digest(
    db: Session,
    *,
    user_id: Optional[str] = None,
    limit: Optional[int] = None,
    force: bool = False,
    now: Optional[datetime] = None,
    client: Optional[TelegramClient] = None,
) -> dict[str, Any]:
    """发送每日摘要；返回结构化状态（disabled / not_configured / duplicate / empty / sent / error）。"""
    settings = get_settings()
    if not settings.TELEGRAM_ENABLED:
        return {"status": "disabled", "sent": False}

    token = (settings.TELEGRAM_BOT_TOKEN or "").strip()
    chat_id = (settings.TELEGRAM_CHAT_ID or "").strip()
    if not token or not chat_id:
        return {"status": "not_configured", "sent": False}

    current = _normalize_now(now)
    dedupe_key = f"telegram:digest:{current.date().isoformat()}:{user_id or 'all'}:{chat_id}"
    if not force:
        existing = (
            db.execute(
                select(TelegramDelivery)
                .where(
                    TelegramDelivery.dedupe_key == dedupe_key,
                    TelegramDelivery.status == "sent",
                )
                .limit(1)
            )
            .scalars()
            .first()
        )
        if existing is not None:
            return {
                "status": "duplicate",
                "sent": False,
                "deliveryId": existing.id,
                "messageIds": [existing.message_id] if existing.message_id else [],
            }

    items = load_digest_items(db, user_id=user_id, limit=limit, now=current)
    if not items:
        return {"status": "empty", "sent": False, "itemCount": 0}

    messages = build_digest_messages(items, now=current)
    delivery = _create_delivery(
        db,
        kind="digest",
        chat_id=chat_id,
        item_count=len(items),
        dedupe_key=dedupe_key,
    )
    try:
        sender = client or TelegramClient()
        result = sender.send_parts(messages)
    except Exception as exc:  # noqa: BLE001 - 发送失败统一落记录并返回结构化错误
        error = str(exc) if isinstance(exc, TelegramError) else f"{type(exc).__name__}: {exc}"
        _finish_delivery(db, delivery, status="failed", error=error)
        logger.warning("Telegram 摘要发送失败：%s", error)
        return {
            "status": "error",
            "sent": False,
            "deliveryId": delivery.id,
            "error": error[:500],
            "itemCount": len(items),
        }

    _finish_delivery(
        db,
        delivery,
        status="sent",
        message_count=result.parts,
        message_ids=result.message_ids,
    )
    logger.info("Telegram 摘要已发送：%d 条推荐 / %d 条消息", len(items), result.parts)
    return {
        "status": "sent",
        "sent": True,
        "deliveryId": delivery.id,
        "itemCount": len(items),
        "messageCount": result.parts,
        "messageIds": result.message_ids,
    }


def send_test_message(
    db: Session,
    *,
    text: Optional[str] = None,
    client: Optional[TelegramClient] = None,
) -> dict[str, Any]:
    """发送一条连通性测试消息（不要求 TELEGRAM_ENABLED，便于启用前验证）。"""
    settings = get_settings()
    chat_id = (settings.TELEGRAM_CHAT_ID or "").strip()
    if not (settings.TELEGRAM_BOT_TOKEN or "").strip() or not chat_id:
        raise TelegramNotConfigured("Telegram 未配置：缺少 TELEGRAM_BOT_TOKEN 或 TELEGRAM_CHAT_ID")

    content = _clean_text(text or DEFAULT_TEST_TEXT, 1000)
    payload = f"<b>OpenFactory · Telegram 测试</b>\n{_escape(content)}"
    delivery = _create_delivery(
        db,
        kind="test",
        chat_id=chat_id,
        item_count=0,
        dedupe_key=f"telegram:test:{uuid4().hex}",
    )
    try:
        sender = client or TelegramClient()
        result = sender.send_text(payload)
    except Exception as exc:  # noqa: BLE001
        error = str(exc) if isinstance(exc, TelegramError) else f"{type(exc).__name__}: {exc}"
        _finish_delivery(db, delivery, status="failed", error=error)
        raise TelegramError(error) from None

    _finish_delivery(
        db,
        delivery,
        status="sent",
        message_count=result.parts,
        message_ids=result.message_ids,
    )
    return {
        "status": "sent",
        "sent": True,
        "deliveryId": delivery.id,
        "messageCount": result.parts,
        "messageIds": result.message_ids,
    }


def status_snapshot(db: Session) -> dict[str, Any]:
    """返回通道状态（不含 token，chat id 脱敏）。"""
    settings = get_settings()
    last = (
        db.execute(
            select(TelegramDelivery)
            .order_by(TelegramDelivery.created_at.desc())
            .limit(1)
        )
        .scalars()
        .first()
    )
    return {
        "enabled": bool(settings.TELEGRAM_ENABLED),
        "configured": bool((settings.TELEGRAM_BOT_TOKEN or "").strip())
        and bool((settings.TELEGRAM_CHAT_ID or "").strip()),
        "chatIdMasked": mask_chat_id(settings.TELEGRAM_CHAT_ID),
        "apiBase": settings.TELEGRAM_API_BASE,
        "dailyLimit": int(settings.TELEGRAM_DAILY_LIMIT),
        "digestWindowHours": int(settings.TELEGRAM_DIGEST_WINDOW_HOURS),
        "lastDelivery": last,
    }
