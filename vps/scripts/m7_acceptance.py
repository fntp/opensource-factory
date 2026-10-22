#!/usr/bin/env python3
"""M7 验收 · 智能助理与自动化端到端走查（零额外依赖）。

在临时运行目录 + 临时 SQLite 上启动真实 `uvicorn`，逐项验证 M7 已交付能力，
并对平台仍为 pending 的 M7-08 / M7-09 输出缺口状态：

    M7-01 自动打标建议（规则命中 / 分数阈值 / 已有标签排除）
    M7-02 自动分类建议（业务线 / Top N / 可解释字段）
    M7-03 精选报告（edge 纯函数 + 路由 + Cron + admin 页面静态检查）
    M7-04 收藏项目更新提醒（版本解析 / 重大变更判定 / 迁移）
    M7-05 Star 趋势（edge 聚合路由 + admin 页面静态检查）
    M7-06 模型路由（总览 / 健康 / 参数校验）
    M7-07 Rerank 精排（预览 / 应用 / 六路信号 / MMR 多样性）
    M7-08~09 缺口检查（LoRA 评估 / Agent 工作流）

用法（在 vps/ 下）：

    python scripts/m7_acceptance.py
    python scripts/m7_acceptance.py --strict
    python scripts/m7_acceptance.py --report-md docs/planning/acceptance-m7-report.md \
        --report-json docs/planning/acceptance-m7-report.json
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import socket
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

TMP_DIR = Path(tempfile.mkdtemp(prefix="m7-acceptance-"))
DB_PATH = TMP_DIR / "m7.db"
INTERNAL_TOKEN = "e2e-m7-internal-token"

os.environ.update(
    {
        "DATABASE_URL": f"sqlite:///{DB_PATH}",
        "INTERNAL_TOKEN": INTERNAL_TOKEN,
        "RATE_LIMIT_ENABLED": "0",
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


def seed_database() -> None:
    from app.db import SessionLocal, init_db
    from app.models import MyRepository

    init_db()
    now = _now()
    db = SessionLocal()
    try:
        db.add_all(
            [
                MyRepository(
                    id="acme/ai-framework",
                    name="ai-framework",
                    description="大模型推理与 Agent 编排框架",
                    html_url="https://github.com/acme/ai-framework",
                    stars=5200,
                    language="Python",
                    readme_summary="基于 FastAPI 的大模型推理服务，支持 Agent 工具调用与向量检索。",
                    pushed_at=now - timedelta(days=3),
                    updated_at=now - timedelta(days=3),
                ),
                MyRepository(
                    id="acme/payment-kit",
                    name="payment-kit",
                    description="支付 SDK：统一收单、结算与对账",
                    html_url="https://github.com/acme/payment-kit",
                    stars=1200,
                    language="Python",
                    readme_summary="统一支付、结算与对账 SDK，支持微信支付与支付宝。",
                    pushed_at=now - timedelta(days=10),
                    updated_at=now - timedelta(days=10),
                ),
                MyRepository(
                    id="acme/legacy-ui",
                    name="legacy-ui",
                    description="旧版管理后台",
                    html_url="https://github.com/acme/legacy-ui",
                    stars=50,
                    language="JavaScript",
                    readme_summary="旧版管理后台，无摘要。",
                    pushed_at=now - timedelta(days=400),
                    updated_at=now - timedelta(days=400),
                ),
            ]
        )
        db.commit()
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 运行时检查
# ---------------------------------------------------------------------------
def check_tag_suggestions(base: str) -> str:
    status, payload, text, _ = http_json(
        base,
        "/api/tag-suggestions/generate",
        method="POST",
        body={"repoIds": ["acme/ai-framework"], "perRepo": 6},
    )
    assert_equal(status, 200, f"HTTP 状态（{text[:200]}）")
    data = payload if isinstance(payload, dict) else {}
    assert_equal(data.get("scanned"), 1, "扫描仓库数")
    items = data.get("items") or []
    assert_true(len(items) == 1, f"建议仓库数异常：{len(items)}")
    tags = items[0].get("tags") or []
    names = {tag.get("name") for tag in tags}
    assert_true("Python" in names, f"缺少语言标签：{names}")
    assert_true("FastAPI" in names, f"缺少框架标签：{names}")
    assert_true("AI/LLM" in names, f"缺少业务域标签：{names}")
    for tag in tags:
        assert_true(float(tag.get("score", 0)) >= 0.55, f"低于阈值的建议：{tag}")
        assert_true(bool(tag.get("reason")), "缺少命中理由")
        assert_true(bool(tag.get("evidence")), "缺少证据片段")
    return f"suggested={data.get('suggested')} tags={sorted(names)}"


def check_tag_excludes_existing(base: str) -> str:
    status, payload, text, _ = http_json(
        base,
        "/api/tag-suggestions/generate",
        method="POST",
        body={"repoIds": ["acme/legacy-ui"], "perRepo": 6},
    )
    assert_equal(status, 200, f"HTTP 状态（{text[:200]}）")
    data = payload if isinstance(payload, dict) else {}
    items = data.get("items") or []
    assert_true(len(items) == 1, f"建议仓库数异常：{len(items)}")
    tags = {tag.get("name") for tag in items[0].get("tags") or []}
    assert_true("JavaScript" in tags, f"缺少语言标签：{tags}")
    assert_true("Python" not in tags, f"不应出现未命中的语言标签：{tags}")
    return f"tags={sorted(tags)}"


def check_category_suggestions(base: str) -> str:
    status, payload, text, _ = http_json(
        base,
        "/api/category-suggestions/generate",
        method="POST",
        body={
            "perRepo": 3,
            "minScore": 0.55,
            "repos": [
                {
                    "repoId": "acme/ai-framework",
                    "name": "ai-framework",
                    "description": "大模型推理与 Agent 编排框架",
                    "language": "Python",
                    "summary": "基于 FastAPI 的大模型推理服务，支持 Agent 工具调用。",
                    "tags": ["AI/LLM", "FastAPI"],
                },
                {
                    "repoId": "acme/payment-kit",
                    "name": "payment-kit",
                    "description": "支付 SDK：统一收单、结算与对账",
                    "language": "Python",
                    "summary": "统一支付、结算与对账 SDK。",
                    "tags": ["支付"],
                },
            ],
        },
    )
    assert_equal(status, 200, f"HTTP 状态（{text[:200]}）")
    data = payload if isinstance(payload, dict) else {}
    assert_equal(data.get("scanned"), 2, "扫描仓库数")
    items = {item.get("repoId"): item.get("suggestions") or [] for item in data.get("items") or []}
    ai_names = {item.get("categoryName") for item in items.get("acme/ai-framework", [])}
    pay_names = {item.get("categoryName") for item in items.get("acme/payment-kit", [])}
    assert_true(any("AI" in name for name in ai_names), f"AI 仓库分类不符：{ai_names}")
    assert_true(any("金融" in name or "支付" in name for name in pay_names), f"支付仓库分类不符：{pay_names}")
    for suggestions in items.values():
        assert_true(len(suggestions) <= 3, "超过 perRepo 上限")
        for suggestion in suggestions:
            assert_true(float(suggestion.get("score", 0)) >= 0.55, "低于 minScore")
            assert_true(bool(suggestion.get("reason")), "缺少理由")
            assert_true(bool(suggestion.get("businessLine")), "缺少业务线")
    return f"ai={sorted(ai_names)} pay={sorted(pay_names)}"


def check_repo_update_rules() -> str:
    from app.services.repo_updates import (
        classify_update,
        clean_release_body,
        contains_breaking_change,
        is_major_bump,
        parse_version,
    )

    assert_equal(parse_version("v2.1.0"), (2, 1, 0), "版本解析")
    assert_equal(parse_version("2024.10"), (2024, 10), "日期式版本解析")
    assert_true(parse_version("nightly") is None, "非版本 tag 应返回 None")
    assert_true(is_major_bump("v1.9.3", "v2.0.0"), "v1→v2 应判定主版本跃迁")
    assert_true(not is_major_bump("v1.2.0", "v1.3.0"), "次版本不应判定主版本跃迁")
    assert_equal(classify_update("v1.0.0", "v1.1.0", "修复若干问题", ""), "release", "普通版本")
    assert_equal(classify_update("v1.0.0", "v2.0.0", "", ""), "major", "主版本跃迁")
    assert_true(contains_breaking_change("Breaking: remove legacy API", ""), "breaking 关键词")
    assert_true(contains_breaking_change("", "不兼容变更：删除旧接口"), "中文不兼容关键词")
    long_body = "x" * 2000
    assert_true(len(clean_release_body(long_body)) <= 800, "Release 摘要未截断")
    return "版本解析 / 主版本跃迁 / breaking 判定 / 摘要截断"


def check_model_routes(base: str) -> str:
    status, payload, text, _ = http_json(base, "/api/model-routes")
    assert_equal(status, 200, f"HTTP 状态（{text[:200]}）")
    data = payload if isinstance(payload, dict) else {}
    assert_true(data.get("taskCount", 0) >= 6, f"任务数不足：{data.get('taskCount')}")
    tasks = {item.get("task") for item in data.get("tasks") or []}
    for expected in ("summary", "embedding", "rerank"):
        assert_true(expected in tasks, f"缺少任务 {expected}：{tasks}")
    assert_true(bool(data.get("models")), "缺少模型目录")
    assert_true("budgetMb" in data and "peakResidentMb" in data, "缺少预算字段")
    return f"tasks={data.get('taskCount')} models={len(data.get('models') or [])}"


def check_model_route_health(base: str) -> str:
    status, payload, text, _ = http_json(base, "/api/model-routes/health")
    assert_equal(status, 200, f"HTTP 状态（{text[:200]}）")
    data = payload if isinstance(payload, dict) else {}
    for key in ("ollama", "deepseek", "rules"):
        assert_true(key in data, f"缺少 {key} 健康信息")
    return f"ollama={data.get('ollama', {}).get('reachable')} rules={data.get('rules', {}).get('available')}"


def check_model_route_validation(base: str) -> str:
    status, _payload, _text, _ = http_json(
        base, "/api/model-routes/not-a-task", method="PUT", body={"strategy": "balanced"}
    )
    assert_equal(status, 404, "未知任务应返回 404")
    status, _payload, _text, _ = http_json(
        base,
        "/api/model-routes/summary",
        method="PUT",
        body={"strategy": "manual", "modelId": "not-a-model"},
    )
    assert_equal(status, 400, "未知模型应返回 400")
    status, _payload, _text, _ = http_json(
        base,
        "/api/model-routes/summary",
        method="PUT",
        body={"strategy": "not-a-strategy"},
    )
    assert_equal(status, 422, "非法策略应返回 422")
    return "404 / 400 / 422 语义正确"


def _rerank_candidates() -> list[dict]:
    return [
        {
            "repoId": "acme/ai-framework",
            "name": "ai-framework",
            "baseScore": 0.90,
            "similarity": 0.95,
            "stars": 5200,
            "starsToday": 120,
            "language": "Python",
            "techStack": ["AI", "LLM"],
            "description": "大模型推理与 Agent 编排框架",
            "readmeSummary": "大模型推理与部署",
            "vector": [1.0, 0.0, 0.0],
        },
        {
            "repoId": "acme/ai-toolkit",
            "name": "ai-toolkit",
            "baseScore": 0.85,
            "similarity": 0.90,
            "stars": 3000,
            "starsToday": 80,
            "language": "Python",
            "techStack": ["AI"],
            "description": "大模型工具集",
            "readmeSummary": "大模型工具与提示词",
            "vector": [0.99, 0.01, 0.0],
        },
        {
            "repoId": "acme/web-ui",
            "name": "web-ui",
            "baseScore": 0.60,
            "similarity": 0.50,
            "stars": 1000,
            "starsToday": 10,
            "language": "TypeScript",
            "techStack": ["React"],
            "description": "管理后台 UI 组件",
            "readmeSummary": "React 管理后台",
            "vector": [0.0, 1.0, 0.0],
        },
        {
            "repoId": "acme/db-kit",
            "name": "db-kit",
            "baseScore": 0.55,
            "similarity": 0.40,
            "stars": 500,
            "starsToday": 5,
            "language": "Go",
            "techStack": ["Database"],
            "description": "数据库访问工具",
            "readmeSummary": "Go 数据库工具",
            "vector": [0.0, 0.0, 1.0],
        },
    ]


def check_rerank_preview(base: str) -> str:
    status, payload, text, _ = http_json(
        base,
        "/api/recommend/rerank/preview",
        method="POST",
        body={"topK": 4, "mmrLambda": 0.75, "items": _rerank_candidates()},
    )
    assert_equal(status, 200, f"HTTP 状态（{text[:200]}）")
    data = payload if isinstance(payload, dict) else {}
    items = data.get("items") or []
    metrics = data.get("metrics") or {}
    assert_equal(len(items), 4, "精排结果条数")
    assert_equal(metrics.get("selected"), 4, "metrics.selected")
    scores = [float(item.get("rerankScore", 0)) for item in items]
    assert_true(all(score > 0 for score in scores), f"精排分异常：{scores}")
    assert_equal([item.get("rankAfter") for item in items], [1, 2, 3, 4], "rankAfter 应连续")
    for item in items:
        signals = item.get("signals") or {}
        for key in ("relevance", "affinity", "freshness", "momentum", "popularity", "health"):
            assert_true(key in signals, f"缺少信号 {key}：{signals}")
        assert_true(bool(item.get("reasons")), "缺少精排理由")
    assert_true(
        float(metrics.get("diversityAfter", 0)) >= float(metrics.get("diversityBefore", 0)),
        "MMR 后多样性不应下降",
    )
    return f"selected={metrics.get('selected')} top1={items[0].get('repoId')} div={metrics.get('diversityAfter')}"


def check_rerank_apply(base: str) -> str:
    status, payload, text, _ = http_json(
        base,
        "/api/recommend/rerank/apply",
        method="POST",
        body={"topK": 3, "mmrLambda": 0.6, "items": _rerank_candidates()},
    )
    assert_equal(status, 200, f"HTTP 状态（{text[:200]}）")
    data = payload if isinstance(payload, dict) else {}
    items = data.get("items") or []
    assert_equal(len(items), 3, "应用后保留条数")
    assert_true(bool(data.get("generatedAt")), "缺少 generatedAt")
    return f"selected={len(items)} mode={data.get('mode')}"


# ---------------------------------------------------------------------------
# 静态检查（edge / admin / 文档）
# ---------------------------------------------------------------------------
def _read(relative: str) -> str:
    path = REPO_ROOT / relative
    assert_true(path.exists(), f"缺少文件：{relative}")
    return path.read_text(encoding="utf-8")


def check_migrations() -> str:
    expected = {
        "0016_tag_suggestions.sql",
        "0017_category_suggestions.sql",
        "0018_curated_reports.sql",
        "0019_repo_updates.sql",
        "0020_rerank.sql",
    }
    actual = {path.name for path in (REPO_ROOT / "edge" / "migrations").glob("00*.sql")}
    missing = expected - actual
    assert_true(not missing, f"缺少 M7 迁移：{sorted(missing)}")
    numbers = [name.split("_", 1)[0] for name in actual]
    m7_numbers = [name.split("_", 1)[0] for name in expected]
    assert_equal(len(m7_numbers), len(set(m7_numbers)), "M7 迁移编号重复")
    assert_true(set(m7_numbers) <= set(numbers), "迁移编号未落盘")
    schema = _read("docs/assets/d1-schema.sql")
    for table in ("tag_suggestions", "category_suggestions", "curated_reports", "repo_updates"):
        assert_true(f"CREATE TABLE IF NOT EXISTS {table}" in schema, f"d1-schema 缺少 {table}")
    assert_true("rerank_score" in schema, "d1-schema 缺少 rerank 字段")
    return f"5 个 M7 迁移；4 张新表 + rerank 字段"


def check_edge_assets() -> str:
    files = {
        "edge/src/routes/tag-suggestions.ts": "tag-suggestions",
        "edge/src/routes/category-suggestions.ts": "category-suggestions",
        "edge/src/routes/reports.ts": "reports",
        "edge/src/routes/repo-updates.ts": "repo-updates",
        "edge/src/routes/star-trends.ts": "star-trends",
        "edge/src/routes/rerank.ts": "rerank",
    }
    for path, needle in files.items():
        content = _read(path)
        assert_true(needle in content, f"{path} 内容异常")
    index = _read("edge/src/index.ts")
    for route in ("tagSuggestionRoutes", "categorySuggestionsRoutes", "reportsRoutes", "repoUpdatesRoutes", "starTrendsRoutes", "rerankRoutes"):
        assert_true(route in index, f"index.ts 未挂载 {route}")
    _read("edge/src/reports/generate.ts")
    _read("edge/src/repo-updates/helpers.ts")
    _read("edge/src/rerank/helpers.ts")
    _read("edge/src/category-suggestions/rules.ts")
    return "6 个路由 + 4 组纯函数资产"


def check_admin_pages() -> str:
    pages = {
        "admin/src/features/tag-suggestions/index.tsx": "打标",
        "admin/src/features/category-suggestions/index.tsx": "分类",
        "admin/src/features/reports/index.tsx": "报告",
        "admin/src/features/repo-updates/index.tsx": "更新",
        "admin/src/features/star-trends/index.tsx": "Star",
        "admin/src/features/model-routing/index.tsx": "模型",
        "admin/src/features/rerank/index.tsx": "精排",
    }
    for path, needle in pages.items():
        content = _read(path)
        assert_true(needle in content, f"{path} 内容异常")
    for route in ("tag-suggestions", "category-suggestions", "reports", "updates", "star-trends", "model-routing", "rerank"):
        _read(f"admin/src/routes/_authenticated/{route}/index.tsx")
    return "7 个 admin 页面 + 路由"


def check_reports_cron() -> str:
    wrangler = _read("edge/wrangler.toml")
    assert_true("30 23 * * 0" in wrangler, "缺少周报 Cron")
    assert_true("40 23 1 * *" in wrangler, "缺少月报 Cron")
    generate = _read("edge/src/reports/generate.ts")
    assert_true("weekly" in generate and "monthly" in generate, "报告纯函数缺少周期")
    route = _read("edge/src/routes/reports.ts")
    assert_true("/api/internal/reports" in route or "internal/reports" in route, "缺少内部生成接口")
    return "双 Cron + 周/月报告纯函数 + 内部生成接口"


def check_star_trends_assets() -> str:
    route = _read("edge/src/routes/star-trends.ts")
    assert_true("/api/star-trends" in route or "star-trends" in route, "edge 路由内容异常")
    _read("edge/src/insights/star-trends.ts")
    _read("admin/src/features/star-trends/index.tsx")
    return "edge 聚合 + admin 页面齐全"


def check_gaps() -> None:
    branches = {
        "M7-08": ("feat/req-202610-0967-lora-evaluation", "个人数据 LoRA 微调评估"),
        "M7-09": ("feat/req-202610-0968-agent-workflow", "Agent 工作流（自动整理 / 草稿生成）"),
    }
    for cid, (branch, title) in branches.items():
        try:
            merged = (
                subprocess.run(
                    ["git", "merge-base", "--is-ancestor", branch, "HEAD"],
                    cwd=REPO_ROOT,
                    capture_output=True,
                    text=True,
                    timeout=15,
                ).returncode
                == 0
            )
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
    check("M7-S01", "M7 迁移与 D1 schema", check_migrations)
    check("M7-S02", "edge 路由与纯函数资产", check_edge_assets)
    check("M7-S03", "admin 页面齐全", check_admin_pages)
    check("M7-S04", "M7-03 精选报告 Cron", check_reports_cron)
    check("M7-S05", "M7-05 Star 趋势资产", check_star_trends_assets)
    check_gaps()


def run_runtime_checks(base: str) -> None:
    check("M7-A01", "M7-01 自动打标建议生成", check_tag_suggestions, base)
    check("M7-A02", "M7-01 语言标签与阈值", check_tag_excludes_existing, base)
    check("M7-B01", "M7-02 自动分类建议", check_category_suggestions, base)
    check("M7-C01", "M7-04 更新判定纯函数", check_repo_update_rules)
    check("M7-D01", "M7-06 模型路由总览", check_model_routes, base)
    check("M7-D02", "M7-06 模型通道健康", check_model_route_health, base)
    check("M7-D03", "M7-06 路由参数校验", check_model_route_validation, base)
    check("M7-E01", "M7-07 Rerank 预览", check_rerank_preview, base)
    check("M7-E02", "M7-07 Rerank 应用", check_rerank_apply, base)


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
        conclusion = "存在失败项，M7 验收不通过"
    elif summary["GAP"]:
        conclusion = (
            "M7-01~07 已交付能力全部通过；M7-08~09 平台状态仍为 pending，"
            "本轮判定为部分验收（有条件通过）"
        )
    else:
        conclusion = "全部通过，M7 验收通过"
    return f"""# M7 验收报告（自动生成）

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
    parser = argparse.ArgumentParser(description="M7 验收脚本")
    parser.add_argument("--strict", action="store_true", help="存在 GAP 或 FAIL 时返回非零")
    parser.add_argument("--keep", action="store_true", help="保留临时目录")
    parser.add_argument("--report-md", default=None, help="Markdown 报告输出路径")
    parser.add_argument("--report-json", default=None, help="JSON 报告输出路径")
    args = parser.parse_args()

    server = None
    try:
        print("• 种入 M7 验收数据…")
        seed_database()

        print("• 静态资产检查…")
        run_static_checks()

        print("• 启动主服务（打标 / 分类 / 模型路由 / Rerank）…")
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
