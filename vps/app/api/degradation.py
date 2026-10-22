"""降级路径自检接口（REQ-202610-0927 / M3-09）。

`GET /api/degradation/status` 返回当前配置下的降级预期与自检结果，
供部署后核对「模型缺失 / 超预算 → hash 向量 / 截断摘要」是否仍然成立。
"""
from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends

from app.security import require_internal_token
from app.schemas import DegradationCheckOut, DegradationStatusOut
from app.services.degradation import run_degradation_checks

router = APIRouter(prefix="/api/degradation", tags=["degradation"])


@router.get(
    "/status",
    response_model=DegradationStatusOut,
    dependencies=[Depends(require_internal_token)],
    summary="降级路径自检状态",
)
def degradation_status() -> DegradationStatusOut:
    report = run_degradation_checks()
    return DegradationStatusOut(
        ok=report.ok,
        summary=report.summary,
        embeddingModel=report.embedding_model,
        embeddingQuantization=report.embedding_quantization,
        embeddingExpectedBackend=report.embedding_expected_backend,
        llmModel=report.llm_model,
        llmDegraded=report.llm_degraded,
        budgetMb=report.budget_mb,
        checks=[DegradationCheckOut(**asdict(check)) for check in report.checks],
    )
