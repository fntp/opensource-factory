"""抓取容错与页面结构变更告警。

设计目标（REQ-202610-0910 / M2-02）：

- **不抛异常**：网络错误、限流、5xx、解析异常一律降级为结构化结果（空列表 + 日志）；
- **有限重试**：仅对超时 / 连接错误 / 429 / 5xx 做指数退避，4xx（除 429）不重试；
- **结构变更检测**：HTTP 200 但候选行为 0、解析结果为 0，或条数相对上次成功骤降，
  判定为疑似页面改版；
- **告警闭环**：写入 `crawl_alerts`（按 `platform:page:kind` 去重），可选 webhook 通知；
- **基线维护**：`crawl_page_stats` 记录每页上次成功条数，供跨轮次对比。

本模块不依赖具体站点解析器，HTTP 客户端与 sleep 均可注入，测试不访问网络。
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Optional
from uuid import uuid4

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import CrawlAlert, CrawlPageStat

logger = logging.getLogger(__name__)

TRANSIENT_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
ALERT_KIND_FETCH_FAILED = "fetch_failed"
ALERT_KIND_STRUCTURE_CHANGE = "structure_change"
ALERT_KIND_COUNT_DROP = "count_drop"
ALERT_KIND_ALL_FAILED = "all_failed"


def _utcnow() -> datetime:
    """统一使用无时区 UTC 时间（与模型默认值一致）。"""
    return datetime.now(timezone.utc).replace(tzinfo=None)


@dataclass(frozen=True)
class CrawlRetryPolicy:
    """单页抓取重试策略。"""

    max_attempts: int = 3
    base_delay: float = 1.0
    max_delay: float = 8.0

    def delay_for(self, attempt: int, retry_after: float | None = None) -> float:
        """第 `attempt` 次失败后的等待秒数；`Retry-After` 优先但受上限约束。"""
        if retry_after is not None:
            return max(0.0, min(float(retry_after), self.max_delay))
        delay = self.base_delay * (2 ** max(0, attempt - 1))
        return max(0.0, min(delay, self.max_delay))


def policy_from_settings(settings: Any | None = None) -> CrawlRetryPolicy:
    """从全局配置构造重试策略（缺字段时使用默认值，便于单测）。"""
    cfg = settings or get_settings()
    return CrawlRetryPolicy(
        max_attempts=max(1, int(getattr(cfg, "TRENDING_RETRY_MAX", 3) or 3)),
        base_delay=max(0.0, float(getattr(cfg, "TRENDING_RETRY_BASE_DELAY", 1.0) or 0.0)),
        max_delay=max(0.0, float(getattr(cfg, "TRENDING_RETRY_MAX_DELAY", 8.0) or 0.0)),
    )


def is_transient_status(status_code: int | None) -> bool:
    """429 / 5xx 可重试；其余 4xx 属于确定性失败，不重试。"""
    return status_code in TRANSIENT_STATUS_CODES


def _retry_after_seconds(response: httpx.Response) -> float | None:
    """解析 `Retry-After`（仅支持秒数；HTTP 日期格式忽略）。"""
    raw = (response.headers.get("Retry-After") or "").strip()
    if not raw:
        return None
    try:
        return max(0.0, float(raw))
    except ValueError:
        return None


@dataclass
class FetchResult:
    """单页抓取结果（失败也返回对象，不抛异常）。"""

    status_code: Optional[int]
    text: str
    error: Optional[str]
    attempts: int

    @property
    def ok(self) -> bool:
        return self.error is None and self.status_code == 200


async def fetch_html_with_retry(
    client: Any,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    policy: CrawlRetryPolicy | None = None,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> FetchResult:
    """带重试地抓取 HTML；任何异常都转换为 `FetchResult.error`。

    `client` 只需实现 `async def get(url, headers=...)`（httpx.AsyncClient 或测试替身）。
    """
    policy = policy or policy_from_settings()
    last_status: Optional[int] = None
    last_error = ""

    for attempt in range(1, policy.max_attempts + 1):
        response: Any = None
        try:
            response = await client.get(url, headers=headers or {})
        except Exception as exc:  # noqa: BLE001 - 抓取失败必须降级，不能中断任务
            last_status = None
            last_error = f"{type(exc).__name__}: {exc}"
        else:
            last_status = int(getattr(response, "status_code", 0) or 0)
            if last_status == 200:
                return FetchResult(200, str(getattr(response, "text", "") or ""), None, attempt)
            last_error = f"HTTP {last_status}"

        if attempt >= policy.max_attempts:
            break

        retry_after = _retry_after_seconds(response) if response is not None else None
        if response is not None and not is_transient_status(last_status):
            # 4xx（429 除外）重试也不会成功，直接降级
            break
        delay = policy.delay_for(attempt, retry_after)
        logger.warning(
            "抓取失败（第 %d/%d 次，%s），%.1fs 后重试: %s",
            attempt,
            policy.max_attempts,
            last_error,
            delay,
            url,
        )
        await sleep(delay)

    logger.warning("抓取最终失败（尝试 %d 次）: %s（%s）", attempt, url, last_error)
    return FetchResult(last_status, "", last_error or "unknown error", attempt)


@dataclass(frozen=True)
class PageHealth:
    """单页健康判定结果。"""

    kind: str
    severity: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)


def evaluate_page_health(
    *,
    page: str,
    ok: bool,
    error: str | None = None,
    status_code: int | None = None,
    rows: int | None = None,
    parsed: int | None = None,
    baseline: int | None = None,
    drop_ratio: float = 0.3,
    min_baseline: int = 5,
) -> Optional[PageHealth]:
    """判定页面是否需要告警；健康时返回 None。

    规则优先级：抓取失败 → 页面无候选行 → 候选行全部解析失败 → 条数骤降。
    """
    if not ok:
        return PageHealth(
            kind=ALERT_KIND_FETCH_FAILED,
            severity="warning",
            message=f"页面 {page} 抓取失败：{error or 'unknown error'}",
            details={"page": page, "statusCode": status_code, "error": error},
        )

    if rows is not None and rows <= 0:
        return PageHealth(
            kind=ALERT_KIND_STRUCTURE_CHANGE,
            severity="error",
            message=f"页面 {page} 未找到任何候选行，疑似页面结构变更",
            details={"page": page, "statusCode": status_code, "rows": rows, "parsed": parsed},
        )

    if rows is not None and parsed is not None and rows > 0 and parsed <= 0:
        return PageHealth(
            kind=ALERT_KIND_STRUCTURE_CHANGE,
            severity="error",
            message=f"页面 {page} 候选行 {rows} 条但全部解析失败，疑似选择器失配",
            details={"page": page, "statusCode": status_code, "rows": rows, "parsed": parsed},
        )

    if (
        baseline is not None
        and parsed is not None
        and baseline >= min_baseline
        and parsed < baseline * max(0.0, min(1.0, drop_ratio))
    ):
        return PageHealth(
            kind=ALERT_KIND_COUNT_DROP,
            severity="warning",
            message=f"页面 {page} 条数骤降：上次 {baseline} 条，本次 {parsed} 条",
            details={
                "page": page,
                "statusCode": status_code,
                "baseline": baseline,
                "parsed": parsed,
                "dropRatio": drop_ratio,
            },
        )
    return None


def get_page_baseline(db: Session, platform: str, page: str) -> int | None:
    """读取某页上次成功抓取条数；无记录返回 None。"""
    key = f"{platform}:{page}"
    stat = db.get(CrawlPageStat, key)
    return stat.last_count if stat is not None else None


def update_page_stat(
    db: Session,
    *,
    platform: str,
    page: str,
    count: int,
    ok: bool,
    error: str | None = None,
    status_code: int | None = None,
    rows: int | None = None,
    parsed: int | None = None,
) -> CrawlPageStat:
    """更新页面统计（成功时刷新基线，失败时保留旧基线）。"""
    key = f"{platform}:{page}"
    stat = db.get(CrawlPageStat, key)
    now = _utcnow()
    if stat is None:
        stat = CrawlPageStat(
            page_key=key,
            platform=platform,
            page=page,
            last_count=0,
            last_ok_at=None,
            last_error=None,
            updated_at=now,
        )
        db.add(stat)
    stat.platform = platform
    stat.page = page
    stat.updated_at = now
    if ok:
        stat.last_count = max(0, int(count))
        stat.last_ok_at = now
        stat.last_error = None
    else:
        stat.last_error = (error or "unknown error")[:500]
    stat.last_status_code = status_code
    stat.last_rows = rows
    stat.last_parsed = parsed
    return stat


def record_alert(
    db: Session,
    *,
    platform: str,
    page: str,
    kind: str,
    severity: str,
    message: str,
    details: dict[str, Any] | None = None,
    cooldown_minutes: int = 360,
) -> tuple[CrawlAlert, bool]:
    """写入或合并告警，返回 `(alert, created)`。

    同一 `platform:page:kind` 在冷却窗口内复用同一条 open 告警并累加次数；
    超出窗口视为新事件，另起一条，避免长期故障只留一条旧记录。
    """
    dedupe_key = f"{platform}:{page}:{kind}"
    now = _utcnow()
    latest = (
        db.execute(
            select(CrawlAlert)
            .where(CrawlAlert.dedupe_key == dedupe_key, CrawlAlert.status == "open")
            .order_by(CrawlAlert.last_seen_at.desc())
        )
        .scalars()
        .first()
    )
    payload = json.dumps(details or {}, ensure_ascii=False, default=str)

    if latest is not None and latest.last_seen_at >= now - timedelta(minutes=max(0, cooldown_minutes)):
        latest.occurrences += 1
        latest.last_seen_at = now
        latest.message = message[:2000]
        latest.details = payload
        latest.severity = severity
        return latest, False

    alert = CrawlAlert(
        id=uuid4().hex,
        platform=platform,
        page=page,
        kind=kind,
        severity=severity,
        message=message[:2000],
        details=payload,
        dedupe_key=dedupe_key,
        status="open",
        occurrences=1,
        first_seen_at=now,
        last_seen_at=now,
    )
    db.add(alert)
    return alert, True


def notify_alert_webhook(alert: CrawlAlert, url: str | None = None) -> bool:
    """best-effort webhook 通知；未配置或失败只记日志。"""
    target = (url if url is not None else get_settings().TRENDING_ALERT_WEBHOOK_URL).strip()
    if not target:
        return False
    payload = {
        "source": "openfactory",
        "type": "crawl_alert",
        "alert": {
            "id": alert.id,
            "platform": alert.platform,
            "page": alert.page,
            "kind": alert.kind,
            "severity": alert.severity,
            "message": alert.message,
            "occurrences": alert.occurrences,
            "firstSeenAt": alert.first_seen_at.isoformat() if alert.first_seen_at else None,
            "lastSeenAt": alert.last_seen_at.isoformat() if alert.last_seen_at else None,
        },
    }
    try:
        resp = httpx.post(target, json=payload, timeout=5.0)
        if 200 <= resp.status_code < 300:
            return True
        logger.warning("抓取告警 webhook 返回 %s", resp.status_code)
    except Exception as exc:  # noqa: BLE001 - 通知失败不能影响抓取
        logger.warning("抓取告警 webhook 发送失败: %s", exc)
    return False


def process_crawl_health(
    db: Session,
    *,
    platform: str,
    pages: list[dict[str, Any]],
    total_items: int,
    settings: Any | None = None,
) -> dict[str, Any]:
    """对一轮抓取的页面统计做健康判定、写告警并更新基线。

    `pages[]` 至少包含 `page/language`、`ok`、`count`；可选 `error/status_code/rows/parsed`。
    任何异常由调用方兜底（本函数不吞 DB 异常，便于测试定位）。
    """
    cfg = settings or get_settings()
    drop_ratio = float(getattr(cfg, "TRENDING_COUNT_DROP_RATIO", 0.3) or 0.3)
    min_baseline = int(getattr(cfg, "TRENDING_COUNT_DROP_MIN_BASELINE", 5) or 5)
    cooldown = int(getattr(cfg, "TRENDING_ALERT_COOLDOWN_MINUTES", 360) or 0)
    webhook_url = str(getattr(cfg, "TRENDING_ALERT_WEBHOOK_URL", "") or "")

    created = 0
    deduplicated = 0
    alert_items: list[dict[str, Any]] = []

    for page in pages:
        page_name = str(page.get("page") or page.get("language") or "all")
        page_platform = str(page.get("platform") or platform)
        ok = bool(page.get("ok", True))
        count = int(page.get("count") or 0)
        rows = page.get("rows")
        parsed = page.get("parsed")
        status_code = page.get("status_code")
        error = page.get("error")
        baseline = get_page_baseline(db, page_platform, page_name)

        health = evaluate_page_health(
            page=page_name,
            ok=ok,
            error=error,
            status_code=status_code,
            rows=rows,
            parsed=parsed,
            baseline=baseline,
            drop_ratio=drop_ratio,
            min_baseline=min_baseline,
        )
        if health is not None:
            alert, is_new = record_alert(
                db,
                platform=page_platform,
                page=page_name,
                kind=health.kind,
                severity=health.severity,
                message=health.message,
                details=health.details,
                cooldown_minutes=cooldown,
            )
            if is_new:
                created += 1
                if webhook_url:
                    notify_alert_webhook(alert, webhook_url)
            else:
                deduplicated += 1
            alert_items.append({"id": alert.id, "kind": alert.kind, "page": alert.page})

        update_page_stat(
            db,
            platform=page_platform,
            page=page_name,
            count=count,
            ok=ok,
            error=error,
            status_code=status_code,
            rows=rows,
            parsed=parsed,
        )

    if total_items <= 0 and pages:
        failed_pages = [str(p.get("page") or p.get("language") or "all") for p in pages if not p.get("ok", True)]
        alert, is_new = record_alert(
            db,
            platform=platform,
            page="all",
            kind=ALERT_KIND_ALL_FAILED,
            severity="error",
            message="本轮热榜抓取结果为 0 条" + (f"（失败页：{', '.join(failed_pages)}）" if failed_pages else ""),
            details={"totalItems": total_items, "failedPages": failed_pages},
            cooldown_minutes=cooldown,
        )
        if is_new:
            created += 1
            if webhook_url:
                notify_alert_webhook(alert, webhook_url)
        else:
            deduplicated += 1
        alert_items.append({"id": alert.id, "kind": alert.kind, "page": alert.page})

    db.commit()
    return {"created": created, "deduplicated": deduplicated, "alerts": alert_items}
