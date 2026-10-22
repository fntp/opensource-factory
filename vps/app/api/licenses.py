"""License 合规接口（M6-06）。

- `GET /api/licenses/catalog`：许可证目录与分类口径；
- `GET /api/licenses/summary`：收藏库 / 热榜 / 全部的 License 与风险分布。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import MyRepository, TrendingRepository
from app.services.license import catalog_payload, summarize_license_rows

router = APIRouter(prefix="/api/licenses", tags=["licenses"])


@router.get("/catalog", summary="License 目录与合规分级口径")
def get_license_catalog() -> dict[str, Any]:
    return catalog_payload()


@router.get("/summary", summary="License / 风险分布统计")
def get_license_summary(
    db: Session = Depends(get_db),
    scope: str = Query(default="all", pattern="^(my|trending|all)$"),
) -> dict[str, Any]:
    rows: list[tuple[str | None, str | None, str | None]] = []
    if scope in ("my", "all"):
        rows.extend(
            db.execute(
                select(
                    MyRepository.license_spdx,
                    MyRepository.license_name,
                    MyRepository.license_source,
                )
            ).all()
        )
    if scope in ("trending", "all"):
        rows.extend(
            db.execute(
                select(
                    TrendingRepository.license_spdx,
                    TrendingRepository.license_name,
                    TrendingRepository.license_source,
                )
            ).all()
        )

    data = summarize_license_rows((row[0], row[1]) for row in rows)
    checked = sum(1 for row in rows if row[2])
    data.update(
        {
            "scope": scope,
            "checked": checked,
            "unchecked": max(0, data["total"] - checked),
        }
    )
    return data
