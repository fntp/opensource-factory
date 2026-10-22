"""Pydantic 出入参模型（API 层）。"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class ORMModel(BaseModel):
    """可从 SQLAlchemy 模型直接序列化的基类。"""

    model_config = ConfigDict(from_attributes=True)


class RepoOut(ORMModel):
    """仓库输出。"""

    id: str
    platform: str
    name: str
    description: Optional[str] = None
    html_url: str
    stars: int = 0
    language: Optional[str] = None
    readme_summary: Optional[str] = None
    category_id: Optional[str] = None
    created_at: Optional[datetime] = None


class TrendingRepoOut(ORMModel):
    """热榜仓库输出（含按日快照与趋势字段）。"""

    id: str
    platform: str
    name: str
    html_url: str
    stars_today: Optional[int] = 0
    description: Optional[str] = None
    tech_stack: Optional[str] = None
    readme_summary: Optional[str] = None
    owner: Optional[str] = None
    language: Optional[str] = None
    stars: int = 0
    crawled_at: Optional[date] = None
    snapshot_date: Optional[date] = None
    rank: Optional[int] = None
    rank_change: Optional[int] = None
    trend: Optional[str] = None


class TrendingRepoDetail(TrendingRepoOut):
    """热榜详情输出：摘要 + 元信息。"""

    summary: Optional[str] = None
    summary_source: str = "empty"  # readme | description | tech | empty


class TrendingSnapshotOut(ORMModel):
    """热榜按日快照输出（含趋势字段）。"""

    snapshot_date: date
    repo_id: str
    platform: str
    owner: Optional[str] = None
    name: str
    html_url: str
    description: Optional[str] = None
    language: Optional[str] = None
    tech_stack: Optional[str] = None
    stars: int = 0
    stars_today: int = 0
    rank: int = 0
    language_rank: int = 0
    star_delta: int = 0
    rank_delta: int = 0
    appearances: int = 1
    is_new: int = 0
    trend: str = "steady"
    trending_pages: Optional[str] = None


class TrendingSnapshotDateOut(BaseModel):
    """可用快照日期。"""

    date: date
    count: int


class CrawlAlertOut(ORMModel):
    """热榜抓取告警输出。"""

    id: str
    platform: str
    page: str
    kind: str
    severity: str
    message: str
    details: Optional[str] = None
    status: str
    occurrences: int = 1
    first_seen_at: Optional[datetime] = None
    last_seen_at: Optional[datetime] = None
    acknowledged_at: Optional[datetime] = None


class TrendingRetentionStatus(BaseModel):
    """热榜数据保留策略状态（M2-08，字段与运维接口保持一致）。"""

    enabled: bool
    retentionDays: int
    cutoff: Optional[date] = None
    archiveEnabled: bool
    archiveDir: str
    archiveKeepDays: int
    totalSnapshots: int
    expiredSnapshots: int
    oldestDate: Optional[date] = None
    latestDate: Optional[date] = None
    databaseBytes: int
    archiveFiles: int
    archiveBytes: int


class RecommendQuery(BaseModel):
    """语义查询请求。"""

    query: str = Field(min_length=1, description="自然语言查询，如「支付系统脚手架」")
    top_k: int = Field(default=10, ge=1, le=50, description="返回条数")


class RecommendItem(BaseModel):
    """单条推荐结果（含中文理由与依据字段）。"""

    repo_id: str
    name: str
    html_url: str
    language: str = ""
    description: str = ""
    score: float
    reason: str
    based_on: list[str] = Field(default_factory=list, description="理由依据字段")


class RecommendResponse(BaseModel):
    """语义查询响应。"""

    query: str
    count: int
    items: list[RecommendItem]


class RecommendationOut(BaseModel):
    """本地已生成的推荐结果（含理由与依据字段）。"""

    id: str
    user_id: str
    repo_id: str
    name: str = ""
    html_url: str = ""
    description: str = ""
    language: str = ""
    tech_stack: str = ""
    score: float
    reason: str = ""
    based_on: list[str] = Field(default_factory=list)
    status: str = "new"
    created_at: Optional[datetime] = None
class RecommendEvalRequest(BaseModel):
    """推荐质量评估请求（M3-08）。"""

    sampleSize: Optional[int] = Field(default=None, ge=1, le=50, description="评估折叠数")
    topK: Optional[int] = Field(default=None, ge=1, le=50, description="评估用 top_k")
    holdoutRatio: Optional[float] = Field(
        default=None, gt=0.0, lt=1.0, description="每个折叠留出的正样本比例"
    )
    negativesPerPositive: Optional[int] = Field(
        default=None, ge=1, le=20, description="每个正样本配的负样本数"
    )
    seed: Optional[int] = Field(default=None, ge=0, description="抽样随机种子")
    userId: Optional[str] = Field(default=None, description="只统计该用户的线上反馈")


class RecommendEvalMetrics(BaseModel):
    """排序指标（逐折叠均值）。"""

    precision: float = 0.0
    recall: float = 0.0
    f1: float = 0.0
    hitRate: float = 0.0
    mrr: float = 0.0
    ndcg: float = 0.0
    coverage: float = 0.0
    diversity: float = 0.0
    avgResults: float = 0.0


class RecommendEvalThreshold(BaseModel):
    """单个 min_score 候选的指标。"""

    minScore: float
    precision: float = 0.0
    recall: float = 0.0
    f1: float = 0.0
    coverage: float = 0.0
    avgResults: float = 0.0


class RecommendEvalWeight(RecommendEvalThreshold):
    """单个权重组合的最优结果。"""

    similarityWeight: float
    trendingWeight: float


class RecommendEvalRecommendation(BaseModel):
    """调参建议。"""

    minScore: float
    similarityWeight: float
    trendingWeight: float
    reason: str = ""
    improved: bool = False


class RecommendEvalReport(BaseModel):
    """推荐质量评估报告。"""

    status: str
    generatedAt: datetime
    config: dict[str, Any]
    dataset: dict[str, Any]
    metrics: RecommendEvalMetrics
    thresholds: list[RecommendEvalThreshold]
    weights: list[RecommendEvalWeight]
    recommended: RecommendEvalRecommendation
    current: RecommendEvalThreshold
    feedback: dict[str, Any]
    warnings: list[str]


class TaskEnqueued(BaseModel):
    """任务入队响应（与边缘 Worker 的契约，字段名保持 camelCase）。"""

    taskId: str


class TaskStatus(BaseModel):
    """任务状态响应。"""

    taskId: str
    status: str  # pending | started | progress | success | failure
    result: Any = None
    error: Optional[str] = None
    progress: Optional[dict[str, Any]] = None


class QualityCheckOut(BaseModel):
    """单项摘要质量检查。"""

    key: str
    label: str
    weight: int
    critical: bool
    passed: bool
    detail: str


class QualitySampleOut(BaseModel):
    """抽检样本输出（camelCase 与前端契约一致）。"""

    id: str
    batchId: str
    repoId: str
    repoSource: str
    summary: str
    source: str
    model: str
    maxChars: int
    score: float
    verdict: str
    checks: list[QualityCheckOut] = Field(default_factory=list)
    status: str
    reviewer: Optional[str] = None
    reviewNote: Optional[str] = None
    reviewedAt: Optional[datetime] = None
    createdAt: Optional[datetime] = None


class QualitySampleList(BaseModel):
    """抽检样本分页列表。"""

    total: int
    items: list[QualitySampleOut]


class QualityStatsOut(BaseModel):
    """摘要质量统计。"""

    total: int
    pending: int
    passed: int
    failed: int
    passRate: float
    avgScore: float
    bySource: dict[str, int] = Field(default_factory=dict)
    byRepoSource: dict[str, int] = Field(default_factory=dict)
    recentBatches: list[dict[str, Any]] = Field(default_factory=list)


class QualityReviewIn(BaseModel):
    """人工复核请求。"""

    result: Literal["passed", "failed"]
    reviewer: Optional[str] = Field(default=None, max_length=128)
    note: Optional[str] = Field(default=None, max_length=2000)


class QualitySampleExistingIn(BaseModel):
    """存量摘要补抽样请求。"""

    source: Literal["my", "trending", "all"] = "my"
    limit: int = Field(default=200, ge=1, le=1000)
    rate: Optional[float] = Field(default=None, ge=0, le=1)
    batchId: Optional[str] = Field(default=None, max_length=128)


class VectorSyncRunOut(BaseModel):
    """一次同步运行的统计输出。"""

    runId: str
    kind: str
    scope: str
    status: str
    batchSize: int
    maxRetries: int
    force: bool
    limit: int
    total: int
    processed: int
    synced: int
    skipped: int
    failed: int
    deleted: int
    checked: int
    missing: int
    repaired: int
    orphanScan: str = ""
    cursorSource: str = ""
    cursorRepoId: str = ""
    error: Optional[str] = None
    createdAt: Optional[datetime] = None
    updatedAt: Optional[datetime] = None
    finishedAt: Optional[datetime] = None


class VectorizeEnqueued(TaskEnqueued):
    """向量化任务入队响应（附带运行 id，可用于续跑 / 查询）。"""

    runId: str


class VectorRunOut(BaseModel):
    """向量化运行状态。"""

    runId: str
    scope: str
    status: str  # running | completed | failed
    model: str = ""
    backend: str = ""
    dim: int = 0
    force: bool = False
    limit: int = 0
    batchSize: int = 0
    total: int = 0
    processed: int = 0
    vectorized: int = 0
    skipped: int = 0
    failed: int = 0
    cursorSource: str = ""
    cursorRepoId: str = ""
    error: Optional[str] = None
    createdAt: Optional[datetime] = None
    updatedAt: Optional[datetime] = None
    finishedAt: Optional[datetime] = None


class VectorSyncStatusOut(BaseModel):
    """索引同步状态：本地覆盖率、状态分布与最近运行。"""

    enabled: bool
    configured: bool
    indexName: str
    dim: int
    localVectors: int
    states: dict[str, int]
    pending: int
    lastRuns: list[VectorSyncRunOut]


class VectorModelStats(BaseModel):
    """按模型 / 后端分组的向量数量。"""

    model: str
    backend: str
    count: int


class VectorSourceStats(BaseModel):
    """单个来源的向量覆盖情况。"""

    total: int
    vectorized: int
    pending: int


class VectorStatsResponse(BaseModel):
    """向量化统计响应。"""

    totalVectors: int
    bySource: dict[str, int]
    byModel: list[VectorModelStats]
    repositories: dict[str, VectorSourceStats]
    latestRuns: list[VectorRunOut]


class VectorDetail(BaseModel):
    """单条向量详情（调试 / 后续 Vectorize 同步使用）。"""

    source: str
    repoId: str
    model: str
    backend: str
    dim: int
    textHash: str
    vector: list[float]
    updatedAt: Optional[datetime] = None


class VectorSyncRequest(BaseModel):
    """Vectorize 索引同步入参。"""

    mode: str = Field(default="incremental", pattern="^(incremental|full)$")
    scope: str = Field(default="all", pattern="^(my|trending|all)$")
    limit: Optional[int] = Field(default=None, ge=1, le=100000)
    batchSize: Optional[int] = Field(default=None, ge=1, le=1000)


class VectorSyncEnqueued(BaseModel):
    """同步入队响应。"""

    taskId: str
    runId: str


class VectorReconcileRequest(BaseModel):
    """Vectorize 对账入参。"""

    scope: str = Field(default="all", pattern="^(my|trending|all)$")
    repair: bool = False
    limit: Optional[int] = Field(default=None, ge=1, le=100000)

class SearchQuery(BaseModel):
    """语义搜索请求（内部接口共用）。"""

    query: str = Field(min_length=1, max_length=200, description="自然语言查询")
    topK: Optional[int] = Field(default=None, ge=1, le=50, description="返回条数（默认 10，最大 50）")
    scope: Literal["my", "trending", "all"] = "all"
    minScore: Optional[float] = Field(default=None, ge=-1.0, le=1.0, description="最低余弦相似度")
    expand: bool = Field(default=True, description="是否启用同义词 / 技术栈词表扩展")


class SearchUnderstandingOut(BaseModel):
    """查询理解结果（同义词 / 技术栈词表）。"""

    query: str
    rewritten: str
    expanded: bool
    techStack: list[str]
    concepts: list[str]
    terms: list[str]
    keywordTerms: list[str]
    maxTerms: int


class SearchEmbedResponse(BaseModel):
    """查询向量：供 edge 调用 Vectorize.query 使用。"""

    vector: list[float]
    dim: int
    model: str
    backend: str
    understanding: SearchUnderstandingOut


class SearchHitOut(BaseModel):
    """本地向量命中（未水合）。"""

    source: str
    repoId: str
    score: float


class SearchQueryResponse(BaseModel):
    """本地向量检索响应。"""

    query: str
    scope: str
    count: int
    topK: int
    minScore: float
    model: str
    backend: str
    dim: int
    scanned: int
    understanding: SearchUnderstandingOut
    items: list[SearchHitOut]


class SimilarQuery(BaseModel):
    """相似项目推荐请求（以仓库向量为种子）。"""

    source: Literal["my", "trending"] = Field(description="种子仓库来源")
    repoId: str = Field(min_length=1, max_length=255, description="种子仓库 id（owner/repo）")
    topK: Optional[int] = Field(default=None, ge=1, le=50, description="返回条数（默认 10，最大 50）")
    scope: Literal["my", "trending", "all"] = "all"
    minScore: Optional[float] = Field(default=None, ge=-1.0, le=1.0, description="最低余弦相似度")
    excludeSaved: bool = Field(default=False, description="是否排除收藏库（只推荐未收藏项目）")


class SimilarSeedOut(BaseModel):
    """种子仓库展示信息。"""

    source: str
    repoId: str
    name: str = ""
    description: str = ""
    language: str = ""


class SimilarQueryResponse(BaseModel):
    """本地向量近邻响应（未水合，供 edge 按用户权限水合）。"""

    source: str
    repoId: str
    scope: str
    count: int
    topK: int
    minScore: float
    excludeSaved: bool
    model: str
    backend: str
    dim: int
    scanned: int
    seed: SimilarSeedOut
    items: list[SearchHitOut]


class SearchItem(BaseModel):
    """水合后的搜索结果条目。"""

    id: str
    source: str
    fullName: str
    name: str
    description: str = ""
    language: str = ""
    stars: int = 0
    starsToday: int = 0
    url: str = ""
    score: float = 0.0
    reason: str = ""


class SearchSemanticResponse(BaseModel):
    """本地语义搜索完整结果（内部 / 调试 / CLI）。"""

    query: str
    scope: str
    count: int
    model: str
    backend: str
    dim: int
    scanned: int
    understanding: SearchUnderstandingOut
    items: list[SearchItem]


class SearchStatusResponse(BaseModel):
    """语义搜索可用性：向量覆盖率与最近向量化运行。"""

    totalVectors: int
    bySource: dict[str, int]
    byModel: list[VectorModelStats]
    dimensions: list[int]
    vocabulary: dict[str, int]
    latestRuns: list[VectorRunOut]

class DegradationCheckOut(BaseModel):
    """单项降级检查结果。"""

    name: str
    ok: bool
    detail: str


class DegradationStatusOut(BaseModel):
    """降级路径自检状态（M3-09）。"""

    ok: bool
    summary: str
    embeddingModel: str
    embeddingQuantization: str
    embeddingExpectedBackend: str
    llmModel: str
    llmDegraded: bool
    budgetMb: int
    checks: list[DegradationCheckOut]


class DependencyRefreshRequest(BaseModel):
    """依赖清单扫描请求（M6-07）。"""

    repoIds: list[str] = Field(default_factory=list)
    force: bool = False
    limit: int = 0


class DependencyRefreshResponse(BaseModel):
    """依赖清单扫描结果。"""

    status: str
    scanned: int
    ok: int
    noManifest: int
    failed: int
    dependencies: int
    repos: list[dict[str, Any]] = Field(default_factory=list)


class DependencyAnalysisResponse(BaseModel):
    """依赖分析聚合结果（技术栈 / 生态 / 依赖覆盖 / 依赖 × 语言关联）。"""

    generatedAt: str
    summary: dict[str, int]
    techStack: list[dict[str, Any]]
    ecosystems: list[dict[str, Any]]
    dependencies: list[dict[str, Any]]
    links: list[dict[str, Any]]
    repos: list[dict[str, Any]]
