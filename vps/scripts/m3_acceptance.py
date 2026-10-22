#!/usr/bin/env python3
"""M3 验收 · 推荐引擎端到端走查（零额外依赖）。

在独立临时 SQLite 数据库里种入收藏库 / 热榜 / 反馈数据集，启动本地 mock edge
（Vectorize 内部接口 + 推荐反馈接口）与真实 `uvicorn`，通过 HTTP 走查 M3 链路：

    M3-01 模型预算 → M3-02 向量化 → M3-03 Vectorize 同步 / 对账
    → M3-04 语义搜索 → M3-05 每日推荐 → M3-06 推荐理由
    → M3-07 反馈闭环 → M3-08 质量评估 → M3-09 降级自检
    → M3-10 查询理解

依赖说明：本机没有 BGE-M3 / Ollama 时统一使用 hash 兜底向量（256 维），
mock edge 的索引维度同步为 256；所有断言不访问外网。

用法（在 vps/ 下）：

    python scripts/m3_acceptance.py
    python scripts/m3_acceptance.py --strict
    python scripts/m3_acceptance.py --report-md docs/planning/acceptance-m3-report.md \
        --report-json docs/planning/acceptance-m3-report.json
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
import threading
import time
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib import error, parse, request

VPS_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = VPS_ROOT.parent
sys.path.insert(0, str(VPS_ROOT))

TMP_DIR = Path(tempfile.mkdtemp(prefix="m3-acceptance-"))
DB_PATH = TMP_DIR / "m3.db"
INTERNAL_TOKEN = "e2e-m3-internal-token"
PERF_SAMPLES = 30
SEARCH_P95_BUDGET_MS = 500.0
RECOMMEND_P95_BUDGET_MS = 300.0

# 必须在导入 app.* 之前设置环境变量：app.db / app.config 在模块加载时读取配置。
os.environ.update(
    {
        "DATABASE_URL": f"sqlite:///{DB_PATH}",
        "INTERNAL_TOKEN": INTERNAL_TOKEN,
        "EMBEDDING_FORCE_FALLBACK": "1",
        "MODEL_BUDGET_MB": "2048",
        "CELERY_TASK_ALWAYS_EAGER": "1",
        "RECOMMEND_FEEDBACK_SYNC": "1",
        "RECOMMEND_MIN_SCORE": "0.0",
        "RECOMMEND_DAILY_TOP_K": "10",
        "VECTORIZE_INDEX_DIM": "256",
        "VECTORIZE_SYNC_BATCH_SIZE": "7",
        "VECTORIZE_SYNC_MAX_RETRIES": "1",
        "VECTORIZE_SYNC_RETRY_BASE_MS": "10",
        "LOG_LEVEL": "WARNING",
    }
)

RESULTS: list[dict[str, object]] = []
PERF: list[dict[str, object]] = []


# ---------------------------------------------------------------------------
# mock edge：Vectorize 内部接口 + 推荐反馈接口
# ---------------------------------------------------------------------------
class EdgeState:
    """mock edge 的可观测状态。"""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.vectors: dict[str, dict] = {}
        self.vector_upserts: list[dict] = []
        self.vector_deletes: list[str] = []
        self.recommendation_upserts: list[dict] = []
        self.feedback_calls: list[str] = []
        self.feedback = {
            "savedRepoIds": ["trend/pay-lite"],
            "dismissedRepoIds": ["trend/k8s-deploy"],
            "clickedRepoIds": ["trend/react-dashboard"],
        }


EDGE = EdgeState()


class EdgeHandler(BaseHTTPRequestHandler):
    """最小 HTTP handler：只实现验收需要的内部契约。"""

    server_version = "m3-mock-edge/1.0"

    def log_message(self, *_args) -> None:  # noqa: D401 - 静默
        return

    def _send(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler 约定
        parsed = parse.urlparse(self.path)
        if parsed.path == "/api/internal/recommendations/feedback":
            user_id = parse.parse_qs(parsed.query).get("userId", [""])[0]
            with EDGE.lock:
                EDGE.feedback_calls.append(user_id)
                payload = dict(EDGE.feedback)
            self._send(200, payload)
            return
        if parsed.path == "/api/internal/vectors/stats":
            with EDGE.lock:
                count = len(EDGE.vectors)
            self._send(200, {"dimensions": 256, "count": count})
            return
        self._send(404, {"error": "not_found", "path": parsed.path})

    def do_POST(self) -> None:  # noqa: N802
        parsed = parse.urlparse(self.path)
        payload = self._read_json()
        if parsed.path == "/api/internal/vectors/upsert":
            items = payload.get("items") or []
            with EDGE.lock:
                for item in items:
                    if isinstance(item, dict) and item.get("id"):
                        EDGE.vectors[str(item["id"])] = item
                EDGE.vector_upserts.append({"count": len(items), "items": items})
            self._send(200, {"total": len(items), "upserted": len(items)})
            return
        if parsed.path == "/api/internal/vectors/delete":
            ids = [str(item) for item in (payload.get("ids") or [])]
            with EDGE.lock:
                for vector_id in ids:
                    EDGE.vectors.pop(vector_id, None)
                EDGE.vector_deletes.extend(ids)
            self._send(200, {"total": len(ids), "deleted": len(ids)})
            return
        if parsed.path == "/api/internal/vectors/check":
            ids = [str(item) for item in (payload.get("ids") or [])]
            with EDGE.lock:
                found = [vector_id for vector_id in ids if vector_id in EDGE.vectors]
            self._send(200, {"found": found, "missing": len(ids) - len(found)})
            return
        if parsed.path == "/api/internal/recommendations/upsert":
            items = payload.get("items") or []
            with EDGE.lock:
                EDGE.recommendation_upserts.append(
                    {"userId": payload.get("userId"), "items": items}
                )
            self._send(200, {"count": len(items)})
            return
        self._send(404, {"error": "not_found", "path": parsed.path})


def start_mock_edge() -> tuple[ThreadingHTTPServer, str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), EdgeHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    return server, f"http://127.0.0.1:{port}"


# ---------------------------------------------------------------------------
# HTTP / 断言工具
# ---------------------------------------------------------------------------
def http_json(
    base: str,
    path: str,
    *,
    method: str = "GET",
    body: dict | None = None,
    token: bool = False,
) -> tuple[int, object, str, float]:
    headers = {"Accept": "application/json"}
    if token:
        headers["X-Internal-Token"] = INTERNAL_TOKEN
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


def check(cid: str, title: str, fn) -> None:
    started = time.perf_counter()
    try:
        detail = fn() or ""
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
        detail = str(exc)
        RESULTS.append(
            {
                "id": cid,
                "title": title,
                "status": "FAIL",
                "detail": detail,
                "durationMs": round((time.perf_counter() - started) * 1000, 1),
            }
        )
        print(f"  ✖ [FAIL] {title} — {detail}")


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int((p / 100) * len(ordered) + 0.9999) - 1))
    return ordered[index]


def sample_endpoint(
    base: str,
    path: str,
    samples: int = PERF_SAMPLES,
    *,
    method: str = "GET",
    body: dict | None = None,
    token: bool = False,
) -> dict:
    durations: list[float] = []
    for _ in range(samples):
        status, _, _, duration = http_json(base, path, method=method, body=body, token=token)
        assert_equal(status, 200, f"性能采样 {path} 状态码")
        durations.append(duration)
    return {
        "path": path,
        "samples": samples,
        "p50": round(percentile(durations, 50), 1),
        "p95": round(percentile(durations, 95), 1),
        "max": round(max(durations), 1),
    }


# ---------------------------------------------------------------------------
# 数据种子
# ---------------------------------------------------------------------------
def seed_database() -> None:
    from app.db import SessionLocal, init_db
    from app.models import Category, MyRepository, TrendingRepository, User

    init_db()
    db = SessionLocal()
    try:
        db.add_all(
            [
                Category(id="cat-pay", name="支付系统"),
                Category(id="cat-ai", name="AI 与推荐"),
                Category(id="cat-web", name="Web 前端"),
                Category(id="cat-infra", name="基础设施"),
                User(id="2001", username="m3-tester"),
            ]
        )
        db.add_all(
            [
                MyRepository(
                    id="me/payment-gateway",
                    name="payment-gateway",
                    description="支付系统网关，支持微信与支付宝",
                    html_url="https://github.com/me/payment-gateway",
                    stars=3200,
                    language="Python",
                    readme_summary="Python,FastAPI,PostgreSQL 支付系统",
                    category_id="cat-pay",
                ),
                MyRepository(
                    id="me/billing-core",
                    name="billing-core",
                    description="账单与结算核心服务",
                    html_url="https://github.com/me/billing-core",
                    stars=2100,
                    language="Python",
                    readme_summary="Python,Django,Redis 账单结算",
                    category_id="cat-pay",
                ),
                MyRepository(
                    id="me/web-console",
                    name="web-console",
                    description="运营后台前端",
                    html_url="https://github.com/me/web-console",
                    stars=1500,
                    language="TypeScript",
                    readme_summary="TypeScript,React,Vite 前端",
                    category_id="cat-web",
                ),
                MyRepository(
                    id="me/design-system",
                    name="design-system",
                    description="React 组件库与设计系统",
                    html_url="https://github.com/me/design-system",
                    stars=900,
                    language="TypeScript",
                    readme_summary="TypeScript,React,Tailwind 组件库",
                    category_id="cat-web",
                ),
                MyRepository(
                    id="me/ml-recommender",
                    name="ml-recommender",
                    description="机器学习推荐系统",
                    html_url="https://github.com/me/ml-recommender",
                    stars=1800,
                    language="Python",
                    readme_summary="Python,PyTorch,推荐 机器学习",
                    category_id="cat-ai",
                ),
                MyRepository(
                    id="me/vector-search",
                    name="vector-search",
                    description="向量检索与语义搜索服务",
                    html_url="https://github.com/me/vector-search",
                    stars=1200,
                    language="Python",
                    readme_summary="Python,FastAPI,向量检索 语义搜索",
                    category_id="cat-ai",
                ),
                MyRepository(
                    id="me/infra-deploy",
                    name="infra-deploy",
                    description="Kubernetes 部署与运维脚本",
                    html_url="https://github.com/me/infra-deploy",
                    stars=700,
                    language="Go",
                    readme_summary="Go,Kubernetes,Docker 部署",
                    category_id="cat-infra",
                ),
                MyRepository(
                    id="me/docs-site",
                    name="docs-site",
                    description="文档站点",
                    html_url="https://github.com/me/docs-site",
                    stars=400,
                    language="JavaScript",
                    readme_summary="JavaScript,Vue,Vite 文档",
                    category_id="cat-web",
                ),
            ]
        )
        trending = [
            ("trend/pay-lite", "轻量支付系统，支持多渠道收款", "Python,FastAPI,支付", "Python", 1200, 8000),
            ("trend/checkout-kit", "电商结算与订单编排工具", "Python,Django,结算", "Python", 1000, 7200),
            ("trend/react-dashboard", "React 数据看板", "TypeScript,React,Vite", "TypeScript", 950, 6800),
            ("trend/ui-kit", "React 组件库", "TypeScript,React,Tailwind", "TypeScript", 900, 6400),
            ("trend/rec-engine", "机器学习推荐引擎", "Python,PyTorch,推荐", "Python", 850, 6000),
            ("trend/embedding-service", "向量检索服务", "Python,FastAPI,向量", "Python", 800, 5600),
            ("trend/k8s-deploy", "Kubernetes 部署工具", "Go,Kubernetes", "Go", 750, 5200),
            ("trend/payment-sdk", "支付 SDK 多语言实现", "Java,支付", "Java", 700, 4800),
            ("trend/search-ui", "搜索前端组件", "TypeScript,React,搜索", "TypeScript", 650, 4400),
            ("trend/data-pipeline", "数据管道与 ETL", "Python,Airflow", "Python", 600, 4000),
            ("trend/cache-proxy", "高性能缓存代理", "Go,Redis", "Go", 550, 3600),
            ("trend/auth-service", "认证与权限服务", "Go,OAuth", "Go", 500, 3200),
        ]
        for repo_id, description, tech, language, stars_today, stars in trending:
            owner, name = repo_id.split("/", 1)
            db.add(
                TrendingRepository(
                    id=repo_id,
                    name=name,
                    description=description,
                    html_url=f"https://github.com/{repo_id}",
                    stars_today=stars_today,
                    tech_stack=tech,
                    readme_summary=description,
                    owner=owner,
                    language=language,
                    stars=stars,
                    crawled_at=date.today(),
                )
            )
        db.commit()
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 检查项
# ---------------------------------------------------------------------------
def run_checks(base: str) -> None:
    # ── M3-01 模型预算 ───────────────────────────────────────────────
    check("M3-01", "模型选型满足 2G 预算（bge-m3 int8 + ≤2B LLM）", lambda: _check_model_budget())

    # ── M3-02 向量化管线 ────────────────────────────────────────────
    def vectorize():
        status, payload, text, _ = http_json(
            base,
            "/api/tasks/vectorize?scope=all&limit=100&batch_size=5",
            method="POST",
            token=True,
        )
        assert_equal(status, 202, "入队状态码")
        assert_true(bool(payload and payload.get("taskId")), f"缺少 taskId：{text[:200]}")
        status, stats, text, _ = http_json(base, "/api/vectors/stats")
        assert_equal(status, 200, "统计状态码")
        assert_equal(stats.get("totalVectors"), 20, "向量总数")
        assert_equal(stats.get("bySource", {}).get("my"), 8, "收藏库向量数")
        assert_equal(stats.get("bySource", {}).get("trending"), 12, "热榜向量数")
        assert_true(bool(stats.get("latestRuns")), "缺少向量化运行记录")
        run = stats["latestRuns"][0]
        assert_equal(run.get("status"), "completed", "运行状态")
        assert_equal(run.get("vectorized"), 20, "本次向量化条数")
        return f"20 条（my 8 / trending 12）· backend={stats['byModel'][0]['backend']}"

    check("M3-02", "全量向量化 20 条并落库", vectorize)

    def vector_detail():
        status, payload, text, _ = http_json(base, "/api/vectors/my/me/payment-gateway")
        assert_equal(status, 200, "单条向量状态码")
        assert_equal(payload.get("dim"), 256, "向量维度")
        assert_equal(len(payload.get("vector") or []), 256, "向量长度")
        assert_true(bool(payload.get("textHash")), "缺少 textHash")
        return "my/me/payment-gateway · dim=256"

    check("M3-03", "单条向量详情可读取（dim=256）", vector_detail)

    # ── M3-03 Vectorize 索引同步 ─────────────────────────────────────
    def sync_first():
        status, payload, text, _ = http_json(
            base,
            "/api/vector-index/sync",
            method="POST",
            body={"mode": "incremental", "scope": "all", "batchSize": 7},
            token=True,
        )
        assert_equal(status, 202, "同步入队状态码")
        assert_true(bool(payload and payload.get("runId")), f"缺少 runId：{text[:200]}")
        status, state, text, _ = http_json(base, "/api/vector-index/status", token=True)
        assert_equal(status, 200, "同步状态码")
        assert_equal(state.get("repoVectors"), 20, "本地向量数")
        assert_equal(state.get("states", {}).get("synced"), 20, "synced 状态数")
        run = state.get("lastRun") or {}
        assert_equal(run.get("status"), "completed", "同步运行状态")
        assert_equal(run.get("upserted"), 20, "upsert 条数")
        assert_true(int(run.get("batches") or 0) >= 3, "应至少分 3 批")
        assert_equal(len(EDGE.vector_upserts), 3, "mock edge 收到批次数")
        return f"upserted=20 · batches={run.get('batches')}"

    check("M3-04", "增量同步 upsert 20 条并按批提交", sync_first)

    def sync_second():
        status, _, text, _ = http_json(
            base,
            "/api/vector-index/sync",
            method="POST",
            body={"mode": "incremental", "scope": "all", "batchSize": 7},
            token=True,
        )
        assert_equal(status, 202, "二次同步入队状态码")
        status, state, text, _ = http_json(base, "/api/vector-index/status", token=True)
        run = state.get("lastRun") or {}
        assert_equal(run.get("status"), "completed", "二次同步状态")
        assert_equal(run.get("upserted"), 0, "二次同步 upsert")
        assert_equal(run.get("skipped"), 20, "二次同步 skipped")
        return "upserted=0 / skipped=20（增量幂等）"

    check("M3-05", "重复增量同步跳过未变化向量", sync_second)

    def reconcile():
        status, payload, text, _ = http_json(
            base,
            "/api/vector-index/reconcile",
            method="POST",
            body={"scope": "all", "repair": False},
            token=True,
        )
        assert_equal(status, 200, "对账状态码")
        assert_equal(payload.get("status"), "completed", "对账状态")
        assert_equal(payload.get("checked"), 20, "对账检查数")
        assert_equal(payload.get("missing"), 0, "缺失数")
        assert_equal(payload.get("stale"), 0, "过期数")
        return "checked=20 / missing=0 / stale=0"

    check("M3-06", "索引对账全部命中（无缺失 / 过期）", reconcile)

    # ── M3-04 语义搜索 ──────────────────────────────────────────────
    def search_query():
        status, payload, text, _ = http_json(
            base,
            "/api/search/query",
            method="POST",
            body={"query": "支付系统 Python", "topK": 5, "scope": "all"},
            token=True,
        )
        assert_equal(status, 200, "搜索状态码")
        assert_equal(payload.get("scanned"), 20, "扫描向量数")
        assert_equal(payload.get("backend"), "hash", "向量后端")
        assert_equal(payload.get("dim"), 256, "查询向量维度")
        assert_true(int(payload.get("count") or 0) >= 1, "应至少命中 1 条")
        ids = [item.get("repoId") for item in payload.get("items") or []]
        assert_true(any("pay" in str(item) for item in ids), f"支付项目未命中：{ids}")
        return f"命中 {payload.get('count')} 条 · top={ids[0]}"

    check("M3-07", "语义搜索命中支付相关项目", search_query)

    def search_semantic():
        status, payload, text, _ = http_json(
            base,
            "/api/search/semantic",
            method="POST",
            body={"query": "支付系统 Python", "topK": 3, "scope": "all"},
            token=True,
        )
        assert_equal(status, 200, "语义搜索状态码")
        items = payload.get("items") or []
        assert_true(bool(items), "语义搜索无结果")
        first = items[0]
        assert_true(bool(first.get("description")), "结果缺少 description")
        assert_true(bool(first.get("reason")), "结果缺少 reason")
        assert_true(bool(first.get("url")), "结果缺少 url")
        return f"{first.get('fullName')} · score={first.get('score')}"

    check("M3-08", "语义搜索结果水合完整（描述 / 理由 / 链接）", search_semantic)

    def search_scope_topk():
        status, payload, _, _ = http_json(
            base,
            "/api/search/query",
            method="POST",
            body={"query": "React 前端", "topK": 2, "scope": "my"},
            token=True,
        )
        assert_equal(status, 200, "限定 scope 状态码")
        assert_true(len(payload.get("items") or []) <= 2, "topK 未生效")
        assert_true(
            all(item.get("source") == "my" for item in payload.get("items") or []),
            "scope=my 返回了非收藏库结果",
        )
        return "scope=my · topK=2"

    check("M3-09", "搜索 scope / topK 过滤生效", search_scope_topk)

    def search_status():
        status, payload, text, _ = http_json(base, "/api/search/status", token=True)
        assert_equal(status, 200, "搜索状态码")
        assert_equal(payload.get("totalVectors"), 20, "向量总数")
        assert_equal(payload.get("dimensions"), [256], "向量维度分布")
        assert_true(bool(payload.get("vocabulary")), "缺少查询理解词表统计")
        return f"totalVectors=20 · vocabulary={payload.get('vocabulary')}"

    check("M3-10", "搜索状态返回覆盖率与词表统计", search_status)

    # ── M3-05 / M3-06 每日推荐与理由 ────────────────────────────────
    def generate_recommendations():
        status, payload, text, _ = http_json(
            base,
            "/api/tasks/generate-recommendations?user_id=2001&top_k=10&min_score=0",
            method="POST",
            token=True,
        )
        assert_equal(status, 202, "推荐任务入队状态码")
        assert_true(bool(payload and payload.get("taskId")), f"缺少 taskId：{text[:200]}")
        status, items, text, _ = http_json(base, "/api/recommend/list?user_id=2001&limit=50")
        assert_equal(status, 200, "推荐列表状态码")
        assert_true(bool(items), "推荐列表为空")
        assert_true(len(items) <= 10, f"推荐数超过 topK：{len(items)}")
        return f"{len(items)} 条推荐"

    check("M3-11", "每日推荐任务生成结果并落库", generate_recommendations)

    def recommendations_quality():
        status, items, _, _ = http_json(base, "/api/recommend/list?user_id=2001&limit=50")
        assert_equal(status, 200, "推荐列表状态码")
        assert_true(bool(items), "推荐列表为空")
        ids = {item.get("repo_id") for item in items}
        assert_true("trend/pay-lite" not in ids, "已收藏项目未被排除")
        assert_true("trend/k8s-deploy" not in ids, "已忽略项目未被排除")
        assert_true(all(item.get("status") == "new" for item in items), "推荐状态应为 new")
        return f"{len(items)} 条 · 已排除 saved/dismissed"

    check("M3-12", "推荐排除已收藏 / 已忽略项目", recommendations_quality)

    def recommendation_reason():
        status, items, _, _ = http_json(base, "/api/recommend/list?user_id=2001&limit=50")
        assert_true(bool(items), "推荐列表为空")
        for item in items:
            assert_true(bool(item.get("reason")), f"{item.get('repo_id')} 缺少理由")
            assert_true("推荐关注" in str(item.get("reason")), "理由文案不完整")
            assert_true(bool(item.get("based_on")), f"{item.get('repo_id')} 缺少 based_on")
        sample = items[0]
        return f"reason=「{sample['reason'][:40]}…」· based_on={sample['based_on']}"

    check("M3-13", "每条推荐含中文理由与依据字段", recommendation_reason)

    def recommend_query():
        status, payload, text, _ = http_json(
            base,
            "/api/recommend/query",
            method="POST",
            body={"query": "支付系统", "top_k": 5},
        )
        assert_equal(status, 200, "即时推荐状态码")
        items = payload.get("items") or []
        assert_true(bool(items), "即时推荐无结果")
        assert_true(all(item.get("reason") for item in items), "即时推荐缺少理由")
        assert_true(all(item.get("based_on") for item in items), "即时推荐缺少 based_on")
        return f"{len(items)} 条 · 首条 {items[0].get('name')}"

    check("M3-14", "即时语义推荐返回理由与依据", recommend_query)

    # ── M3-07 反馈闭环 ──────────────────────────────────────────────
    def feedback_roundtrip():
        with EDGE.lock:
            calls = list(EDGE.feedback_calls)
            pushes = list(EDGE.recommendation_upserts)
        assert_true("2001" in calls, f"未拉取 edge 反馈：{calls}")
        assert_true(bool(pushes), "未回写 edge 推荐")
        latest = pushes[-1]
        assert_equal(latest.get("userId"), "2001", "回写 userId")
        items = latest.get("items") or []
        assert_true(bool(items), "回写推荐为空")
        assert_true(all(item.get("basedOn") for item in items), "回写缺少 basedOn")
        ids = {item.get("repoId") for item in items}
        assert_true("trend/pay-lite" not in ids, "回写包含已收藏项目")
        assert_true("trend/k8s-deploy" not in ids, "回写包含已忽略项目")
        return f"反馈拉取 1 次 · 回写 {len(items)} 条"

    check("M3-15", "反馈拉取 → 排除 → 推荐回写闭环", feedback_roundtrip)

    # ── M3-08 质量评估 ──────────────────────────────────────────────
    def quality_eval():
        status, payload, text, _ = http_json(
            base,
            "/api/recommend/eval",
            method="POST",
            body={
                "sampleSize": 3,
                "topK": 5,
                "holdoutRatio": 0.25,
                "negativesPerPositive": 3,
                "seed": 7,
            },
        )
        assert_equal(status, 200, "评估状态码")
        assert_equal(payload.get("status"), "ok", f"评估状态：{text[:300]}")
        dataset = payload.get("dataset") or {}
        assert_equal(dataset.get("samples"), 3, "评估折叠数")
        metrics = payload.get("metrics") or {}
        for key in ("precision", "recall", "f1", "hitRate", "mrr", "ndcg", "coverage", "diversity"):
            assert_true(key in metrics, f"缺少指标 {key}")
        assert_true(bool(payload.get("thresholds")), "缺少阈值扫描")
        assert_true(bool(payload.get("weights")), "缺少权重扫描")
        assert_true(bool(payload.get("recommended")), "缺少调参建议")
        return (
            f"samples=3 · F1={metrics.get('f1')} · "
            f"推荐 minScore={payload['recommended'].get('minScore')}"
        )

    check("M3-16", "推荐质量评估返回指标 / 扫描 / 调参建议", quality_eval)

    # ── M3-09 降级路径 ──────────────────────────────────────────────
    def degradation_api():
        status, payload, text, _ = http_json(base, "/api/degradation/status", token=True)
        assert_equal(status, 200, "降级状态码")
        assert_true(bool(payload.get("ok")), f"降级自检失败：{text[:300]}")
        checks = payload.get("checks") or []
        assert_equal(len(checks), 5, "降级检查项数")
        assert_true(all(item.get("ok") for item in checks), "存在失败的降级检查")
        assert_equal(payload.get("embeddingExpectedBackend"), "hash", "预期向量后端")
        assert_equal(payload.get("budgetMb"), 2048, "预算")
        return "5 项全 PASS · expectedBackend=hash"

    check("M3-17", "降级状态接口 5 项自检全 PASS", degradation_api)

    def degradation_cli():
        code, payload, output = run_cli(["-m", "app.degradation", "check", "--json"])
        assert_equal(code, 0, f"CLI 退出码（{output[-200:]}）")
        assert_true(bool(payload and payload.get("ok")), "CLI 输出未通过")
        return "python -m app.degradation check --json · exit 0"

    check("M3-18", "降级自检 CLI 可独立执行", degradation_cli)

    # ── M3-10 查询理解 ──────────────────────────────────────────────
    def understand():
        status, payload, text, _ = http_json(
            base,
            "/api/search/understand",
            method="POST",
            body={"query": "react 前端"},
            token=True,
        )
        assert_equal(status, 200, "查询理解状态码")
        assert_true(payload.get("expanded") is True, "未启用扩展")
        assert_true("React" in (payload.get("techStack") or []), "未识别 React 技术栈")
        assert_true("前端" in (payload.get("concepts") or []), "未识别前端概念")
        assert_true("frontend" in str(payload.get("rewritten")), "改写结果缺少 frontend")
        return f"rewritten=「{payload.get('rewritten')}」"

    check("M3-19", "查询理解识别技术栈与同义词", understand)

    def understand_disabled():
        status, payload, _, _ = http_json(
            base,
            "/api/search/understand",
            method="POST",
            body={"query": "react 前端", "expand": False},
            token=True,
        )
        assert_equal(status, 200, "关闭扩展状态码")
        assert_true(payload.get("expanded") is False, "expand=false 仍启用扩展")
        assert_equal(payload.get("terms"), [], "expand=false 仍返回扩展词")
        assert_equal(payload.get("techStack"), [], "expand=false 仍返回技术栈")
        return "expand=false · 保持原查询"

    check("M3-20", "查询理解可关闭（expand=false）", understand_disabled)

    def embed_query():
        status, payload, text, _ = http_json(
            base,
            "/api/search/embed",
            method="POST",
            body={"query": "向量检索"},
            token=True,
        )
        assert_equal(status, 200, "查询向量状态码")
        assert_equal(payload.get("dim"), 256, "查询向量维度")
        assert_equal(len(payload.get("vector") or []), 256, "向量长度")
        assert_true(bool(payload.get("understanding")), "缺少查询理解结果")
        return "dim=256 · understanding 已返回"

    check("M3-21", "查询向量接口返回向量与理解结果", embed_query)


def run_cli(args: list[str]) -> tuple[int, object, str]:
    """在 vps 目录执行 CLI，解析 stdout 中的 JSON。"""
    env = dict(os.environ)
    proc = subprocess.run(
        [sys.executable, *args],
        cwd=VPS_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )
    output = (proc.stdout or "") + (proc.stderr or "")
    payload = None
    start = proc.stdout.find("{")
    if start >= 0:
        try:
            payload = json.loads(proc.stdout[start:])
        except json.JSONDecodeError:
            payload = None
    return proc.returncode, payload, output


def _check_model_budget() -> str:
    code, payload, output = run_cli(["-m", "app.model_budget", "check", "--json"])
    assert_equal(code, 0, f"预算 CLI 退出码（{output[-200:]}）")
    report = (payload or {}).get("report") or {}
    assert_true(bool(report.get("budget_ok")), "预算校验未通过")
    budget = int(report.get("budget_mb") or 0)
    peak = int(report.get("peak_resident_mb") or 0)
    assert_equal(budget, 2048, "预算上限")
    assert_true(peak <= budget, f"峰值 {peak}MB 超出预算 {budget}MB")
    roles = {item.get("role"): item for item in report.get("items") or []}
    assert_true("embedding" in roles and "llm" in roles, "缺少模型项")
    assert_true(bool(roles["embedding"].get("within_budget")), "embedding 超预算")
    assert_true(bool(roles["llm"].get("within_budget")), "LLM 超预算")
    return (
        f"embedding={roles['embedding']['resident_mb']}MB · "
        f"llm={roles['llm']['resident_mb']}MB · peak={peak}/{budget}MB"
    )


# ---------------------------------------------------------------------------
# 报告
# ---------------------------------------------------------------------------
def git_info() -> tuple[str, str]:
    def run(args: list[str]) -> str:
        try:
            return subprocess.check_output(
                ["git", *args], cwd=REPO_ROOT, stderr=subprocess.DEVNULL, text=True
            ).strip()
        except (subprocess.CalledProcessError, FileNotFoundError):
            return "unknown"

    return run(["rev-parse", "--abbrev-ref", "HEAD"]), run(["rev-parse", "--short", "HEAD"])


def summarize() -> dict[str, int]:
    summary = {"PASS": 0, "GAP": 0, "FAIL": 0, "SKIP": 0}
    for item in RESULTS:
        status = str(item["status"])
        summary[status] = summary.get(status, 0) + 1
    return summary


def build_markdown(meta: dict) -> str:
    summary = summarize()
    rows = "\n".join(
        f"| {item['id']} | {item['title']} | {item['status']} | "
        f"{str(item['detail']).replace('|', chr(92) + '|') or '—'} | {item['durationMs']}ms |"
        for item in RESULTS
    )
    perf_rows = "\n".join(
        f"| `{item['path']}` | {item['samples']} | {item['p50']}ms | {item['p95']}ms | "
        f"{item['max']}ms | {'PASS' if item['p95'] < item['budget'] else 'FAIL'} |"
        for item in PERF
    )
    conclusion = (
        "存在失败项，验收不通过"
        if summary["FAIL"]
        else "全部通过"
        if not summary["GAP"]
        else "已交付能力通过；存在未集成能力"
    )
    return f"""# M3 验收报告（自动生成）

- 生成时间：{meta['finishedAt']}
- 分支 / 提交：{meta['branch']} / {meta['commit']}
- 运行环境：{meta['platform']} · Python {meta['python']}
- 数据规模：8 个收藏库 / 12 个热榜仓库 / 1 个测试用户 / mock edge（Vectorize + 推荐反馈）
- 判定口径：PASS 通过 · GAP 能力未集成（阻塞） · FAIL 行为错误 · SKIP 跳过

## 检查结果

| # | 检查 | 结果 | 说明 | 耗时 |
| --- | --- | --- | --- | --- |
{rows}

## 性能抽样

| 场景 | 样本数 | P50 | P95 | Max | 结果 |
| --- | --- | --- | --- | --- | --- |
{perf_rows}

## 汇总

- PASS：{summary['PASS']}
- GAP：{summary['GAP']}
- FAIL：{summary['FAIL']}
- SKIP：{summary['SKIP']}
- 结论：{conclusion}
"""


# ---------------------------------------------------------------------------
# 主流程
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
            raise RuntimeError(
                f"uvicorn 提前退出（code={process.returncode}）：\n{output[-3000:]}"
            )
        try:
            status, payload, _, _ = http_json(base, "/healthz")
            if status == 200 and isinstance(payload, dict):
                return
        except Exception:  # noqa: BLE001 - 尚未就绪
            pass
        time.sleep(0.3)
    raise RuntimeError("等待 uvicorn 就绪超时")


def main() -> int:
    parser = argparse.ArgumentParser(description="M3 验收脚本")
    parser.add_argument("--strict", action="store_true", help="存在 GAP 时也返回非零")
    parser.add_argument("--keep", action="store_true", help="保留临时数据库")
    parser.add_argument("--report-md", default=None, help="Markdown 报告输出路径")
    parser.add_argument("--report-json", default=None, help="JSON 报告输出路径")
    args = parser.parse_args()

    mock_server = None
    uvicorn = None
    try:
        print("• 种入 M3 验收数据集…")
        seed_database()

        print("• 启动 mock edge（Vectorize / 推荐反馈）…")
        mock_server, edge_base = start_mock_edge()
        os.environ["EDGE_BASE_URL"] = edge_base

        port = get_free_port()
        base = f"http://127.0.0.1:{port}"
        env = dict(os.environ)
        env["EDGE_BASE_URL"] = edge_base
        print(f"• 启动 uvicorn（{base}）…")
        uvicorn = subprocess.Popen(
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
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        wait_for_health(base, uvicorn)

        print("• 执行 M3 验收检查…")
        run_checks(base)

        print("• 性能抽样…")
        search_perf = sample_endpoint(
            base,
            "/api/search/query",
            samples=PERF_SAMPLES,
            method="POST",
            body={"query": "支付系统 Python", "topK": 5, "scope": "all"},
            token=True,
        )
        search_perf["budget"] = SEARCH_P95_BUDGET_MS
        PERF.append(search_perf)
        RESULTS.append(
            {
                "id": "M3-P01",
                "title": f"语义搜索 P95 < {SEARCH_P95_BUDGET_MS:.0f}ms",
                "status": "PASS" if search_perf["p95"] < SEARCH_P95_BUDGET_MS else "FAIL",
                "detail": f"P50 {search_perf['p50']}ms / P95 {search_perf['p95']}ms",
                "durationMs": search_perf["p95"],
            }
        )
        print(f"  · 搜索：P50 {search_perf['p50']}ms / P95 {search_perf['p95']}ms")

        recommend_perf = sample_endpoint(
            base, "/api/recommend/list?user_id=2001&limit=50", samples=PERF_SAMPLES
        )
        recommend_perf["budget"] = RECOMMEND_P95_BUDGET_MS
        PERF.append(recommend_perf)
        RESULTS.append(
            {
                "id": "M3-P02",
                "title": f"推荐列表 P95 < {RECOMMEND_P95_BUDGET_MS:.0f}ms",
                "status": "PASS" if recommend_perf["p95"] < RECOMMEND_P95_BUDGET_MS else "FAIL",
                "detail": f"P50 {recommend_perf['p50']}ms / P95 {recommend_perf['p95']}ms",
                "durationMs": recommend_perf["p95"],
            }
        )
        print(f"  · 推荐列表：P50 {recommend_perf['p50']}ms / P95 {recommend_perf['p95']}ms")

        summary = summarize()
        print(
            f"\n汇总：PASS {summary['PASS']} · GAP {summary['GAP']} · "
            f"FAIL {summary['FAIL']} · SKIP {summary['SKIP']}"
        )

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
                json.dumps({"meta": meta, "results": RESULTS, "perf": PERF}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            print(f"• 已写入 JSON 报告：{target}")

        if summary["FAIL"] > 0 or (args.strict and summary["GAP"] > 0):
            return 1
        return 0
    finally:
        if uvicorn is not None and uvicorn.poll() is None:
            uvicorn.terminate()
            try:
                uvicorn.wait(timeout=10)
            except subprocess.TimeoutExpired:
                uvicorn.kill()
        if mock_server is not None:
            mock_server.shutdown()
            mock_server.server_close()
        if args.keep:
            print(f"• 保留临时数据库：{TMP_DIR}")
        else:
            shutil.rmtree(TMP_DIR, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
