"""License 识别与合规提示测试（M6-06，无网络）。"""
from __future__ import annotations

from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from app.db import SessionLocal, init_db
from app.main import app
from app.models import MyRepository, TrendingRepository
from app.services.github_service import normalize_repo
from app.services.license import (
    build_compliance_hint,
    catalog_payload,
    detect_license_from_readme,
    identify_github_license,
    normalize_spdx,
    summarize_license_rows,
)
from app.services.license_enrichment import enrich_licenses


def _cleanup_test_rows() -> None:
    """清掉本模块写入的仓库，避免影响推荐等依赖全库画像的测试。"""
    db = SessionLocal()
    try:
        db.execute(delete(MyRepository).where(MyRepository.id.like("license-test/%")))
        db.execute(
            delete(TrendingRepository).where(TrendingRepository.id.like("license-test/%"))
        )
        db.commit()
    finally:
        db.close()


@pytest.fixture(autouse=True)
def _ensure_tables() -> None:
    """直接使用 SessionLocal 的测试也保证表已创建，并在前后清理测试数据。"""
    init_db()
    _cleanup_test_rows()
    yield
    _cleanup_test_rows()


def test_normalize_spdx_supports_common_variants() -> None:
    assert normalize_spdx("MIT") == "MIT"
    assert normalize_spdx("mit") == "MIT"
    assert normalize_spdx("Apache 2.0") == "Apache-2.0"
    assert normalize_spdx("Apache-2.0") == "Apache-2.0"
    assert normalize_spdx("GPL-3.0") == "GPL-3.0"
    assert normalize_spdx("AGPL-3.0-only") == "AGPL-3.0"
    assert normalize_spdx("BSD 3-Clause") == "BSD-3-Clause"
    assert normalize_spdx("Unlicense") == "Unlicense"
    assert normalize_spdx("") is None
    assert normalize_spdx("NoSuchLicense-1.0") is None


def test_identify_github_license_normalizes_object() -> None:
    info = identify_github_license(
        {
            "key": "apache-2.0",
            "name": "Apache License 2.0",
            "spdx_id": "Apache-2.0",
            "url": "https://api.github.com/licenses/apache-2.0",
        }
    )
    assert info == {"spdxId": "Apache-2.0", "name": "Apache License 2.0"}
    assert identify_github_license(None) is None
    assert identify_github_license({}) is None


def test_normalize_repo_keeps_license_fields() -> None:
    normalized = normalize_repo(
        {
            "full_name": "demo/licensed",
            "name": "licensed",
            "html_url": "https://github.com/demo/licensed",
            "stargazers_count": 10,
            "forks_count": 2,
            "license": {
                "key": "mit",
                "name": "MIT License",
                "spdx_id": "MIT",
                "url": "https://api.github.com/licenses/mit",
            },
        }
    )
    assert normalized["license_spdx"] == "MIT"
    assert normalized["license_name"] == "MIT License"
    assert normalized["license_source"] == "github"

    unlicensed = normalize_repo({"full_name": "demo/unlicensed", "license": None})
    assert unlicensed["license_spdx"] == ""
    assert unlicensed["license_source"] == "none"


def test_detect_license_from_readme_priority_and_versions() -> None:
    assert detect_license_from_readme("<!-- SPDX-License-Identifier: MIT -->") == {
        "spdxId": "MIT",
        "name": "MIT License",
    }
    assert detect_license_from_readme(
        "![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)"
    ) == {"spdxId": "Apache-2.0", "name": "Apache License 2.0"}
    assert detect_license_from_readme("## License\n\nReleased under the MIT License.") == {
        "spdxId": "MIT",
        "name": "MIT License",
    }
    assert detect_license_from_readme("## License\n\nGNU General Public License v3.0") == {
        "spdxId": "GPL-3.0",
        "name": "GNU General Public License 3.0",
    }
    # 仅写 "GPL" 没有版本号时不臆测版本
    assert detect_license_from_readme("This project is GPL.") is None
    assert detect_license_from_readme("") is None


def test_build_compliance_hint_classifies_risk() -> None:
    mit = build_compliance_hint("MIT", source="github")
    assert mit["category"] == "permissive"
    assert mit["riskLevel"] == "low"
    assert mit["obligations"]
    assert mit["source"] == "github"

    agpl = build_compliance_hint("AGPL-3.0", source="readme")
    assert agpl["category"] == "network-copyleft"
    assert agpl["riskLevel"] == "high"
    assert agpl["warnings"]

    unknown = build_compliance_hint(None, None, source="none")
    assert unknown["category"] == "unknown"
    assert unknown["riskLevel"] == "unknown"
    assert "无许可证不等于可以自由使用" in unknown["warnings"]


def test_catalog_and_summary() -> None:
    catalog = catalog_payload()
    spdx_ids = {item["spdxId"] for item in catalog["licenses"]}
    assert {"MIT", "Apache-2.0", "GPL-3.0", "AGPL-3.0", "MPL-2.0"} <= spdx_ids
    assert any(category["key"] == "strong-copyleft" for category in catalog["categories"])

    summary = summarize_license_rows(
        [("MIT", "MIT License"), ("MIT", "MIT License"), ("AGPL-3.0", "AGPL"), (None, None)]
    )
    assert summary["total"] == 4
    assert summary["known"] == 3
    assert summary["unknown"] == 1
    assert summary["riskCounts"]["low"] == 2
    assert summary["riskCounts"]["high"] == 1


def test_enrich_licenses_uses_github_then_readme() -> None:
    db = SessionLocal()
    repo_github = "license-test/github-meta"
    repo_readme = "license-test/readme-fallback"
    try:
        for repo_id in (repo_github, repo_readme):
            existing = db.get(MyRepository, repo_id)
            if existing is not None:
                db.delete(existing)
        db.commit()
        db.add(
            MyRepository(
                id=repo_github,
                platform="github",
                name="github-meta",
                html_url=f"https://github.com/{repo_github}",
                stars=100,
            )
        )
        db.add(
            MyRepository(
                id=repo_readme,
                platform="github",
                name="readme-fallback",
                html_url=f"https://github.com/{repo_readme}",
                stars=50,
            )
        )
        db.commit()

        repo_calls: list[str] = []
        readme_calls: list[str] = []

        def fake_repo(token: str | None, repo_id: str):
            assert token is None
            repo_calls.append(repo_id)
            if repo_id == repo_github:
                return {"license_spdx": "Apache-2.0", "license_name": "Apache License 2.0", "license_source": "github"}
            return {"license_spdx": "", "license_name": "", "license_source": "none"}

        def fake_readme(token: str | None, repo_id: str):
            readme_calls.append(repo_id)
            if repo_id == repo_readme:
                return "## License\n\nMIT License\n\nPermission is hereby granted..."
            return ""

        enrich_licenses(
            db,
            scope="my",
            limit=100,
            token=None,
            fetch_repo=fake_repo,
            fetch_readme=fake_readme,
        )
        assert repo_github in repo_calls and repo_readme in repo_calls
        # 已通过 GitHub 识别的仓库不应再拉 README
        assert repo_github not in readme_calls

        github_row = db.get(MyRepository, repo_github)
        readme_row = db.get(MyRepository, repo_readme)
        assert github_row is not None and github_row.license_spdx == "Apache-2.0"
        assert github_row.license_source == "github"
        assert github_row.license_checked_at is not None
        assert readme_row is not None and readme_row.license_spdx == "MIT"
        assert readme_row.license_source == "readme"

        # 增量模式不重复处理已识别仓库
        before = len(repo_calls)
        enrich_licenses(
            db,
            scope="my",
            limit=100,
            token=None,
            fetch_repo=fake_repo,
            fetch_readme=fake_readme,
        )
        assert repo_github not in repo_calls[before:]
        assert repo_readme not in repo_calls[before:]

        # force 模式重新识别
        forced = enrich_licenses(
            db,
            scope="my",
            limit=100,
            force=True,
            token=None,
            fetch_repo=fake_repo,
            fetch_readme=fake_readme,
        )
        assert forced["scanned"] >= 2
        assert repo_github in repo_calls[before:]
    finally:
        db.close()


def test_license_api_catalog_summary_and_repo_hint() -> None:
    repo_id = "license-test/api-hint"
    db = SessionLocal()
    try:
        existing = db.get(MyRepository, repo_id)
        if existing is not None:
            db.delete(existing)
            db.commit()
        db.add(
            MyRepository(
                id=repo_id,
                platform="github",
                name="api-hint",
                html_url=f"https://github.com/{repo_id}",
                stars=5,
                license_spdx="GPL-3.0",
                license_name="GNU General Public License v3.0",
                license_source="github",
                license_checked_at=datetime(2026, 10, 22, 8, 0, 0),
            )
        )
        db.commit()
    finally:
        db.close()

    with TestClient(app) as client:
        catalog = client.get("/api/licenses/catalog")
        summary = client.get("/api/licenses/summary", params={"scope": "my"})
        hint = client.get(f"/api/repos/{repo_id}/license")
        missing = client.get("/api/repos/license-test/not-found-0953/license")

    assert catalog.status_code == 200
    assert len(catalog.json()["licenses"]) >= 10
    assert summary.status_code == 200
    body = summary.json()
    assert body["scope"] == "my"
    assert body["total"] >= 1
    assert any(item["spdxId"] == "GPL-3.0" for item in body["licenses"])

    assert hint.status_code == 200
    hint_body = hint.json()
    assert hint_body["spdxId"] == "GPL-3.0"
    assert hint_body["category"] == "strong-copyleft"
    assert hint_body["riskLevel"] == "high"
    assert hint_body["source"] == "github"
    assert hint_body["checkedAt"].startswith("2026-10-22T08:00:00")
    assert missing.status_code == 404


def test_trending_list_and_detail_include_license() -> None:
    repo_id = "license-test/trending-detail"
    db = SessionLocal()
    try:
        row = db.get(TrendingRepository, repo_id)
        if row is None:
            row = TrendingRepository(
                id=repo_id,
                platform="github",
                name="trending-detail",
                html_url=f"https://github.com/{repo_id}",
                stars_today=88,
                owner="license-test",
                language="Python",
                stars=1000,
                license_spdx="MIT",
                license_name="MIT License",
                license_source="github",
                license_checked_at=datetime(2026, 10, 22, 8, 0, 0),
            )
            db.add(row)
            db.commit()
    finally:
        db.close()

    with TestClient(app) as client:
        detail = client.get(f"/api/trending/{repo_id}")

    assert detail.status_code == 200
    body = detail.json()
    assert body["license"]["spdxId"] == "MIT"
    assert body["license"]["riskLevel"] == "low"
