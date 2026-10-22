"""模型路由内部接口（REQ-202610-0965 / M7-06）。

供 edge 以 ``X-Internal-Token`` 调用；所有写操作都会校验候选模型与内存预算。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.schemas import (
    ModelRouteActionOut,
    ModelRouteHealthOut,
    ModelRouteListOut,
    ModelRouteResetOut,
    ModelRouteTaskOut,
    ModelRouteUpdateIn,
    ModelRouteUpgradeIn,
)
from app.security import require_internal_token
from app.services.model_router import (
    TASK_KEYS,
    RouteValidationError,
    current_budget_mb,
    get_route_decision,
    health_payload,
    overview_payload,
    reset_all_route_configs,
    reset_route_config,
    save_route_config,
    task_payload,
    upgrade_candidates,
)

router = APIRouter(
    prefix="/api/model-routes",
    tags=["model-routes"],
    dependencies=[Depends(require_internal_token)],
)


def _ensure_task(task: str) -> None:
    if task not in TASK_KEYS:
        raise HTTPException(status_code=404, detail=f"未知任务：{task}")


def _route_for(task: str) -> ModelRouteTaskOut:
    from app.services.model_router import load_route_configs

    configs = load_route_configs()
    payload = task_payload(task, configs.get(task), current_budget_mb())
    return ModelRouteTaskOut(**payload)


@router.get("", response_model=ModelRouteListOut, summary="模型路由总览")
def list_model_routes() -> ModelRouteListOut:
    return ModelRouteListOut(**overview_payload())


@router.post("/reset", response_model=ModelRouteResetOut, summary="恢复全部任务默认路由")
def reset_model_routes() -> ModelRouteResetOut:
    deleted = reset_all_route_configs()
    return ModelRouteResetOut(
        ok=True,
        deleted=deleted,
        message=f"已恢复默认，删除 {deleted} 条配置",
    )


@router.post("/upgrade", response_model=ModelRouteActionOut, summary="应用任务的最佳可用升级")
def apply_model_upgrade(payload: ModelRouteUpgradeIn) -> ModelRouteActionOut:
    _ensure_task(payload.task)
    decision = get_route_decision(payload.task)
    candidates = upgrade_candidates(payload.task, decision.model_id)
    eligible = [item for item in candidates if item.eligible]
    if not eligible:
        return ModelRouteActionOut(
            ok=False,
            task=payload.task,
            modelId=decision.model_id,
            message="没有预算内可用的升级候选",
            route=_route_for(payload.task),
        )

    target = eligible[0].model
    try:
        config = save_route_config(
            payload.task,
            "manual",
            target.id,
            updated_by="admin",
        )
    except RouteValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ModelRouteActionOut(
        ok=True,
        task=payload.task,
        modelId=target.id,
        message=f"已升级到 {target.name}",
        route=ModelRouteTaskOut(
            **task_payload(payload.task, config, current_budget_mb())
        ),
    )


@router.get("/health", response_model=ModelRouteHealthOut, summary="模型通道健康检查")
def model_route_health() -> ModelRouteHealthOut:
    return ModelRouteHealthOut(**health_payload())


@router.put("/{task}", response_model=ModelRouteTaskOut, summary="更新任务路由")
def update_model_route(task: str, payload: ModelRouteUpdateIn) -> ModelRouteTaskOut:
    _ensure_task(task)
    try:
        config = save_route_config(
            task,
            payload.strategy,
            payload.modelId,
            updated_by=payload.updatedBy or "admin",
        )
    except RouteValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ModelRouteTaskOut(
        **task_payload(task, config, current_budget_mb())
    )


@router.delete("/{task}", response_model=ModelRouteResetOut, summary="恢复任务默认路由")
def reset_model_route(task: str) -> ModelRouteResetOut:
    _ensure_task(task)
    deleted = reset_route_config(task)
    return ModelRouteResetOut(
        ok=True,
        deleted=1 if deleted else 0,
        message="已恢复默认" if deleted else "当前已是默认配置",
    )
