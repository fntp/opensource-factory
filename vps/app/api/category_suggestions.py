"""自动分类建议内部接口 `/api/category-suggestions/*`（M7-02）。

供 edge Worker 调用，统一要求 `X-Internal-Token`（`INTERNAL_TOKEN` 为空时不鉴权）。
VPS 只做无状态的规则计算：edge 把当前用户的仓库快照内联传入，避免跨用户数据混用。
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends

from app.schemas import (
    CategorySuggestionGenerateRequest,
    CategorySuggestionGenerateResponse,
    CategorySuggestionItemOut,
    CategorySuggestionRepoOut,
)
from app.security import require_internal_token
from app.services.category_suggestions import RepoSnapshot, suggest_for_repos

router = APIRouter(
    prefix="/api/category-suggestions",
    tags=["category-suggestions"],
    dependencies=[Depends(require_internal_token)],
)


@router.post(
    "/generate",
    response_model=CategorySuggestionGenerateResponse,
    summary="按业务线生成分类建议",
)
def generate(payload: CategorySuggestionGenerateRequest) -> CategorySuggestionGenerateResponse:
    """根据仓库名称 / 标签 / 简介 / 摘要生成分类建议（纯规则，不访问网络）。"""
    snapshots = [
        RepoSnapshot(
            repo_id=item.repoId,
            name=item.name,
            description=item.description,
            language=item.language,
            summary=item.summary,
            tags=tuple(item.tags),
        )
        for item in payload.repos
    ]
    items, scanned, suggested, skipped = suggest_for_repos(
        snapshots,
        per_repo=payload.perRepo,
        min_score=payload.minScore,
    )
    return CategorySuggestionGenerateResponse(
        generatedAt=datetime.now(timezone.utc).isoformat(),
        scanned=scanned,
        suggested=suggested,
        skipped=skipped,
        items=[
            CategorySuggestionRepoOut(
                repoId=str(item["repoId"]),
                suggestions=[
                    CategorySuggestionItemOut(**suggestion)
                    for suggestion in item["suggestions"]  # type: ignore[union-attr]
                ],
            )
            for item in items
        ],
    )
