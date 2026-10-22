"""监控与告警接口（REQ-202610-0941 / M5-03）。

- `/api/monitoring/status`：实时健康检查 + 资源 + 阈值 + 告警 + 最近运行；
- `/api/monitoring/check`：立即执行一轮检查并落库；
- `/api/monitoring/history`、`/api/monitoring/alerts`、`/alerts/{id}/ack`；
- `/api/monitoring/logs`、`/logs/cleanup`。

除 `/healthz/ready`（在 main.py 中）外，全部要求内部令牌（配置 INTERNAL_TOKEN 时）。
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.tasks import require_internal_token
from app.config import get_settings
from app.db import get_db
from app.schemas import (
    MonitoringAlertOut,
    MonitoringAlertsOut,
    MonitoringCheckResultOut,
    MonitoringCleanupOut,
    MonitoringHistoryOut,
    MonitoringLogsOut,
    MonitoringStatusOut,
)
from app.services import monitoring

router = APIRouter(prefix="/api/monitoring", tags=["monitoring"])


def _alert_out(alert) -> MonitoringAlertOut:
    return MonitoringAlertOut(**monitoring.serialize_alert(alert))


@router.get(
    "/status",
    response_model=MonitoringStatusOut,
    dependencies=[Depends(require_internal_token)],
    summary="实时监控状态",
)
def monitoring_status(db: Session = Depends(get_db)) -> MonitoringStatusOut:
    payload = monitoring.build_status(db)
    payload["alerts"] = [item for item in payload["alerts"] if item["status"] != "resolved"]
    return MonitoringStatusOut(**payload)


@router.post(
    "/check",
    response_model=MonitoringCheckResultOut,
    dependencies=[Depends(require_internal_token)],
    summary="立即执行一轮监控检查",
)
def run_check(db: Session = Depends(get_db)) -> MonitoringCheckResultOut:
    return MonitoringCheckResultOut(**monitoring.run_monitoring_check(db))


@router.get(
    "/history",
    response_model=MonitoringHistoryOut,
    dependencies=[Depends(require_internal_token)],
    summary="监控检查历史",
)
def check_history(
    limit: int = Query(default=20, ge=1, le=200),
    db: Session = Depends(get_db),
) -> MonitoringHistoryOut:
    items = [monitoring.serialize_run(run) for run in monitoring.list_runs(db, limit=limit)]
    return MonitoringHistoryOut(items=items, count=len(items))


@router.get(
    "/alerts",
    response_model=MonitoringAlertsOut,
    dependencies=[Depends(require_internal_token)],
    summary="告警列表",
)
def list_alerts(
    status_filter: Optional[str] = Query(
        default=None,
        alias="status",
        pattern="^(open|acknowledged|resolved)$",
    ),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> MonitoringAlertsOut:
    items = monitoring.list_alerts(db, status=status_filter, limit=limit)
    return MonitoringAlertsOut(items=[_alert_out(item) for item in items], count=len(items))


@router.post(
    "/alerts/{alert_id}/ack",
    response_model=MonitoringAlertOut,
    dependencies=[Depends(require_internal_token)],
    summary="确认告警",
)
def acknowledge_alert(alert_id: str, db: Session = Depends(get_db)) -> MonitoringAlertOut:
    alert = monitoring.acknowledge_alert(db, alert_id)
    if alert is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="alert not found")
    return _alert_out(alert)


@router.get(
    "/logs",
    response_model=MonitoringLogsOut,
    dependencies=[Depends(require_internal_token)],
    summary="日志文件统计与保留策略",
)
def logs_status() -> MonitoringLogsOut:
    return MonitoringLogsOut(**monitoring.logs_status(get_settings()))


@router.post(
    "/logs/cleanup",
    response_model=MonitoringCleanupOut,
    dependencies=[Depends(require_internal_token)],
    summary="按保留天数清理日志",
)
def cleanup_logs(
    retention_days: Optional[int] = Query(default=None, ge=1, le=3650),
    dry_run: bool = Query(default=False),
) -> MonitoringCleanupOut:
    cfg = get_settings()
    home = monitoring.resolve_home(cfg)
    log_dir = monitoring.resolve_log_dir(cfg, home)
    if log_dir is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="log dir not configured")
    result = monitoring.cleanup_log_files(
        log_dir,
        retention_days=int(retention_days or cfg.MONITOR_LOG_RETENTION_DAYS),
        dry_run=dry_run,
    )
    result["dryRun"] = dry_run
    return MonitoringCleanupOut(**result)
