"""Email 推送通道（M4-05）。

职责：

- 把每日评估后进入 `pushed` 的高质量推荐生成中文摘要邮件（纯文本 + HTML）；
- 通过标准库 `smtplib` 投递，支持 STARTTLS / 隐式 SSL / SMTP AUTH；
- 以 `email_deliveries` 记录每次投递结果，按「日期 + 收件人」做最小幂等；
- 未启用、未配置、无数据、网络或 SMTP 异常一律返回结构化结果，不阻塞主流程。

安全约束：SMTP 密码只从环境变量读取，不写日志、不出现在状态接口与错误信息中；
测试通过注入 `smtp_factory` 覆盖发送路径，不访问网络。
"""
from __future__ import annotations

import html as html_lib
import logging
import re
import smtplib
import ssl
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid
from typing import Any, Callable, Optional, Sequence
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.models import EmailDelivery, MyRepository, Recommendation, TrendingRepository
from app.services.push_records import record_delivery as record_push_delivery

logger = logging.getLogger(__name__)

MAX_SUBJECT_LENGTH = 160
MAX_ERROR_LENGTH = 300
MAX_ITEMS = 50
MAX_RECIPIENTS = 20
DEFAULT_SUBJECT_PREFIX = "OpenFactory 每日精选"
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class EmailConfigError(ValueError):
    """Email 通道未启用或配置不完整。"""


@dataclass(frozen=True)
class EmailContent:
    """一封待发送邮件的内容。"""

    subject: str
    text: str
    html: str


@dataclass(frozen=True)
class EmailSendResult:
    """一次 SMTP 投递的结果。"""

    ok: bool
    message_id: Optional[str] = None
    error: Optional[str] = None
    attempts: int = 0


@dataclass(frozen=True)
class DigestItem:
    """摘要中的单条推荐（已从推荐 + 仓库元数据拼装）。"""

    repo_id: str
    title: str
    url: str
    description: str
    reason: str
    match_score: float
    quality_score: float
    tech_stack: str
    stars_today: int


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


def truncate_text(value: Any, limit: int) -> str:
    """去除首尾空白并按字符数截断。"""
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def sanitize_header(value: Any, limit: int = MAX_SUBJECT_LENGTH) -> str:
    """清理邮件头：移除 CR/LF 与控制字符，防止头注入，并按长度截断。"""
    raw = str(value or "")
    raw = re.sub(r"[\r\n]+", " ", raw)
    cleaned = "".join(ch for ch in raw if ch == "\t" or ord(ch) >= 32)
    return truncate_text(cleaned, limit)


def is_valid_email(value: Any) -> bool:
    """基础邮箱格式校验（不依赖 email-validator 额外依赖）。"""
    text = str(value or "").strip()
    if not text or len(text) > 254 or ".." in text:
        return False
    return bool(_EMAIL_RE.match(text))


def _split_recipients(raw: str | Sequence[str] | None) -> list[str]:
    """把逗号 / 分号分隔的收件人拆成列表。"""
    if raw is None:
        return []
    if isinstance(raw, str):
        chunks = re.split(r"[,;]+", raw)
    else:
        chunks = []
        for item in raw:
            chunks.extend(re.split(r"[,;]+", str(item)))
    return [chunk.strip() for chunk in chunks if chunk.strip()]


def normalize_recipients(raw: str | Sequence[str] | None) -> list[str]:
    """归一化收件人：去空白、去重（大小写不敏感）、校验格式。"""
    chunks = _split_recipients(raw)
    if len(chunks) > MAX_RECIPIENTS:
        raise EmailConfigError(f"收件人过多（最多 {MAX_RECIPIENTS} 个）")
    result: list[str] = []
    seen: set[str] = set()
    for chunk in chunks:
        if not is_valid_email(chunk):
            raise EmailConfigError(f"收件人地址无效：{mask_email(chunk)}")
        key = chunk.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(chunk)
    return result


def mask_email(value: Any) -> str:
    """脱敏邮箱：保留本地部分首字符与域名。"""
    text = str(value or "").strip()
    if not text:
        return ""
    if "," in text or ";" in text:
        return ", ".join(mask_email(part) for part in _split_recipients(text))
    local, separator, domain = text.partition("@")
    if not separator or not domain:
        return "***"
    prefix = f"{local[:1]}***" if local else "***"
    return f"{prefix}@{domain}"


def format_percent(score: Any) -> str:
    """把 0~1 分数格式化为百分比整数。"""
    try:
        number = float(score)
    except (TypeError, ValueError):
        number = 0.0
    number = max(0.0, min(1.0, number))
    return f"{round(number * 100)}%"


def _esc(value: Any) -> str:
    """HTML 转义（含引号，避免属性被截断）。"""
    return html_lib.escape(str(value or ""), quote=True)


def is_configured(settings: Optional[Settings] = None) -> bool:
    """判断 SMTP 基础配置是否齐全（不校验收件人）。"""
    cfg = settings or get_settings()
    host = str(cfg.EMAIL_SMTP_HOST or "").strip()
    sender = str(cfg.EMAIL_FROM or "").strip()
    try:
        port = int(cfg.EMAIL_SMTP_PORT or 0)
    except (TypeError, ValueError):
        port = 0
    return bool(
        host
        and sender
        and is_valid_email(sender)
        and 1 <= port <= 65535
        and not (cfg.EMAIL_SSL and cfg.EMAIL_STARTTLS)
    )


def validate_settings(settings: Optional[Settings] = None) -> None:
    """校验发送所需配置；缺失或冲突时抛 `EmailConfigError`。"""
    cfg = settings or get_settings()
    missing: list[str] = []
    if not str(cfg.EMAIL_SMTP_HOST or "").strip():
        missing.append("EMAIL_SMTP_HOST")
    sender = str(cfg.EMAIL_FROM or "").strip()
    if not sender:
        missing.append("EMAIL_FROM")
    elif not is_valid_email(sender):
        raise EmailConfigError("EMAIL_FROM 不是合法邮箱地址")
    try:
        port = int(cfg.EMAIL_SMTP_PORT or 0)
    except (TypeError, ValueError):
        port = 0
    if not 1 <= port <= 65535:
        raise EmailConfigError("EMAIL_SMTP_PORT 必须在 1~65535 之间")
    if cfg.EMAIL_SSL and cfg.EMAIL_STARTTLS:
        raise EmailConfigError("EMAIL_SSL 与 EMAIL_STARTTLS 不能同时开启")
    if missing:
        raise EmailConfigError("Email 通道未配置：" + "、".join(missing))


def digest_dedupe_key(
    recipients: Sequence[str], now: Optional[datetime] = None
) -> str:
    """生成摘要幂等键：日期 + 收件人集合。"""
    date_text = _normalize_now(now).strftime("%Y-%m-%d")
    normalized = ",".join(sorted(str(item).strip().lower() for item in recipients))
    return f"email:digest:{date_text}:{normalized}"


def build_digest_items(
    recommendations: Sequence[Recommendation],
    repositories: dict[str, Any],
) -> list[DigestItem]:
    """把推荐记录与仓库元数据拼装为摘要条目。"""
    items: list[DigestItem] = []
    for row in recommendations:
        repo = repositories.get(row.repo_id)
        repo_id = str(row.repo_id or "")
        title = repo_id
        url = f"https://github.com/{repo_id}" if repo_id else ""
        description = ""
        tech_stack = ""
        stars_today = 0
        if repo is not None:
            title = getattr(repo, "name", None) or getattr(repo, "id", None) or repo_id
            url = getattr(repo, "html_url", None) or url
            description = str(getattr(repo, "description", None) or "")
            tech_stack = str(getattr(repo, "tech_stack", None) or "")
            stars_today = int(getattr(repo, "stars_today", 0) or 0)
        reason = str(row.reason or "").strip() or description
        match_score = float(row.match_score or row.score or 0.0)
        quality_score = float(row.quality_score or 0.0)
        items.append(
            DigestItem(
                repo_id=repo_id,
                title=title,
                url=url,
                description=description,
                reason=reason,
                match_score=match_score,
                quality_score=quality_score,
                tech_stack=tech_stack,
                stars_today=stars_today,
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
    settings: Optional[Settings] = None,
) -> list[DigestItem]:
    """读取最近窗口内进入 `pushed` 的推荐，并水合仓库元数据。"""
    cfg = settings or get_settings()
    max_items = max(1, min(int(limit or cfg.EMAIL_DAILY_LIMIT), MAX_ITEMS))
    hours = max(1, int(window_hours or cfg.EMAIL_DIGEST_WINDOW_HOURS))
    cutoff = _normalize_now(now) - timedelta(hours=hours)

    statement = select(Recommendation).where(
        Recommendation.status == "pushed",
        Recommendation.created_at >= cutoff,
    )
    if user_id:
        statement = statement.where(Recommendation.user_id == user_id)
    statement = statement.order_by(
        Recommendation.quality_score.desc(),
        Recommendation.match_score.desc(),
        Recommendation.created_at.desc(),
    ).limit(max_items)
    rows = db.execute(statement).scalars().all()
    if not rows:
        return []

    repo_ids = {row.repo_id for row in rows if row.repo_id}
    repositories: dict[str, Any] = {}
    if repo_ids:
        for repo in db.execute(
            select(TrendingRepository).where(TrendingRepository.id.in_(repo_ids))
        ).scalars():
            repositories[repo.id] = repo
        missing = repo_ids - set(repositories)
        if missing:
            for repo in db.execute(
                select(MyRepository).where(MyRepository.id.in_(missing))
            ).scalars():
                repositories[repo.id] = repo
    return build_digest_items(rows, repositories)


def render_digest(
    items: Sequence[DigestItem], now: Optional[datetime] = None
) -> EmailContent:
    """渲染中文摘要邮件（纯文本 + 内联样式 HTML）。"""
    date_text = _normalize_now(now).strftime("%Y-%m-%d")
    subject = f"{DEFAULT_SUBJECT_PREFIX} · {date_text}（{len(items)} 个项目）"

    text_lines: list[str] = [
        f"{DEFAULT_SUBJECT_PREFIX} · {date_text}",
        f"共 {len(items)} 个与你技术栈匹配的开源项目",
        "",
    ]
    cards: list[str] = []
    for index, item in enumerate(items, start=1):
        title = item.title or item.repo_id
        meta_parts: list[str] = []
        if item.match_score > 0:
            meta_parts.append(f"匹配度 {format_percent(item.match_score)}")
        if item.quality_score > 0:
            meta_parts.append(f"质量分 {item.quality_score:.2f}")
        if item.stars_today > 0:
            meta_parts.append(f"今日 +{item.stars_today} ⭐")
        if item.tech_stack:
            meta_parts.append(f"技术栈：{item.tech_stack}")
        meta_text = " · ".join(meta_parts)

        text_lines.append(f"{index}. {title}")
        if item.description:
            text_lines.append(f"   {item.description}")
        if item.reason and item.reason != item.description:
            text_lines.append(f"   推荐理由：{item.reason}")
        if meta_text:
            text_lines.append(f"   {meta_text}")
        if item.url:
            text_lines.append(f"   {item.url}")
        text_lines.append("")

        link_html = (
            f'<a href="{_esc(item.url)}" style="color:#0f172a;text-decoration:none;">{_esc(title)}</a>'
            if item.url
            else _esc(title)
        )
        description_html = (
            f'<p style="margin:0 0 8px;color:#475569;font-size:14px;line-height:1.65;">{_esc(item.description)}</p>'
            if item.description
            else ""
        )
        reason_html = (
            f'<p style="margin:0 0 8px;color:#334155;font-size:14px;line-height:1.65;">'
            f"<strong>推荐理由：</strong>{_esc(item.reason)}</p>"
            if item.reason and item.reason != item.description
            else ""
        )
        meta_html = (
            f'<div style="font-size:12px;color:#64748b;line-height:1.6;">{_esc(meta_text)}</div>'
            if meta_text
            else ""
        )
        cards.append(
            '<div style="border:1px solid #e2e8f0;border-radius:12px;padding:16px 18px;'
            'margin:0 0 14px;background:#ffffff;">'
            f'<div style="font-size:12px;color:#94a3b8;margin-bottom:6px;">#{index}</div>'
            f'<h2 style="margin:0 0 8px;font-size:17px;line-height:1.4;">{link_html}</h2>'
            f"{description_html}{reason_html}{meta_html}"
            "</div>"
        )

    text_lines.extend(
        [
            "--",
            "你收到这封邮件是因为订阅了 OpenFactory 每日精选。",
            "如需退订，请在推送偏好设置中关闭 Email 通道。",
        ]
    )
    html_doc = (
        '<!doctype html><html lang="zh-CN"><body style="margin:0;padding:0;background:#f8fafc;'
        "font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,'Helvetica Neue',"
        "Arial,'PingFang SC','Microsoft YaHei',sans-serif;color:#0f172a;\">"
        '<div style="max-width:640px;margin:0 auto;padding:28px 16px;">'
        '<div style="background:#0f172a;border-radius:16px 16px 0 0;padding:24px 24px 20px;color:#ffffff;">'
        '<div style="font-size:12px;letter-spacing:2px;color:#94a3b8;text-transform:uppercase;">'
        "OPENFACTORY DAILY</div>"
        f'<h1 style="margin:8px 0 0;font-size:22px;line-height:1.35;">'
        f"{_esc(DEFAULT_SUBJECT_PREFIX)} · {date_text}</h1>"
        f'<div style="margin-top:8px;font-size:13px;color:#cbd5e1;">共 {len(items)} 个与你技术栈匹配的开源项目</div>'
        "</div>"
        '<div style="background:#f1f5f9;padding:18px 18px 6px;">'
        + "".join(cards)
        + "</div>"
        '<div style="background:#ffffff;border-radius:0 0 16px 16px;padding:16px 24px;'
        'border:1px solid #e2e8f0;border-top:0;font-size:12px;color:#94a3b8;line-height:1.6;">'
        "你收到这封邮件是因为订阅了 OpenFactory 每日精选。如需退订，请在推送偏好设置中关闭 Email 通道。"
        "</div></div></body></html>"
    )
    return EmailContent(subject=subject, text="\n".join(text_lines), html=html_doc)


def build_email_message(
    content: EmailContent,
    recipients: Sequence[str],
    settings: Optional[Settings] = None,
) -> EmailMessage:
    """构建 MIME 邮件（纯文本 + HTML 替代体）。"""
    cfg = settings or get_settings()
    validate_settings(cfg)
    from_addr = str(cfg.EMAIL_FROM or "").strip()
    from_name = sanitize_header(cfg.EMAIL_FROM_NAME or "OpenFactory", 80) or "OpenFactory"
    message = EmailMessage()
    message["Subject"] = sanitize_header(content.subject) or DEFAULT_SUBJECT_PREFIX
    message["From"] = formataddr((from_name, from_addr))
    message["To"] = ", ".join(recipients)
    message["Date"] = formatdate(localtime=False)
    domain = from_addr.split("@", 1)[1] if "@" in from_addr else None
    message["Message-ID"] = make_msgid(domain=domain)
    message["Auto-Submitted"] = "auto-generated"
    message.set_content(content.text)
    message.add_alternative(content.html, subtype="html")
    return message


class SmtpSender:
    """SMTP 发送器（同步，便于 Celery 任务直接使用）。

    `smtp_factory` 与 `sleep` 可注入，测试不访问网络、不真正等待。
    """

    def __init__(
        self,
        settings: Optional[Settings] = None,
        *,
        smtp_factory: Optional[Callable[..., Any]] = None,
        sleep: Optional[Callable[[float], None]] = None,
    ) -> None:
        self.settings = settings or get_settings()
        self._smtp_factory = smtp_factory
        self._sleep = sleep or time.sleep

    def _factory(self, use_ssl: bool) -> Callable[..., Any]:
        if self._smtp_factory is not None:
            return self._smtp_factory
        return smtplib.SMTP_SSL if use_ssl else smtplib.SMTP

    def _deliver(self, message: EmailMessage, recipients: Sequence[str]) -> None:
        cfg = self.settings
        timeout = max(1.0, float(cfg.EMAIL_TIMEOUT_SECONDS or 15.0))
        use_ssl = bool(cfg.EMAIL_SSL)
        factory = self._factory(use_ssl)
        if use_ssl:
            client = factory(
                cfg.EMAIL_SMTP_HOST,
                int(cfg.EMAIL_SMTP_PORT),
                timeout=timeout,
                context=ssl.create_default_context(),
            )
        else:
            client = factory(
                cfg.EMAIL_SMTP_HOST,
                int(cfg.EMAIL_SMTP_PORT),
                timeout=timeout,
            )
        with client:
            client.ehlo()
            if cfg.EMAIL_STARTTLS and not use_ssl:
                client.starttls(context=ssl.create_default_context())
                client.ehlo()
            username = str(cfg.EMAIL_SMTP_USERNAME or "").strip()
            if username:
                client.login(username, str(cfg.EMAIL_SMTP_PASSWORD or ""))
            client.send_message(
                message,
                from_addr=str(cfg.EMAIL_FROM or "").strip(),
                to_addrs=list(recipients),
            )

    def _safe_error(self, exc: BaseException) -> str:
        """把 SMTP 异常转成可展示文本，并替换密码 / 用户名等敏感信息。"""
        text = truncate_text(f"{type(exc).__name__}: {exc}", 220)
        password = str(self.settings.EMAIL_SMTP_PASSWORD or "")
        if password:
            text = text.replace(password, "***")
        username = str(self.settings.EMAIL_SMTP_USERNAME or "").strip()
        if username:
            text = text.replace(username, mask_email(username))
        return truncate_text(text, MAX_ERROR_LENGTH)

    def send(
        self, content: EmailContent, recipients: Sequence[str]
    ) -> EmailSendResult:
        """发送一封邮件；可重试错误按指数退避重试，认证 / 收件人错误立即失败。"""
        try:
            validate_settings(self.settings)
            normalized = normalize_recipients(recipients)
            if not normalized:
                raise EmailConfigError("收件人为空")
        except EmailConfigError as exc:
            return EmailSendResult(ok=False, error=str(exc), attempts=0)

        message = build_email_message(content, normalized, self.settings)
        retries = max(0, int(self.settings.EMAIL_MAX_RETRIES or 0))
        base_delay = max(0.0, float(self.settings.EMAIL_RETRY_BASE_SECONDS or 0.0))
        attempts = 0
        last_error = ""
        for attempt in range(1, retries + 2):
            attempts = attempt
            try:
                self._deliver(message, normalized)
                return EmailSendResult(
                    ok=True,
                    message_id=str(message["Message-ID"]),
                    attempts=attempt,
                )
            except (
                smtplib.SMTPAuthenticationError,
                smtplib.SMTPRecipientsRefused,
                smtplib.SMTPSenderRefused,
            ) as exc:
                last_error = self._safe_error(exc)
                break
            except (smtplib.SMTPException, OSError) as exc:
                last_error = self._safe_error(exc)
                if attempt <= retries:
                    self._sleep(base_delay * (2 ** (attempt - 1)))
                    continue
                break
        return EmailSendResult(
            ok=False, error=last_error or "邮件发送失败", attempts=attempts
        )


def _record_delivery(
    db: Session,
    *,
    recipients: Sequence[str],
    kind: str,
    status: str,
    item_count: int,
    subject: str,
    message_id: Optional[str],
    dedupe_key: str,
    error: Optional[str],
) -> EmailDelivery:
    """写入一条送达记录并返回（调用方负责 commit）。"""
    delivery = EmailDelivery(
        id=uuid4().hex,
        recipient=", ".join(recipients),
        kind=kind,
        status=status,
        item_count=item_count,
        subject=truncate_text(subject, 255),
        message_id=truncate_text(message_id, 255) if message_id else None,
        dedupe_key=dedupe_key,
        error=truncate_text(error, MAX_ERROR_LENGTH) if error else None,
        finished_at=_utcnow(),
    )
    db.add(delivery)
    db.commit()
    db.refresh(delivery)
    record_push_delivery(
        db,
        channel="email",
        kind=kind,
        target=", ".join(recipients),
        target_type="email",
        ok=status == "sent",
        item_count=item_count,
        message_count=1 if status == "sent" else 0,
        message_id=message_id,
        subject=subject,
        dedupe_key=dedupe_key,
        error=error,
        source_id=delivery.id,
    )
    return delivery


def send_digest(
    db: Session,
    *,
    user_id: Optional[str] = None,
    recipients: str | Sequence[str] | None = None,
    limit: Optional[int] = None,
    force: bool = False,
    now: Optional[datetime] = None,
    settings: Optional[Settings] = None,
    sender: Optional[Any] = None,
) -> dict[str, Any]:
    """读取 `pushed` 推荐并投递每日摘要邮件。

    返回结构统一为 `{status, ok, itemCount, deliveryId?, messageId?, error?}`；
    `status` 取 `disabled / not_configured / empty / skipped / sent / failed`。
    """
    cfg = settings or get_settings()
    if not cfg.EMAIL_ENABLED:
        return {
            "status": "disabled",
            "ok": False,
            "itemCount": 0,
            "error": "EMAIL_ENABLED=false",
        }
    try:
        validate_settings(cfg)
        target = normalize_recipients(
            recipients if recipients is not None else cfg.EMAIL_TO
        )
    except EmailConfigError as exc:
        return {
            "status": "not_configured",
            "ok": False,
            "itemCount": 0,
            "error": str(exc),
        }
    if not target:
        return {
            "status": "not_configured",
            "ok": False,
            "itemCount": 0,
            "error": "EMAIL_TO 未配置",
        }

    items = load_digest_items(
        db, user_id=user_id, limit=limit, now=now, settings=cfg
    )
    if not items:
        return {
            "status": "empty",
            "ok": False,
            "itemCount": 0,
            "error": "没有可推送的推荐",
        }

    key = digest_dedupe_key(target, now)
    if not force:
        existing = (
            db.execute(
                select(EmailDelivery)
                .where(
                    EmailDelivery.dedupe_key == key,
                    EmailDelivery.status == "sent",
                )
                .order_by(EmailDelivery.created_at.desc())
                .limit(1)
            )
            .scalars()
            .first()
        )
        if existing is not None:
            return {
                "status": "skipped",
                "ok": True,
                "reason": "already_sent",
                "deliveryId": existing.id,
                "itemCount": existing.item_count,
            }

    content = render_digest(items, now)
    result = (sender or SmtpSender(cfg)).send(content, target)
    delivery = _record_delivery(
        db,
        recipients=target,
        kind="digest",
        status="sent" if result.ok else "failed",
        item_count=len(items),
        subject=content.subject,
        message_id=result.message_id,
        dedupe_key=key,
        error=result.error,
    )
    logger.info(
        "Email 摘要投递: status=%s items=%d attempts=%d",
        delivery.status,
        delivery.item_count,
        result.attempts,
    )
    return {
        "status": "sent" if result.ok else "failed",
        "ok": result.ok,
        "deliveryId": delivery.id,
        "itemCount": len(items),
        "messageId": result.message_id,
        "error": result.error,
    }


def send_test_email(
    db: Session,
    *,
    to: str | Sequence[str] | None = None,
    subject: Optional[str] = None,
    body: Optional[str] = None,
    settings: Optional[Settings] = None,
    sender: Optional[Any] = None,
) -> dict[str, Any]:
    """发送一封连通性测试邮件；配置不完整时抛 `EmailConfigError`。"""
    cfg = settings or get_settings()
    validate_settings(cfg)
    target = normalize_recipients(to if to is not None else cfg.EMAIL_TO)
    if not target:
        raise EmailConfigError("收件人未配置（EMAIL_TO 或请求参数 to）")

    now = _utcnow()
    subject_text = sanitize_header(
        subject or f"OpenFactory Email 通道测试 · {now.strftime('%Y-%m-%d %H:%M')}"
    )
    body_text = str(
        body
        or "这是一封来自 OpenFactory 的测试邮件，收到即表示 SMTP 配置可用。"
    ).strip()
    body_html = _esc(body_text).replace("\n", "<br>")
    content = EmailContent(
        subject=subject_text or "OpenFactory Email 通道测试",
        text=body_text,
        html=(
            '<!doctype html><html lang="zh-CN"><body style="margin:0;padding:24px;'
            "background:#f8fafc;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',"
            "Arial,'PingFang SC','Microsoft YaHei',sans-serif;color:#0f172a;\">"
            '<div style="max-width:560px;margin:0 auto;background:#ffffff;border:1px solid #e2e8f0;'
            'border-radius:12px;padding:24px;font-size:14px;line-height:1.7;">'
            "<h1 style=\"margin:0 0 12px;font-size:18px;\">OpenFactory Email 通道测试</h1>"
            f"<p style=\"margin:0;color:#475569;\">{body_html}</p>"
            "</div></body></html>"
        ),
    )
    result = (sender or SmtpSender(cfg)).send(content, target)
    delivery = _record_delivery(
        db,
        recipients=target,
        kind="test",
        status="sent" if result.ok else "failed",
        item_count=0,
        subject=content.subject,
        message_id=result.message_id,
        dedupe_key="",
        error=result.error,
    )
    return {
        "ok": result.ok,
        "status": "sent" if result.ok else "failed",
        "deliveryId": delivery.id,
        "itemCount": 0,
        "messageId": result.message_id,
        "error": result.error,
    }


def delivery_to_dict(row: EmailDelivery) -> dict[str, Any]:
    """把送达记录转换为 API 输出（收件人脱敏）。"""
    return {
        "id": row.id,
        "recipientMasked": mask_email(row.recipient),
        "kind": row.kind,
        "status": row.status,
        "itemCount": row.item_count,
        "subject": row.subject,
        "messageId": row.message_id,
        "error": row.error,
        "createdAt": row.created_at,
        "finishedAt": row.finished_at,
    }


def get_email_status(
    db: Session, settings: Optional[Settings] = None
) -> dict[str, Any]:
    """返回通道状态快照（不暴露 SMTP 密码 / 用户名明文）。"""
    cfg = settings or get_settings()
    last = (
        db.execute(
            select(EmailDelivery).order_by(EmailDelivery.created_at.desc()).limit(1)
        )
        .scalars()
        .first()
    )
    return {
        "enabled": bool(cfg.EMAIL_ENABLED),
        "configured": is_configured(cfg),
        "host": str(cfg.EMAIL_SMTP_HOST or "").strip(),
        "port": int(cfg.EMAIL_SMTP_PORT or 0),
        "starttls": bool(cfg.EMAIL_STARTTLS),
        "ssl": bool(cfg.EMAIL_SSL),
        "fromMasked": mask_email(cfg.EMAIL_FROM),
        "toMasked": mask_email(cfg.EMAIL_TO),
        "lastDelivery": last,
    }
