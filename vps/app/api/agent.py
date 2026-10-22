"""Agent 工作流内部接口（REQ-202610-0968 / M7-09）。

``POST /api/agent/draft`` 接收 edge 内联传入的当前用户仓库快照与待处理建议，
返回确定性的执行计划与 Markdown 草稿。接口只做计算，不落库、不访问网络。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.schemas import AgentDraftIn, AgentDraftOut
from app.security import require_internal_token
from app.services.agent_workflow import (
    ActionSnapshot,
    RepoSnapshot,
    build_agent_response,
)

router = APIRouter(
    prefix="/api/agent",
    tags=["agent"],
    dependencies=[Depends(require_internal_token)],
)


@router.post("/draft", response_model=AgentDraftOut, summary="生成 Agent 执行计划与收藏草稿")
def generate_agent_draft(payload: AgentDraftIn) -> AgentDraftOut:
    repos = [
        RepoSnapshot(
            repo_id=item.repoId,
            name=item.name,
            description=item.description,
            language=item.language,
            stars=item.stars,
            category=item.category,
            tags=tuple(item.tags),
            summary=item.summary,
        )
        for item in payload.repos
    ]

    def actions(items: list) -> list[ActionSnapshot]:
        return [
            ActionSnapshot(
                kind=item.kind,
                repo_id=item.repoId,
                value=item.value,
                score=item.score,
                reason=item.reason,
            )
            for item in items
        ]

    result = build_agent_response(
        template=payload.template,
        mode=payload.mode,
        threshold=payload.threshold,
        repos=repos,
        pending_tags=actions(payload.pendingTags),
        pending_categories=actions(payload.pendingCategories),
        applied_tags=actions(payload.appliedTags),
        applied_categories=actions(payload.appliedCategories),
        focus=payload.focus,
    )
    return AgentDraftOut(**result)
