#!/usr/bin/env python3
"""M6 验收 · 检索与知识库深化端到端走查（零额外依赖）。

在临时运行目录 + 临时 SQLite 上启动真实 `uvicorn`，逐项验证 M6 已交付能力，
并对平台仍为 pending 的 M6-09~11 输出缺口状态：

    M6-01 全文检索（README 镜像 / FTS5 / 状态 / 重建 / 短词回退）
    M6-02 相似推荐（种子向量 / 近邻 / 缺失语义）
    M6-03 重复检测（名称 / 简介 / 向量 / 合并建议）
    M6-04 技术栈图谱（edge 路由 + admin 页面 + 纯函数单测资产）
    M6-05 项目健康度（列表 / 汇总 / 单仓库 / 刷新入队）
    M6-06 License 合规（目录 / 汇总 / 单仓库提示）
    M6-07 依赖分析（聚合 / 扫描接口 / 语言关联）
    M6-08 知识库导出（edge 路由 + admin 页面 + 格式规范）
    M6-09~11 缺口检查（多轮问答 / 检索体验 / 主题聚类）

用法（在 vps/ 下）：

    python scripts/m6_acceptance.py
    python scripts/m6_acceptance.py --strict
    python scripts/m6_acceptance.py --report-md docs/planning/acceptance-m6-report.md \
        --report-json docs/planning/acceptance-m6-report.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib import error, request

VPS_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = VPS_ROOT.parent
sys.path.insert(0, str(VPS_ROOT))

TMP_DIR = Path(tempfile.mkdtemp(prefix="m6-acceptance-"))
DB_PATH = TMP_DIR / "m6.db"
INTERNAL_TOKEN = "e2e-m6-internal-token"

os.environ.update(
    {
        "DATABASE_URL": f"sqlite:///{DB_PATH}",
        "INTERNAL_TOKEN": INTERNAL_TOKEN,
        "FTS_ENABLED": "1",
        "RATE_LIMIT_ENABLED": "0",
        "REPO_HEALTH_ENABLED": "0",
        "CELERY_TASK_ALWAYS_EAGER": "1",
        "LOG_LEVEL": "WARNING",
        "EMBEDDING_FORCE_FALLBACK": "1",
    }
)

RESULTS: list[dict[str, object]] = []


# ---------------------------------------------------------------------------
# HTTP / 断言 / 结果记录
# ---------------------------------------------------------------------------
def http_json(
    base: str,
    path: str,
    *,
    method: str = "GET",
    body: dict | None = None,
    token: str | None = INTERNAL_TOKEN,
) -> tuple[int, object, str, float]:
    headers = {"Accept": "application/json"}
    if token:
        headers["X-Internal-Token"] = token
    data = None
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = request.Request(f"{base}{path}", data=data, headers=headers, method=method)
    started = time.perf_counter()
    try:
        with request.urlopen(req, timeout=60) as resp:
            text = resp.read().decode("utf-8")
            status = resp.status
    except error.HTTPError as exc:
        text = exc.read().decode("utf-8", errors="replace")
        status = exc.code
    duration_ms = (time.perf_counter() - started) * 1000
    try:
        payload = json.loads(text) if text else None
    except json.JSONDecodeError:
        payload = None
    return status, payload, text, duration_ms


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def assert_equal(actual: object, expected: object, label: str) -> None:
    if actual != expected:
        raise AssertionError(f"{label}：期望 {expected!r}，实际 {actual!r}")


def check(cid: str, title: str, fn, *args) -> None:
    started = time.perf_counter()
    try:
        detail = fn(*args) or ""
        RESULTS.append(
            {
                "id": cid,
                "title": title,
                "status": "PASS",
                "detail": str(detail),
                "durationMs": round((time.perf_counter() - started) * 1000, 1),
            }
        )
        print(f"  ✔ [PASS] {title}" + (f" — {detail}" if detail else ""))
    except Exception as exc:  # noqa: BLE001 - 单项失败不影响其余检查
        RESULTS.append(
            {
                "id": cid,
                "title": title,
                "status": "FAIL",
                "detail": str(exc),
                "durationMs": round((time.perf_counter() - started) * 1000, 1),
            }
        )
        print(f"  ✖ [FAIL] {title} — {exc}")


def gap(cid: str, title: str, detail: str) -> None:
    RESULTS.append(
        {"id": cid, "title": title, "status": "GAP", "detail": detail, "durationMs": 0.0}
    )
    print(f"  ○ [GAP ] {title} — {detail}")


# ---------------------------------------------------------------------------
# 种子数据
# ---------------------------------------------------------------------------
def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _dep_id(repo_id: str, ecosystem: str, name: str, kind: str) -> str:
    raw = f"{repo_id}|{ecosystem}|{name}|{kind}".encode("utf-8")
    return hashlib.sha1(raw).hexdigest()[:16]


def seed_database() -> None:
    from app.db import SessionLocal, init_db
    from app.models import (
        MyRepository,
        RepoDependency,
        RepoDependencyScan,
        RepoReadme,
        RepoVector,
    )

    init_db()
    now = _now()
    db = SessionLocal()
    try:
        db.add_all(
            [
                MyRepository(
                    id="acme/payment-kit",
                    name="payment-kit",
                    description="支付 SDK：统一收单、结算与对账",
                    html_url="https://github.com/acme/payment-kit",
                    stars=1200,
                    language="Python",
                    readme_summary="统一支付、结算与对账 SDK",
                    license_spdx="MIT",
                    license_name="MIT License",
                    license_source="github",
                    license_checked_at=now,
                    pushed_at=now - timedelta(days=10),
                    updated_at=now - timedelta(days=10),
                    open_issues_count=3,
                ),
                MyRepository(
                    id="acme/payment-kit-js",
                    name="payment-kit-js",
                    description="支付 SDK：统一收单、结算与对账（TypeScript 版）",
                    html_url="https://github.com/acme/payment-kit-js",
                    stars=300,
                    language="TypeScript",
                    readme_summary="支付 SDK 的 TypeScript 实现",
                    license_spdx="MIT",
                    license_name="MIT License",
                    license_source="readme",
                    license_checked_at=now,
                    pushed_at=now - timedelta(days=20),
                    updated_at=now - timedelta(days=20),
                    open_issues_count=1,
                ),
                MyRepository(
                    id="acme/legacy-ui",
                    name="legacy-ui",
                    description="旧版管理后台",
                    html_url="https://github.com/acme/legacy-ui",
                    stars=50,
                    language="JavaScript",
                    readme_summary="旧版管理后台",
                    license_spdx="Apache-2.0",
                    license_name="Apache License 2.0",
                    license_source="github",
                    license_checked_at=now,
                    pushed_at=now - timedelta(days=400),
                    updated_at=now - timedelta(days=400),
                    archived=True,
                ),
                MyRepository(
                    id="acme/agent-framework",
                    name="agent-framework",
                    description="LLM Agent 框架：工具调用与记忆",
                    html_url="https://github.com/acme/agent-framework",
                    stars=800,
                    language="Python",
                    readme_summary="构建带工具与记忆的 LLM Agent",
                    license_spdx="AGPL-3.0",
                    license_name="GNU Affero General Public License 3.0",
                    license_source="github",
                    license_checked_at=now,
                    pushed_at=now - timedelta(days=200),
                    updated_at=now - timedelta(days=200),
                    open_issues_count=200,
                ),
            ]
        )
        db.add_all(
            [
                RepoReadme(
                    source="my",
                    repo_id="acme/payment-kit",
                    content="# Payment Kit\n\n统一支付、结算与对账 SDK，支持微信支付与支付宝。",
                    content_hash="m6-payment-kit",
                    char_count=42,
                ),
                RepoReadme(
                    source="my",
                    repo_id="acme/payment-kit-js",
                    content="# Payment Kit JS\n\n支付 SDK 的 TypeScript 实现，覆盖结算与对账。",
                    content_hash="m6-payment-kit-js",
                    char_count=44,
                ),
                RepoReadme(
                    source="my",
                    repo_id="acme/agent-framework",
                    content="# Agent Framework\n\nBuild LLM agents with tools and memory.",
                    content_hash="m6-agent-framework",
                    char_count=48,
                ),
            ]
        )
        db.add_all(
            [
                RepoVector(
                    source="my",
                    repo_id="acme/payment-kit",
                    model="bge-m3",
                    backend="hash",
                    dim=3,
                    text_hash="m6-vec-payment",
                    vector="[1.0, 0.0, 0.0]",
                ),
                RepoVector(
                    source="my",
                    repo_id="acme/payment-kit-js",
                    model="bge-m3",
                    backend="hash",
                    dim=3,
                    text_hash="m6-vec-payment-js",
                    vector="[0.98, 0.15, 0.0]",
                ),
                RepoVector(
                    source="my",
                    repo_id="acme/agent-framework",
                    model="bge-m3",
                    backend="hash",
                    dim=3,
                    text_hash="m6-vec-agent",
                    vector="[0.0, 1.0, 0.0]",
                ),
            ]
        )
        deps = [
            ("acme/payment-kit", "pypi", "requests", "2.32.0", "runtime", "requirements.txt"),
            ("acme/payment-kit", "pypi", "pydantic", "2.8.0", "runtime", "requirements.txt"),
            ("acme/payment-kit", "pypi", "pytest", "8.3.0", "dev", "requirements-dev.txt"),
            ("acme/agent-framework", "pypi", "httpx", "0.27.0", "runtime", "pyproject.toml"),
            ("acme/agent-framework", "pypi", "pydantic", "2.8.0", "runtime", "pyproject.toml"),
            ("acme/agent-framework", "npm", "zod", "3.23.0", "runtime", "package.json"),
        ]
        db.add_all(
            [
                RepoDependency(
                    id=_dep_id(repo_id, eco, name, kind),
                    repo_id=repo_id,
                    ecosystem=eco,
                    name=name,
                    version=version,
                    kind=kind,
                    manifest=manifest,
                )
                for repo_id, eco, name, version, kind, manifest in deps
            ]
        )
        db.add_all(
            [
                RepoDependencyScan(
                    repo_id="acme/payment-kit",
                    status="ok",
                    manifests="requirements.txt,requirements-dev.txt",
                    dependency_count=3,
                ),
                RepoDependencyScan(
                    repo_id="acme/agent-framework",
                    status="ok",
                    manifests="pyproject.toml,package.json",
                    dependency_count=3,
                ),
            ]
        )
        db.commit()
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 运行时检查
# ---------------------------------------------------------------------------
def check_fts_schema() -> str:
    with sqlite3.connect(DB_PATH) as conn:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        triggers = {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='trigger'")
        }
        fts_count = conn.execute("SELECT count(*) FROM repo_readme_fts").fetchone()[0]
    assert_true("repo_readmes" in tables, "缺少 repo_readmes 表")
    assert_true("repo_readme_fts" in tables, "缺少 repo_readme_fts 虚表")
    for name in ("repo_readmes_ai", "repo_readmes_au", "repo_readmes_ad"):
        assert_true(name in triggers, f"缺少 FTS 触发器 {name}")
    assert_true(int(fts_count) >= 3, f"FTS 文档数不足：{fts_count}")
    return f"3 个触发器；FTS 文档 {fts_count}"


def check_fulltext_chinese(base: str) -> str:
    status, payload, text, _ = http_json(
        base, "/api/search/fulltext", method="POST", body={"query": "支付", "scope": "all", "topK": 10}
    )
    assert_equal(status, 200, f"HTTP 状态（{text[:200]}）")
    data = payload if isinstance(payload, dict) else {}
    assert_true(data.get("count", 0) >= 2, f"命中数不足：{data.get('count')}")
    ids = {item.get("id") for item in data.get("items", [])}
    assert_true("acme/payment-kit" in ids, f"未命中 payment-kit：{ids}")
    assert_true(data.get("mode") in ("fts", "like"), f"非法 mode：{data.get('mode')}")
    return f"mode={data.get('mode')} count={data.get('count')}"


def check_fulltext_english_status(base: str) -> str:
    status, payload, text, _ = http_json(
        base, "/api/search/fulltext", method="POST", body={"query": "payment", "scope": "my"}
    )
    assert_equal(status, 200, f"HTTP 状态（{text[:200]}）")
    data = payload if isinstance(payload, dict) else {}
    assert_true(data.get("count", 0) >= 2, f"命中数不足：{data.get('count')}")
    assert_equal(data.get("mode"), "fts", "英文长词应走 FTS")
    status, stats, text, _ = http_json(base, "/api/search/fulltext/status")
    assert_equal(status, 200, f"状态接口 HTTP（{text[:200]}）")
    stats = stats if isinstance(stats, dict) else {}
    assert_true(stats.get("enabled") is True, "FTS 未启用")
    assert_true(stats.get("totalDocs", 0) >= 3, f"镜像文档不足：{stats.get('totalDocs')}")
    assert_true(stats.get("ftsDocs", 0) >= 3, f"FTS 文档不足：{stats.get('ftsDocs')}")
    return f"count={data.get('count')} docs={stats.get('totalDocs')}"


def check_fulltext_rebuild(base: str) -> str:
    status, payload, text, _ = http_json(
        base, "/api/search/fulltext/rebuild", method="POST", body={}
    )
    assert_equal(status, 200, f"重建 HTTP（{text[:200]}）")
    data = payload if isinstance(payload, dict) else {}
    assert_true(int(data.get("rebuilt", 0)) >= 3, f"重建数量不足：{data.get('rebuilt')}")
    status, payload, text, _ = http_json(
        base, "/api/search/fulltext", method="POST", body={"query": "对账", "scope": "all"}
    )
    assert_equal(status, 200, f"重建后检索 HTTP（{text[:200]}）")
    assert_true((payload or {}).get("count", 0) >= 1, "重建后检索无命中")
    return f"rebuilt={data.get('rebuilt')}"


def check_similar_hits(base: str) -> str:
    status, payload, text, _ = http_json(
        base,
        "/api/search/similar",
        method="POST",
        body={"source": "my", "repoId": "acme/payment-kit", "topK": 5, "scope": "my"},
    )
    assert_equal(status, 200, f"HTTP 状态（{text[:200]}）")
    data = payload if isinstance(payload, dict) else {}
    assert_true(data.get("count", 0) >= 1, f"近邻数不足：{data.get('count')}")
    first = (data.get("items") or [{}])[0]
    assert_equal(first.get("repoId"), "acme/payment-kit-js", "Top1 近邻")
    assert_true(float(first.get("score", 0)) > 0.9, f"相似度偏低：{first.get('score')}")
    return f"top1={first.get('repoId')} score={first.get('score')}"


def check_similar_errors(base: str) -> str:
    status, _payload, _text, _ = http_json(
        base,
        "/api/search/similar",
        method="POST",
        body={"source": "my", "repoId": "acme/not-found", "topK": 3},
    )
    assert_equal(status, 404, "不存在种子应返回 404")
    status, _payload, _text, _ = http_json(
        base,
        "/api/search/similar",
        method="POST",
        body={"source": "my", "repoId": "acme/legacy-ui", "topK": 3},
    )
    assert_equal(status, 409, "未向量化种子应返回 409")
    return "404 / 409 语义正确"


def check_duplicate_clusters(base: str) -> str:
    status, payload, text, _ = http_json(
        base,
        "/api/duplicates/scan",
        method="POST",
        body={
            "scope": "my",
            "myRepoIds": [
                "acme/payment-kit",
                "acme/payment-kit-js",
                "acme/legacy-ui",
                "acme/agent-framework",
            ],
        },
    )
    assert_equal(status, 200, f"HTTP 状态（{text[:200]}）")
    data = payload if isinstance(payload, dict) else {}
    clusters = data.get("clusters") or []
    assert_true(len(clusters) >= 1, "未发现重复簇")
    cluster = clusters[0]
    member_ids = {item.get("repoId") for item in cluster.get("members", [])}
    assert_true(
        {"acme/payment-kit", "acme/payment-kit-js"} <= member_ids,
        f"重复簇成员不符：{member_ids}",
    )
    suggestion = cluster.get("suggestion") or {}
    assert_true(bool(suggestion.get("keep")), "缺少保留项建议")
    assert_true(bool(suggestion.get("fields")), "缺少字段合并建议")
    return f"clusters={len(clusters)} confidence={cluster.get('confidence')}"


def check_health_list(base: str) -> str:
    status, payload, text, _ = http_json(base, "/api/repos/health")
    assert_equal(status, 200, f"HTTP 状态（{text[:200]}）")
    data = payload if isinstance(payload, dict) else {}
    summary = data.get("summary") or {}
    items = data.get("items") or []
    assert_true(summary.get("total", 0) >= 4, f"汇总总数不足：{summary.get('total')}")
    statuses = {item.get("status") for item in items}
    for expected in ("active", "stale", "archived"):
        assert_true(expected in statuses, f"缺少健康度状态 {expected}：{statuses}")
    return f"total={summary.get('total')} statuses={sorted(statuses)}"


def check_health_detail(base: str) -> str:
    status, payload, text, _ = http_json(base, "/api/repos/acme/payment-kit/health")
    assert_equal(status, 200, f"HTTP 状态（{text[:200]}）")
    data = payload if isinstance(payload, dict) else {}
    assert_equal(data.get("status"), "active", "payment-kit 健康度")
    assert_true(int(data.get("score", 0)) > 0, f"分数异常：{data.get('score')}")
    assert_true(bool(data.get("reasons")), "缺少健康度理由")
    return f"status={data.get('status')} score={data.get('score')}"


def check_health_refresh(base: str) -> str:
    status, payload, text, _ = http_json(
        base,
        "/api/repos/health/refresh",
        method="POST",
        body={"repoIds": ["acme/payment-kit"], "limit": 10},
    )
    assert_equal(status, 202, f"HTTP 状态（{text[:200]}）")
    data = payload if isinstance(payload, dict) else {}
    assert_true(bool(data.get("taskId")), "缺少 taskId")
    return f"taskId={data.get('taskId')}"


def check_license_catalog(base: str) -> str:
    status, payload, text, _ = http_json(base, "/api/licenses/catalog", token=None)
    assert_equal(status, 200, f"HTTP 状态（{text[:200]}）")
    data = payload if isinstance(payload, dict) else {}
    assert_true(len(data.get("categories") or []) >= 5, "分类数量不足")
    assert_true(len(data.get("licenses") or []) >= 10, "目录条目不足")
    return f"categories={len(data.get('categories') or [])} licenses={len(data.get('licenses') or [])}"


def check_license_summary(base: str) -> str:
    status, payload, text, _ = http_json(base, "/api/licenses/summary?scope=my")
    assert_equal(status, 200, f"HTTP 状态（{text[:200]}）")
    data = payload if isinstance(payload, dict) else {}
    assert_equal(data.get("total"), 4, "收藏库 License 总数")
    assert_equal(data.get("known"), 4, "已识别 License 数")
    risk = data.get("riskCounts") or {}
    assert_true(risk.get("high", 0) >= 1, f"AGPL 高风险未计入：{risk}")
    names = {item.get("spdxId") for item in data.get("licenses", [])}
    assert_true({"MIT", "Apache-2.0", "AGPL-3.0"} <= names, f"License 分布不符：{names}")
    return f"total={data.get('total')} high={risk.get('high')}"


def check_license_detail(base: str) -> str:
    status, payload, text, _ = http_json(base, "/api/repos/acme/payment-kit/license")
    assert_equal(status, 200, f"HTTP 状态（{text[:200]}）")
    data = payload if isinstance(payload, dict) else {}
    assert_equal(data.get("spdxId"), "MIT", "SPDX")
    assert_equal(data.get("category"), "permissive", "分类")
    assert_equal(data.get("riskLevel"), "low", "风险")
    assert_true(bool(data.get("obligations")), "缺少义务说明")
    return f"{data.get('spdxId')} / {data.get('category')} / {data.get('riskLevel')}"


def check_dependency_aggregate(base: str) -> str:
    status, payload, text, _ = http_json(
        base,
        "/api/analysis/dependencies?repoIds=acme/payment-kit,acme/agent-framework&top=20",
    )
    assert_equal(status, 200, f"HTTP 状态（{text[:200]}）")
    data = payload if isinstance(payload, dict) else {}
    summary = data.get("summary") or {}
    assert_equal(summary.get("repos"), 2, "参与聚合仓库数")
    assert_equal(summary.get("dependencyRows"), 6, "依赖行数")
    assert_true(summary.get("uniqueDependencies", 0) >= 4, "去重依赖数不足")
    deps = {item.get("name") for item in data.get("dependencies", [])}
    assert_true({"requests", "pydantic", "zod"} <= deps, f"依赖列表不符：{deps}")
    assert_true(len(data.get("links") or []) >= 1, "缺少依赖 × 语言关联")
    return f"repos={summary.get('repos')} rows={summary.get('dependencyRows')}"


def check_dependency_refresh(base: str) -> str:
    status, payload, text, _ = http_json(
        base,
        "/api/analysis/dependencies/refresh",
        method="POST",
        body={"repoIds": ["acme/not-found"], "force": False, "limit": 1},
    )
    assert_equal(status, 200, f"HTTP 状态（{text[:200]}）")
    data = payload if isinstance(payload, dict) else {}
    assert_equal(data.get("scanned"), 0, "不存在的仓库不应被扫描")
    return f"status={data.get('status')} scanned={data.get('scanned')}"


# ---------------------------------------------------------------------------
# 静态检查（edge / admin / 文档）
# ---------------------------------------------------------------------------
def _read(relative: str) -> str:
    path = REPO_ROOT / relative
    assert_true(path.exists(), f"缺少文件：{relative}")
    return path.read_text(encoding="utf-8")


def check_tech_stack_assets() -> str:
    route = _read("edge/src/routes/tech-stack.ts")
    assert_true("/api/tech-stack" in route or "tech-stack" in route, "edge 路由内容异常")
    _read("edge/src/tech-stack/aggregate.ts")
    _read("edge/src/tech-stack/catalog.ts")
    page = _read("admin/src/features/tech-stack/index.tsx")
    assert_true("技术栈" in page, "admin 技术栈页面内容异常")
    _read("admin/src/routes/_authenticated/tech-stack/index.tsx")
    _read("admin/src/features/tech-stack/tech-stack.test.ts")
    return "edge 聚合 + admin 页面 + 单测齐全"


def check_export_assets() -> str:
    route = _read("edge/src/routes/export.ts")
    assert_true("/knowledge" in route, "edge 导出路由缺失")
    builder = _read("edge/src/export/build.ts")
    assert_true("openfactory.knowledge.v1" in builder, "缺少导出格式版本")
    assert_true("obsidian" in builder.lower(), "缺少 Obsidian 导出实现")
    page = _read("admin/src/features/export/index.tsx")
    assert_true("知识库导出" in page or "导出" in page, "admin 导出页内容异常")
    _read("admin/src/features/export/export.test.ts")
    guide = _read("docs/guides/knowledge-export.md")
    assert_true("openfactory.knowledge.v1" in guide, "格式规范缺少版本号")
    return "edge 导出 + admin 页面 + 格式规范齐全"


def check_m6_frontend_pages() -> str:
    for path in (
        "admin/src/features/duplicates/index.tsx",
        "admin/src/features/licenses/index.tsx",
        "admin/src/features/dependencies/index.tsx",
        "admin/src/features/repos/index.tsx",
    ):
        _read(path)
    return "重复检测 / License / 依赖分析 / 仓库健康度页面齐全"


def check_gaps() -> None:
    branches = {
        "M6-09": ("feat/req-202610-0956-conversational-search", "多轮问答式检索"),
        "M6-10": ("feat/req-202610-0957-search-ux", "检索体验精修"),
        "M6-11": ("feat/req-202610-0958-theme-clustering", "主题聚类与自动标签"),
    }
    for cid, (branch, title) in branches.items():
        try:
            ahead = int(
                subprocess.run(
                    ["git", "rev-list", "--count", f"HEAD..{branch}"],
                    cwd=REPO_ROOT,
                    capture_output=True,
                    text=True,
                    timeout=15,
                    check=True,
                ).stdout.strip()
                or 0
            )
            result = subprocess.run(
                ["git", "merge-base", "--is-ancestor", branch, "HEAD"],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                timeout=15,
            )
            merged = ahead > 0 and result.returncode == 0
        except Exception:  # noqa: BLE001 - 分支不存在按缺口处理
            merged = False
        if merged:
            RESULTS.append(
                {
                    "id": f"{cid}-GAP",
                    "title": f"{title}（已合并，待平台状态确认）",
                    "status": "PASS",
                    "detail": f"{branch} 已包含在验收分支",
                    "durationMs": 0.0,
                }
            )
        else:
            gap(
                f"{cid}-GAP",
                f"{title}（平台 pending）",
                f"{branch} 未合并，需该需求交付后补充验收",
            )


def run_static_checks() -> None:
    check("M6-S01", "M6-04 技术栈图谱资产", check_tech_stack_assets)
    check("M6-S02", "M6-08 知识库导出资产", check_export_assets)
    check("M6-S03", "M6 前端页面齐全", check_m6_frontend_pages)
    check_gaps()


def run_runtime_checks(base: str) -> None:
    check("M6-A01", "M6-01 FTS5 虚表与触发器", check_fts_schema)
    check("M6-A02", "M6-01 中文短词检索（LIKE 回退）", check_fulltext_chinese, base)
    check("M6-A03", "M6-01 英文长词 FTS + 索引状态", check_fulltext_english_status, base)
    check("M6-A04", "M6-01 索引重建", check_fulltext_rebuild, base)
    check("M6-B01", "M6-02 相似推荐近邻", check_similar_hits, base)
    check("M6-B02", "M6-02 种子缺失语义", check_similar_errors, base)
    check("M6-C01", "M6-03 重复检测与合并建议", check_duplicate_clusters, base)
    check("M6-D01", "M6-05 健康度列表与汇总", check_health_list, base)
    check("M6-D02", "M6-05 单仓库健康度", check_health_detail, base)
    check("M6-D03", "M6-05 健康度刷新入队", check_health_refresh, base)
    check("M6-E01", "M6-06 License 目录", check_license_catalog, base)
    check("M6-E02", "M6-06 License 汇总与风险", check_license_summary, base)
    check("M6-E03", "M6-06 单仓库 License 提示", check_license_detail, base)
    check("M6-F01", "M6-07 依赖分析聚合", check_dependency_aggregate, base)
    check("M6-F02", "M6-07 依赖扫描接口", check_dependency_refresh, base)


# ---------------------------------------------------------------------------
# 服务生命周期 / 报告
# ---------------------------------------------------------------------------
def get_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def wait_for_health(base: str, process: subprocess.Popen, timeout: float = 60.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if process.poll() is not None:
            output = process.stdout.read() if process.stdout is not None else ""
            raise RuntimeError(f"uvicorn 提前退出（code={process.returncode}）：\n{output[-3000:]}")
        try:
            status, _payload, _text, _ = http_json(base, "/healthz", token=None)
            if status == 200:
                return
        except Exception:  # noqa: BLE001 - 尚未就绪
            pass
        time.sleep(0.3)
    raise RuntimeError("等待 uvicorn 就绪超时")


def start_server() -> tuple[subprocess.Popen, str]:
    port = get_free_port()
    base = f"http://127.0.0.1:{port}"
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-level",
            "warning",
        ],
        cwd=VPS_ROOT,
        env=dict(os.environ),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    wait_for_health(base, process)
    return process, base


def stop_server(process: subprocess.Popen | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()


def summarize() -> dict[str, int]:
    counts = {"PASS": 0, "FAIL": 0, "GAP": 0}
    for item in RESULTS:
        status = str(item["status"])
        counts[status] = counts.get(status, 0) + 1
    return counts


def git_info() -> tuple[str, str]:
    try:
        branch = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        commit = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        return branch, commit
    except Exception:  # noqa: BLE001 - 报告不因 git 缺失失败
        return "unknown", "unknown"


def build_markdown(meta: dict[str, str]) -> str:
    rows = "\n".join(
        f"| {item['id']} | {item['title']} | {item['status']} | {item['detail']} | {item['durationMs']}ms |"
        for item in RESULTS
    )
    summary = summarize()
    if summary["FAIL"]:
        conclusion = "存在失败项，M6 验收不通过"
    elif summary["GAP"]:
        conclusion = (
            "M6-01~08 已交付能力全部通过；M6-09~11 平台状态仍为 pending，"
            "本轮判定为部分验收（有条件通过）"
        )
    else:
        conclusion = "全部通过，M6 验收通过"
    return f"""# M6 验收报告（自动生成）

- 生成时间：{meta['finishedAt']}
- 分支 / 提交：{meta['branch']} / {meta['commit']}
- 运行环境：{meta['platform']} · Python {meta['python']}
- 验收方式：临时 SQLite + 真实 uvicorn + API 契约检查 + edge / admin 资产静态检查
- 判定口径：PASS 通过 · FAIL 行为错误 · GAP 未交付缺口（不计入通过率）

## 检查结果

| # | 检查 | 结果 | 说明 | 耗时 |
| --- | --- | --- | --- | --- |
{rows}

## 汇总

- PASS：{summary['PASS']}
- FAIL：{summary['FAIL']}
- GAP：{summary['GAP']}
- 结论：{conclusion}
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="M6 验收脚本")
    parser.add_argument("--strict", action="store_true", help="存在 GAP 或 FAIL 时返回非零")
    parser.add_argument("--keep", action="store_true", help="保留临时目录")
    parser.add_argument("--report-md", default=None, help="Markdown 报告输出路径")
    parser.add_argument("--report-json", default=None, help="JSON 报告输出路径")
    args = parser.parse_args()

    server = None
    try:
        print("• 种入 M6 验收数据…")
        seed_database()

        print("• 静态资产检查…")
        run_static_checks()

        print("• 启动主服务（检索 / 健康度 / License / 依赖）…")
        server, base = start_server()
        print(f"  · {base}")
        run_runtime_checks(base)
        stop_server(server)
        server = None

        summary = summarize()
        print(f"\n汇总：PASS {summary['PASS']} · FAIL {summary['FAIL']} · GAP {summary['GAP']}")

        branch, commit = git_info()
        meta = {
            "branch": branch,
            "commit": commit,
            "finishedAt": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "platform": platform.platform(),
            "python": platform.python_version(),
        }
        if args.report_md:
            target = (REPO_ROOT / args.report_md).resolve()
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(build_markdown(meta), encoding="utf-8")
            print(f"• 已写入 Markdown 报告：{target}")
        if args.report_json:
            target = (REPO_ROOT / args.report_json).resolve()
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(
                json.dumps({"meta": meta, "results": RESULTS}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            print(f"• 已写入 JSON 报告：{target}")

        if summary["FAIL"] > 0 or (args.strict and summary["GAP"] > 0):
            return 1
        return 0
    finally:
        stop_server(server)
        if args.keep:
            print(f"• 保留临时目录：{TMP_DIR}")
        else:
            shutil.rmtree(TMP_DIR, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
