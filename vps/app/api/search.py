"""语义搜索内部接口 `/api/search/*`（M3-04）。

供 edge Worker 调用，统一要求 `X-Internal-Token`（`INTERNAL_TOKEN` 为空时不鉴权）：

- `POST /api/search/embed`：只生成查询向量，edge 拿到后调用 Cloudflare Vectorize；
- `POST /api/search/query`：本地 `repo_vectors` 余弦检索（Vectorize 不可用时的降级）；
- `POST /api/search/semantic`：本地检索并水合完整项目信息（调试 / CLI / 直连场景）；
- `POST /api/search/similar`：以仓库向量为种子的近邻检索（「看了又看」，未水合）；
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
    SearchUnderstandingOut,
    SimilarQuery,
    SimilarQueryResponse,
)
from app.services.embedding import get_embedding_service
from app.services.query_understanding import QueryUnderstandingError, understand_query
from app.services.semantic_search import (
    SearchError,
    get_status,
    normalize_query,
    search_local,
    search_semantic,
)
from app.services.similar_recommendations import (
    SeedNotFound,
    SeedVectorMissing,
    SimilarError,
    find_similar,
)

router = APIRouter(
    prefix="/api/search",
    tags=["search"],
    dependencies=[Depends(require_internal_token)],
)


def _bad_request(exc: SearchError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.post("/understand", response_model=SearchUnderstandingOut, summary="查询理解（同义词 / 技术栈）")
def understand(payload: SearchQuery) -> SearchUnderstandingOut:
    try:
        result = understand_query(payload.query, enabled=payload.expand)
    except QueryUnderstandingError as exc:
        raise _bad_request(exc) from exc
    return SearchUnderstandingOut(**result.to_dict())


@router.post("/embed", response_model=SearchEmbedResponse, summary="生成查询向量")
def embed_query(payload: SearchQuery) -> SearchEmbedResponse:
    try:
        query = normalize_query(payload.query)
        understanding = understand_query(query, enabled=payload.expand)
    except (SearchError, QueryUnderstandingError) as exc:
        raise _bad_request(exc) from exc
    service = get_embedding_service()
    vector = service.encode_one(understanding.rewritten)
    return SearchEmbedResponse(
        vector=vector,
        dim=len(vector),
        model=service.model_name,
        backend=service.backend,
        understanding=SearchUnderstandingOut(**understanding.to_dict()),
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
            expand=payload.expand,
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
            expand=payload.expand,
        )
    except SearchError as exc:
        raise _bad_request(exc) from exc
    return SearchSemanticResponse(**result)


@router.post(
    "/similar",
    response_model=SimilarQueryResponse,
    summary="相似项目推荐（向量近邻，未水合）",
)
def similar_search(payload: SimilarQuery, db: Session = Depends(get_db)) -> SimilarQueryResponse:
    try:
        result = find_similar(
            db,
            payload.source,
            payload.repoId,
            top_k=payload.topK,
            scope=payload.scope,
            min_score=payload.minScore,
            exclude_saved=payload.excludeSaved,
        )
    except SeedNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SeedVectorMissing as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except SimilarError as exc:
        raise _bad_request(exc) from exc
    return SimilarQueryResponse(**result)


@router.get("/status", response_model=SearchStatusResponse, summary="语义搜索可用性")
def search_status(db: Session = Depends(get_db)) -> SearchStatusResponse:
    return SearchStatusResponse(**get_status(db))
