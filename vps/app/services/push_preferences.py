"""推送偏好（M4-06）。

职责：

- 定义推送偏好（启用开关、推送时间、时区、匹配度 / 质量分阈值、通道开关）；
- 校验与归一化前端 / edge 传入的偏好，非法值回退默认值；
- 从 edge 内部接口拉取用户偏好（D1 为唯一数据源），不可达时回退默认值；
- 提供「是否到达推送时间」「是否通过阈值」「是否有可用通道」等纯函数，
  供每日推送任务筛选用户与推荐。

所有逻辑均为本地规则，测试不访问网络；HTTP 客户端支持注入 transport。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)

DEFAULT_TIME_OF_DAY = "09:00"
DEFAULT_TIMEZONE = "Asia/Shanghai"
DEFAULT_MIN_SCORE = 0.35
DEFAULT_MIN_QUALITY_SCORE = 0.55
CHANNEL_KEYS: tuple[str, ...] = ("inapp", "bark", "telegram", "email")
CHANNEL_LABELS: dict[str, str] = {
    "inapp": "站内通知",
    "bark": "Bark",
    "telegram": "Telegram",
    "email": "Email",
}


def _clamp01(value: Any, default: float) -> float:
    """把任意值裁剪到 0~1；非法值返回默认值。"""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return max(0.0, min(1.0, float(default)))
    if number != number or number in (float("inf"), float("-inf")):
        return max(0.0, min(1.0, float(default)))
    return max(0.0, min(1.0, number))


def _as_bool(value: Any, default: bool) -> bool:
    """宽松布尔解析：兼容 true/false、1/0、on/off。"""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        text = value.strip().lower()
        if text in ("1", "true", "yes", "on"):
            return True
        if text in ("0", "false", "no", "off"):
            return False
    return default


def normalize_time_of_day(value: Any, default: str = DEFAULT_TIME_OF_DAY) -> str:
    """归一化 `HH:MM`；支持 `9:00`、`09:00:00`，非法值回退默认。"""
    text = str(value or "").strip()
    if not text:
        return default
    parts = text.split(":")
    if len(parts) not in (2, 3):
        return default
    try:
        hour = int(parts[0])
        minute = int(parts[1])
    except (TypeError, ValueError):
        return default
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return default
    return f"{hour:02d}:{minute:02d}"


def normalize_timezone(value: Any, default: str = DEFAULT_TIMEZONE) -> str:
    """校验 IANA 时区；非法值回退默认。"""
    text = str(value or "").strip()
    if not text:
        return default
    try:
        ZoneInfo(text)
    except (ZoneInfoNotFoundError, ValueError):
        return default
    return text


@dataclass(frozen=True)
class PushChannels:
    """通道开关；默认仅站内通知开启。"""

    inapp: bool = True
    bark: bool = False
    telegram: bool = False
    email: bool = False

    def any_enabled(self) -> bool:
        return any((self.inapp, self.bark, self.telegram, self.email))

    def enabled_keys(self) -> tuple[str, ...]:
        return tuple(
            key for key in CHANNEL_KEYS if bool(getattr(self, key, False))
        )

    def to_dict(self) -> dict[str, bool]:
        return {key: bool(getattr(self, key)) for key in CHANNEL_KEYS}


@dataclass(frozen=True)
class PushPreferences:
    """单个用户的推送偏好。"""

    enabled: bool = True
    time_of_day: str = DEFAULT_TIME_OF_DAY
    timezone: str = DEFAULT_TIMEZONE
    min_score: float = DEFAULT_MIN_SCORE
    min_quality_score: float = DEFAULT_MIN_QUALITY_SCORE
    channels: PushChannels = field(default_factory=PushChannels)
    updated_at: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "timeOfDay": self.time_of_day,
            "timezone": self.timezone,
            "minScore": round(self.min_score, 6),
            "minQualityScore": round(self.min_quality_score, 6),
            "channels": self.channels.to_dict(),
            "updatedAt": self.updated_at,
        }


def default_preferences(settings: Optional[Settings] = None) -> PushPreferences:
    """按配置生成默认偏好（未保存过偏好的用户使用）。"""
    cfg = settings or get_settings()
    return PushPreferences(
        enabled=True,
        time_of_day=normalize_time_of_day(getattr(cfg, "PUSH_DEFAULT_TIME", DEFAULT_TIME_OF_DAY)),
        timezone=normalize_timezone(
            getattr(cfg, "PUSH_DEFAULT_TIMEZONE", DEFAULT_TIMEZONE)
        ),
        min_score=_clamp01(
            getattr(cfg, "PUSH_DEFAULT_MIN_SCORE", DEFAULT_MIN_SCORE),
            DEFAULT_MIN_SCORE,
        ),
        min_quality_score=_clamp01(
            getattr(cfg, "PUSH_DEFAULT_MIN_QUALITY_SCORE", DEFAULT_MIN_QUALITY_SCORE),
            DEFAULT_MIN_QUALITY_SCORE,
        ),
        channels=PushChannels(),
    )


def normalize_channels(
    value: Any, default: Optional[PushChannels] = None
) -> PushChannels:
    """归一化通道开关：支持嵌套 `channels` 与扁平 `channel_*` 两种写法。"""
    base = default or PushChannels()
    data: Mapping[str, Any] = value if isinstance(value, Mapping) else {}
    result: dict[str, bool] = {}
    for key in CHANNEL_KEYS:
        candidate = data.get(key)
        if candidate is None:
            candidate = data.get(f"channel_{key}")
        if candidate is None:
            candidate = data.get(f"channel{key.capitalize()}")
        result[key] = _as_bool(candidate, bool(getattr(base, key)))
    return PushChannels(**result)


def normalize_preferences(
    payload: Any, base: Optional[PushPreferences] = None
) -> PushPreferences:
    """合并并校验偏好；非法字段回退 base / 默认值。"""
    fallback = base or default_preferences()
    data: Mapping[str, Any] = payload if isinstance(payload, Mapping) else {}

    def pick(*keys: str) -> Any:
        for key in keys:
            if key in data and data[key] is not None:
                return data[key]
        return None

    channels_payload = pick("channels")
    if channels_payload is None:
        channels_payload = data

    return PushPreferences(
        enabled=_as_bool(pick("enabled"), fallback.enabled),
        time_of_day=normalize_time_of_day(
            pick("timeOfDay", "time_of_day"), fallback.time_of_day
        ),
        timezone=normalize_timezone(
            pick("timezone", "time_zone"), fallback.timezone
        ),
        min_score=_clamp01(
            pick("minScore", "min_score"), fallback.min_score
        ),
        min_quality_score=_clamp01(
            pick("minQualityScore", "min_quality_score"),
            fallback.min_quality_score,
        ),
        channels=normalize_channels(channels_payload, fallback.channels),
        updated_at=str(pick("updatedAt", "updated_at") or "") or fallback.updated_at,
    )


def is_due(
    prefs: PushPreferences,
    now: Optional[datetime] = None,
    window_minutes: Optional[int] = None,
    settings: Optional[Settings] = None,
) -> bool:
    """判断当前时刻是否落在用户偏好的推送窗口内（支持跨午夜）。"""
    if not prefs.enabled:
        return False
    cfg = settings or get_settings()
    window = max(1, int(window_minutes or getattr(cfg, "PUSH_TIME_WINDOW_MINUTES", 10)))
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    try:
        local = current.astimezone(ZoneInfo(prefs.timezone))
    except (ZoneInfoNotFoundError, ValueError):
        local = current
    start_hour, start_minute = (int(part) for part in prefs.time_of_day.split(":"))
    start = start_hour * 60 + start_minute
    current_minute = local.hour * 60 + local.minute
    return (current_minute - start) % 1440 < window


def matches_thresholds(row: Any, prefs: PushPreferences) -> bool:
    """推荐是否达到用户的匹配度 / 质量分阈值。

    - 匹配度优先使用 `match_score`，历史数据缺失时回退 `score`；
    - 质量分仅在已评估（>0）时参与判断，避免旧数据被默认阈值误杀。
    """
    match = float(getattr(row, "match_score", 0) or 0)
    if match <= 0:
        match = float(getattr(row, "score", 0) or 0)
    if match < prefs.min_score:
        return False
    quality = float(getattr(row, "quality_score", 0) or 0)
    if quality > 0 and quality < prefs.min_quality_score:
        return False
    return True


def filter_recommendations(
    rows: Iterable[Any], prefs: PushPreferences
) -> list[Any]:
    """按用户阈值筛选推荐（保持原顺序）。"""
    return [row for row in rows if matches_thresholds(row, prefs)]


class PushPreferenceClient:
    """edge 推送偏好内部接口客户端。"""

    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        timeout: float = 10.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = (base_url or "").rstrip("/")
        self.token = token or ""
        self.timeout = max(1.0, float(timeout))
        self._transport = transport

    @classmethod
    def from_settings(cls, settings: Optional[Settings] = None) -> "PushPreferenceClient":
        cfg = settings or get_settings()
        return cls(
            (cfg.EDGE_BASE_URL or "").strip(),
            (cfg.INTERNAL_TOKEN or "").strip(),
            timeout=float(getattr(cfg, "PUSH_PREFERENCES_TIMEOUT_SECONDS", 10.0)),
        )

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.token)

    def fetch_all(self) -> dict[str, PushPreferences]:
        """拉取全部已保存偏好；未配置 / 网络失败 / 响应异常时返回空字典。"""
        if not self.configured:
            return {}
        url = f"{self.base_url}/api/internal/push-preferences"
        try:
            with httpx.Client(timeout=self.timeout, transport=self._transport) as client:
                response = client.get(
                    url, headers={"X-Internal-Token": self.token}
                )
                response.raise_for_status()
                body = response.json()
        except Exception as exc:  # noqa: BLE001 - 偏好读取失败回退默认值
            logger.warning("读取推送偏好失败，回退默认值: %s", exc)
            return {}

        items = body.get("items") if isinstance(body, dict) else None
        if not isinstance(items, list):
            return {}
        result: dict[str, PushPreferences] = {}
        for item in items:
            if not isinstance(item, Mapping):
                continue
            user_id = str(item.get("userId") or item.get("user_id") or "").strip()
            if not user_id:
                continue
            payload = item.get("preferences") if "preferences" in item else item
            result[user_id] = normalize_preferences(payload)
        return result


def fetch_all_preferences(
    settings: Optional[Settings] = None,
    transport: httpx.BaseTransport | None = None,
) -> dict[str, PushPreferences]:
    """便捷函数：按当前配置拉取全部用户偏好（失败返回空字典）。"""
    client = PushPreferenceClient.from_settings(settings)
    if transport is not None:
        client = PushPreferenceClient(
            client.base_url, client.token, timeout=client.timeout, transport=transport
        )
    return client.fetch_all()
