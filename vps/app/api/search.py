"""语义搜索内部接口 `/api/search/*`（M3-04）。

供 edge Worker 调用，统一要求 `X-Internal-Token`（`INTERNAL_TOKEN` 为空时不鉴权）：

- `POST /api/search/embed`：只生成查询向量，edge 拿到后调用 Cloudflare Vectorize；
- `POST /api/search/query`：本地 `repo_vectors` 余弦检索（Vectorize 不可用时的降级）；
- `POST /api/search/semantic`：本地检索并水合完整项目信息（调试 / CLI / 直连场景）；
- `GET  /api/search/status`：向量覆盖率与最近向量化运行。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.tasks import require_internal_token
from app.db import get_db
from app.schemas import (
    SearchEmbedResponse,
    SearchQuery,
    SearchQueryResponse,
    SearchSemanticResponse,
    SearchStatusResponse,
)
from app.services.embedding import get_embedding_service
from app.services.semantic_search import (
    SearchError,
    get_status,
    normalize_query,
    search_local,
    search_semantic,
)

router = APIRouter(
    prefix="/api/search",
    tags=["search"],
    dependencies=[Depends(require_internal_token)],
)


def _bad_request(exc: SearchError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.post("/embed", response_model=SearchEmbedResponse, summary="生成查询向量")
def embed_query(payload: SearchQuery) -> SearchEmbedResponse:
    try:
        query = normalize_query(payload.query)
    except SearchError as exc:
        raise _bad_request(exc) from exc
    service = get_embedding_service()
    vector = service.encode_one(query)
    return SearchEmbedResponse(
        vector=vector,
        dim=len(vector),
        model=service.model_name,
        backend=service.backend,
    )


@router.post("/query", response_model=SearchQueryResponse, summary="本地向量检索（未水合）")
def query_vectors(payload: SearchQuery, db: Session = Depends(get_db)) -> SearchQueryResponse:
    try:
        result = search_local(
            db,
            payload.query,
            top_k=payload.topK,
            scope=payload.scope,
            min_score=payload.minScore,
        )
    except SearchError as exc:
        raise _bad_request(exc) from exc
    return SearchQueryResponse(**result)


@router.post("/semantic", response_model=SearchSemanticResponse, summary="本地语义搜索（完整结果）")
def semantic_search(payload: SearchQuery, db: Session = Depends(get_db)) -> SearchSemanticResponse:
    try:
        result = search_semantic(
            db,
            payload.query,
            top_k=payload.topK,
            scope=payload.scope,
            min_score=payload.minScore,
        )
    except SearchError as exc:
        raise _bad_request(exc) from exc
    return SearchSemanticResponse(**result)


@router.get("/status", response_model=SearchStatusResponse, summary="语义搜索可用性")
def search_status(db: Session = Depends(get_db)) -> SearchStatusResponse:
    return SearchStatusResponse(**get_status(db))
