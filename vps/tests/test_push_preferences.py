"""推送偏好测试（M4-06）。

覆盖：时间 / 时区 / 阈值 / 通道归一化、默认值、推送窗口（含跨午夜与时区换算）、
阈值过滤、edge 内部接口客户端降级，以及 daily_push 与偏好的集成行为。
全部使用本地 SQLite 与 httpx MockTransport，不访问网络。
"""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import delete

from app.db import SessionLocal, init_db
from app.models import PushEvent, Recommendation
from app.services.push_preferences import (
    DEFAULT_MIN_QUALITY_SCORE,
    DEFAULT_MIN_SCORE,
    DEFAULT_TIME_OF_DAY,
    DEFAULT_TIMEZONE,
    PushChannels,
    PushPreferenceClient,
    PushPreferences,
    default_preferences,
    filter_recommendations,
    is_due,
    matches_thresholds,
    normalize_channels,
    normalize_preferences,
    normalize_time_of_day,
    normalize_timezone,
)
from app.tasks.jobs import daily_push

USER_A = "pref-test-a"
USER_B = "pref-test-b"


@pytest.fixture()
def db():
    init_db()
    session = SessionLocal()
    _cleanup(session)
    yield session
    _cleanup(session)
    session.close()


def _cleanup(session) -> None:
    session.execute(delete(PushEvent).where(PushEvent.user_id.like("pref-test%")))
    session.execute(delete(Recommendation).where(Recommendation.user_id.like("pref-test%")))
    session.commit()


def _seed(db, suffix: str, *, user_id: str = USER_A, match_score: float = 0.7,
          quality_score: float = 0.0, status: str = "qualified") -> None:
    db.add(
        Recommendation(
            id=f"pref-test-rec-{suffix}",
            user_id=user_id,
            repo_id=f"pref-test/{suffix}",
            score=match_score,
            match_score=match_score,
            quality_score=quality_score,
            reason="pref test",
            status=status,
        )
    )
    db.commit()


def _row(db, suffix: str, user_id: str = USER_A) -> Recommendation:
    db.expire_all()
    return db.get(Recommendation, f"pref-test-rec-{suffix}")


def test_normalize_time_of_day() -> None:
    assert normalize_time_of_day("9:05") == "09:05"
    assert normalize_time_of_day("09:05:00") == "09:05"
    assert normalize_time_of_day("24:00") == DEFAULT_TIME_OF_DAY
    assert normalize_time_of_day("abc") == DEFAULT_TIME_OF_DAY
    assert normalize_time_of_day(None) == DEFAULT_TIME_OF_DAY
    assert normalize_time_of_day("7:30", "08:00") == "07:30"


def test_normalize_timezone() -> None:
    assert normalize_timezone("UTC") == "UTC"
    assert normalize_timezone("Asia/Shanghai") == "Asia/Shanghai"
    assert normalize_timezone("Mars/Olympus") == DEFAULT_TIMEZONE
    assert normalize_timezone("") == DEFAULT_TIMEZONE


def test_default_preferences_match_product_defaults() -> None:
    prefs = default_preferences()
    assert prefs.enabled is True
    assert prefs.time_of_day == "09:00"
    assert prefs.timezone == "Asia/Shanghai"
    assert prefs.min_score == DEFAULT_MIN_SCORE
    assert prefs.min_quality_score == DEFAULT_MIN_QUALITY_SCORE
    assert prefs.channels.to_dict() == {
        "inapp": True,
        "bark": False,
        "telegram": False,
        "email": False,
    }


def test_normalize_preferences_supports_camel_and_flat_channels() -> None:
    prefs = normalize_preferences(
        {
            "enabled": "false",
            "timeOfDay": "8:30",
            "timezone": "Asia/Tokyo",
            "minScore": 1.7,
            "minQualityScore": -0.2,
            "channel_bark": 1,
            "channel_telegram": "on",
        }
    )
    assert prefs.enabled is False
    assert prefs.time_of_day == "08:30"
    assert prefs.timezone == "Asia/Tokyo"
    assert prefs.min_score == 1.0
    assert prefs.min_quality_score == 0.0
    assert prefs.channels.bark is True
    assert prefs.channels.telegram is True
    assert prefs.channels.inapp is True  # 未提供的字段沿用默认


def test_normalize_channels_respects_base() -> None:
    base = PushChannels(inapp=False, bark=True, telegram=False, email=True)
    channels = normalize_channels({"email": False}, base)
    assert channels.inapp is False
    assert channels.bark is True
    assert channels.email is False


def test_is_due_uses_user_timezone() -> None:
    prefs = PushPreferences(time_of_day="09:00", timezone="Asia/Shanghai")
    # UTC 01:00 == 上海 09:00
    assert is_due(prefs, now=datetime(2026, 10, 22, 1, 0, tzinfo=timezone.utc))
    # UTC 01:09 == 上海 09:09，仍在 10 分钟窗口内
    assert is_due(prefs, now=datetime(2026, 10, 22, 1, 9, tzinfo=timezone.utc))
    # UTC 01:10 == 上海 09:10，窗口结束
    assert not is_due(prefs, now=datetime(2026, 10, 22, 1, 10, tzinfo=timezone.utc))
    # UTC 00:59 == 上海 08:59，未到时间
    assert not is_due(prefs, now=datetime(2026, 10, 22, 0, 59, tzinfo=timezone.utc))


def test_is_due_supports_midnight_window_and_disable_switch() -> None:
    prefs = PushPreferences(time_of_day="23:55", timezone="UTC")
    assert is_due(prefs, now=datetime(2026, 10, 22, 23, 58, tzinfo=timezone.utc))
    assert is_due(prefs, now=datetime(2026, 10, 23, 0, 2, tzinfo=timezone.utc))
    assert not is_due(prefs, now=datetime(2026, 10, 23, 0, 6, tzinfo=timezone.utc))
    assert not is_due(
        PushPreferences(enabled=False, time_of_day="09:00", timezone="UTC"),
        now=datetime(2026, 10, 22, 9, 0, tzinfo=timezone.utc),
    )


def test_matches_thresholds_and_filter() -> None:
    prefs = PushPreferences(min_score=0.5, min_quality_score=0.6)
    eligible = SimpleNamespace(match_score=0.8, quality_score=0.9)
    low_match = SimpleNamespace(match_score=0.3, quality_score=0.9)
    low_quality = SimpleNamespace(match_score=0.8, quality_score=0.4)
    legacy = SimpleNamespace(match_score=0.0, score=0.7, quality_score=0.0)

    assert matches_thresholds(eligible, prefs)
    assert not matches_thresholds(low_match, prefs)
    assert not matches_thresholds(low_quality, prefs)
    # match_score 缺失回退 score；quality_score 未评估（0）不参与过滤
    assert matches_thresholds(legacy, prefs)
    assert filter_recommendations([eligible, low_match, low_quality, legacy], prefs) == [
        eligible,
        legacy,
    ]


def test_client_fetch_all_and_graceful_failure() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "userId": USER_A,
                        "preferences": {
                            "enabled": True,
                            "timeOfDay": "08:30",
                            "timezone": "UTC",
                            "minScore": 0.6,
                            "channels": {"inapp": True, "bark": True},
                        },
                    },
                    {"userId": "", "preferences": {}},
                ]
            },
        )

    client = PushPreferenceClient(
        "https://edge.example.com", "internal-token",
        transport=httpx.MockTransport(handler),
    )
    prefs = client.fetch_all()
    assert set(prefs) == {USER_A}
    assert prefs[USER_A].time_of_day == "08:30"
    assert prefs[USER_A].min_score == 0.6
    assert prefs[USER_A].channels.bark is True
    assert calls[0].headers["X-Internal-Token"] == "internal-token"
    assert str(calls[0].url) == "https://edge.example.com/api/internal/push-preferences"

    def failing(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "boom"})

    failing_client = PushPreferenceClient(
        "https://edge.example.com", "internal-token",
        transport=httpx.MockTransport(failing),
    )
    assert failing_client.fetch_all() == {}

    unconfigured = PushPreferenceClient("", "")
    assert unconfigured.configured is False
    assert unconfigured.fetch_all() == {}


def test_daily_push_applies_preferences(db, monkeypatch) -> None:
    _seed(db, "a-eligible", user_id=USER_A, match_score=0.8)
    _seed(db, "a-low", user_id=USER_A, match_score=0.2)
    _seed(db, "b-eligible", user_id=USER_B, match_score=0.9)
    _seed(db, "b-low-quality", user_id=USER_B, match_score=0.9, quality_score=0.3)
    _seed(db, "b-unqualified", user_id=USER_B, match_score=0.9, status="new")

    prefs = {
        USER_A: PushPreferences(
            min_score=0.5, min_quality_score=0.0, channels=PushChannels()
        ),
        USER_B: PushPreferences(
            min_score=0.5, min_quality_score=0.6, channels=PushChannels()
        ),
    }
    monkeypatch.setattr(
        "app.services.push_preferences.fetch_all_preferences", lambda **_: prefs
    )

    result = daily_push()

    assert result["pushed"] == 2
    assert _row(db, "a-eligible", USER_A).status == "pushed"
    assert _row(db, "a-low", USER_A).status == "qualified"
    assert _row(db, "b-eligible", USER_B).status == "pushed"
    assert _row(db, "b-low-quality", USER_B).status == "qualified"
    assert _row(db, "b-unqualified", USER_B).status == "new"


def test_daily_push_skips_disabled_no_channel_and_not_due(db, monkeypatch) -> None:
    _seed(db, "disabled", user_id=USER_A)
    _seed(db, "no-channel", user_id=USER_B)
    _seed(db, "not-due", user_id="pref-test-c")

    prefs = {
        USER_A: PushPreferences(enabled=False),
        USER_B: PushPreferences(
            channels=PushChannels(inapp=False, bark=False, telegram=False, email=False)
        ),
        "pref-test-c": PushPreferences(time_of_day="09:00", timezone="UTC"),
    }
    monkeypatch.setattr(
        "app.services.push_preferences.fetch_all_preferences", lambda **_: prefs
    )

    result = daily_push(
        respect_schedule=True,
        now=datetime(2026, 10, 22, 3, 0, tzinfo=timezone.utc),
    )

    assert result["pushed"] == 0
    assert result["skippedUsers"] == 3
    assert _row(db, "disabled", USER_A).status == "qualified"
    assert _row(db, "no-channel", USER_B).status == "qualified"
    assert _row(db, "not-due", "pref-test-c").status == "qualified"
    reasons = {item["userId"]: item["reason"] for item in result["users"]}
    assert reasons == {
        USER_A: "disabled",
        USER_B: "no_channel",
        "pref-test-c": "not_due",
    }
