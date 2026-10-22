"""推送去重与静默策略接口（M4-07）。

与 `/api/tasks/*` 一致，配置 `INTERNAL_TOKEN` 后需携带 `X-Internal-Token`。
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.api.tasks import require_internal_token
from app.db import get_db
from app.schemas import (
    PushEventCreate,
    PushEventListResponse,
    PushEventWriteResponse,
    PushPolicyCheckRequest,
    PushPolicyDecision,
    PushPolicyStatusOut,
)
from app.services import push_policy

router = APIRouter(
    prefix="/api/push/policy",
    tags=["push-policy"],
    dependencies=[Depends(require_internal_token)],
)


@router.get("/status", response_model=PushPolicyStatusOut, summary="推送策略状态")
def get_policy_status(db: Session = Depends(get_db)) -> PushPolicyStatusOut:
    """返回策略开关、静默状态、今日计数与最近事件。"""
    return PushPolicyStatusOut(**push_policy.policy_status(db))


@router.post("/check", response_model=PushPolicyDecision, summary="发送前预演（不写库）")
def check_push(
    payload: PushPolicyCheckRequest,
    db: Session = Depends(get_db),
) -> PushPolicyDecision:
    """判定单条推送是否允许；用于通道侧二次重试前复核。"""
    decision = push_policy.evaluate_push(
        db,
        user_id=payload.userId,
        repo_id=payload.repoId,
        recommendation_id=payload.recommendationId,
        channel=payload.channel,
    )
    return PushPolicyDecision(**decision)


@router.get("/events", response_model=PushEventListResponse, summary="查询推送事件")
def get_push_events(
    user_id: Optional[str] = Query(default=None, alias="userId"),
    channel: Optional[str] = Query(default=None),
    event_status: Optional[str] = Query(default=None, alias="status"),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> PushEventListResponse:
    """按用户 / 通道 / 状态过滤最近推送事件。"""
    items = push_policy.list_events(
        db,
        user_id=user_id,
        channel=channel,
        status=event_status,
        limit=limit,
    )
    return PushEventListResponse(count=len(items), items=items)


@router.post(
    "/events",
    response_model=PushEventWriteResponse,
    status_code=status.HTTP_201_CREATED,
    summary="记录通道投递事件",
)
def create_push_event(
    payload: PushEventCreate,
    db: Session = Depends(get_db),
) -> PushEventWriteResponse:
    """按「用户 + 仓库 + 通道 + 自然日」幂等记录投递结果。"""
    result = push_policy.record_push_event(
        db,
        user_id=payload.userId,
        repo_id=payload.repoId,
        recommendation_id=payload.recommendationId,
        channel=payload.channel,
        status=payload.status,
        reason=payload.reason,
    )
    db.commit()
    return PushEventWriteResponse(**result)
