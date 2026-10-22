"""自动打标建议接口（REQ-202610-0960 / M7-01）。

`POST /api/tag-suggestions/generate` 根据仓库中文摘要生成标签建议，
只读不落库，由 edge 侧负责用户隔离与持久化。沿用内部鉴权。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas import TagSuggestionGenerateIn, TagSuggestionGenerateOut
from app.security import require_internal_token
from app.services.tag_suggestions import generate_for_repositories

router = APIRouter(
    prefix="/api/tag-suggestions",
    tags=["tag-suggestions"],
    dependencies=[Depends(require_internal_token)],
)


@router.post("/generate", response_model=TagSuggestionGenerateOut, summary="基于摘要生成标签建议")
def generate_tag_suggestions(
    payload: TagSuggestionGenerateIn,
    db: Session = Depends(get_db),
) -> TagSuggestionGenerateOut:
    result = generate_for_repositories(
        db,
        repo_ids=payload.repoIds,
        limit=payload.limit,
        per_repo=payload.perRepo,
    )
    return TagSuggestionGenerateOut(**result)
