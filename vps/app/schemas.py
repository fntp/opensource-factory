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


class RepoHealthOut(BaseModel):
    """单个仓库健康度（M6-05）。"""

    repoId: str
    name: str
    htmlUrl: str = ""
    language: Optional[str] = None
    stars: int = 0
    status: str  # active | attention | stale | archived | unknown
    label: str
    score: int = 0
    lastPushAt: Optional[datetime] = None
    daysSincePush: Optional[int] = None
    openIssues: int = 0
    archived: bool = False
    reasons: list[str] = Field(default_factory=list)
    checkedAt: Optional[datetime] = None


class RepoHealthSummary(BaseModel):
    """健康度汇总计数。"""

    total: int = 0
    active: int = 0
    attention: int = 0
    stale: int = 0
    archived: int = 0
    unknown: int = 0
    averageScore: float = 0.0


class RepoHealthListOut(BaseModel):
    summary: RepoHealthSummary
    items: list[RepoHealthOut]


class RepoHealthRefreshRequest(BaseModel):
    """健康度刷新请求。"""

    repoIds: list[str] = Field(default_factory=list)
    limit: int = Field(default=200, ge=1, le=1000)


class RepoUpdatesScanRequest(BaseModel):
    """收藏项目更新扫描请求（M7-04）。"""

    repoIds: list[str] = Field(default_factory=list)
    limit: int = Field(default=200, ge=1, le=1000)
    includePrerelease: bool = False


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


class EvaluationRunOut(BaseModel):
    """单次推荐评估运行输出（M4-01）。"""

    runId: str
    userId: Optional[str] = None
    status: str
    matchThreshold: float
    qualityThreshold: float
    total: int = 0
    qualified: int = 0
    filtered: int = 0
    skipped: int = 0
    failed: int = 0
    error: Optional[str] = None
    createdAt: Optional[datetime] = None
    finishedAt: Optional[datetime] = None


class EvaluationRunListResponse(BaseModel):
    """评估运行列表。"""

    count: int
    items: list[EvaluationRunOut]


class QualifiedRecommendationOut(BaseModel):
    """通过每日评估、等待推送的推荐。"""

    id: str
    userId: str
    repoId: str
    score: float
    matchScore: float
    qualityScore: float
    qualityDetail: Optional[dict[str, Any]] = None
    reason: Optional[str] = None
    status: str
    evaluatedAt: Optional[datetime] = None


class QualifiedListResponse(BaseModel):
    """合格推荐列表。"""

    count: int
    items: list[QualifiedRecommendationOut]


class BarkStatusOut(BaseModel):
    """Bark 推送通道状态（不包含 device key）。"""

    enabled: bool
    configured: bool
    serverUrl: str
    group: str
    level: str
    maxPerRun: int
    dryRun: bool
    pending: int = 0
    sent: int = 0
    failed: int = 0
    lastError: Optional[str] = None
    lastSentAt: Optional[datetime] = None


class BarkTestRequest(BaseModel):
    """Bark 测试通知请求。"""

    title: Optional[str] = Field(default=None, max_length=120)
    body: Optional[str] = Field(default=None, max_length=2000)
    url: Optional[str] = Field(default=None, max_length=2000)


class BarkTestOut(BaseModel):
    """Bark 测试通知结果。"""

    ok: bool
    statusCode: Optional[int] = None
    error: Optional[str] = None


class TelegramDeliveryOut(BaseModel):
    """Telegram 送达记录输出（M4-04）。"""

    id: str
    chatId: str
    kind: str
    status: str
    itemCount: int = 0
    messageCount: int = 0
    messageId: Optional[str] = None
    error: Optional[str] = None
    createdAt: Optional[datetime] = None
    finishedAt: Optional[datetime] = None


class TelegramStatusOut(BaseModel):
    """Telegram 通道状态（不返回 token，chat id 脱敏）。"""

    enabled: bool
    configured: bool
    chatIdMasked: str = ""
    apiBase: str = ""
    dailyLimit: int = 0
    digestWindowHours: int = 0
    lastDelivery: Optional[TelegramDeliveryOut] = None


class TelegramTestRequest(BaseModel):
    """测试消息请求。"""

    text: Optional[str] = Field(default=None, max_length=1000, description="自定义测试文案")


class TelegramSendResponse(BaseModel):
    """Telegram 发送结果。"""

    ok: bool
    status: str
    sent: bool = False
    deliveryId: Optional[str] = None
    itemCount: int = 0
    messageCount: int = 0
    messageIds: list[str] = Field(default_factory=list)
    error: Optional[str] = None


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


class SearchFulltextRequest(BaseModel):
    """README 全文检索请求（M6-01）。"""

    query: str = Field(min_length=1, max_length=200, description="关键词 / 短语")
    scope: Literal["my", "trending", "all"] = "all"
    topK: Optional[int] = Field(default=None, ge=1, le=50, description="返回条数（默认 10，最大 50）")
    offset: int = Field(default=0, ge=0, le=10000)


class SearchFulltextItem(SearchItem):
    """全文检索命中条目：附带 README 片段与命中词。"""

    snippet: str = ""
    matchedTerms: list[str] = []


class FulltextIndexStats(BaseModel):
    """README 全文索引覆盖率。"""

    enabled: bool
    totalDocs: int
    bySource: dict[str, int]
    totalChars: int
    ftsDocs: Optional[int] = None
    latestUpdatedAt: Optional[str] = None


class SearchFulltextResponse(BaseModel):
    """README 全文检索完整结果。"""

    query: str
    scope: str
    mode: Literal["fts", "like"]
    count: int
    topK: int
    offset: int
    tookMs: int
    terms: list[str]
    index: FulltextIndexStats
    items: list[SearchFulltextItem]


class FulltextRebuildResponse(BaseModel):
    """索引重建结果。"""

    rebuilt: int


class SyncReadmesRequest(BaseModel):
    """README 镜像补索引任务入参。"""

    source: Literal["my", "trending", "all"] = "all"
    repoIds: Optional[list[str]] = Field(default=None, max_length=200)
    limit: Optional[int] = Field(default=None, ge=1, le=5000)
    force: bool = False


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
class EmailDeliveryOut(BaseModel):
    """Email 送达记录输出（收件人已脱敏）。"""

    id: str
    recipientMasked: str = ""
    kind: str  # digest | test
    status: str  # sent | failed
    itemCount: int = 0
    subject: Optional[str] = None
    messageId: Optional[str] = None
    error: Optional[str] = None
    createdAt: Optional[datetime] = None
    finishedAt: Optional[datetime] = None


class EmailStatusOut(BaseModel):
    """Email 通道状态快照（不暴露 SMTP 凭据）。"""

    enabled: bool
    configured: bool
    host: str = ""
    port: int = 0
    starttls: bool = True
    ssl: bool = False
    fromMasked: str = ""
    toMasked: str = ""
    lastDelivery: Optional[EmailDeliveryOut] = None


class EmailTestRequest(BaseModel):
    """测试邮件请求：全部字段可选，默认使用配置的 EMAIL_TO。"""

    to: Optional[str] = Field(default=None, description="收件人，逗号 / 分号分隔")
    subject: Optional[str] = Field(default=None, max_length=160)
    body: Optional[str] = Field(default=None, max_length=2000)


class EmailSendResponse(BaseModel):
    """Email 发送 / 测试结果。"""

    ok: bool
    status: str  # disabled | not_configured | empty | skipped | sent | failed
    deliveryId: Optional[str] = None
    itemCount: int = 0
    messageId: Optional[str] = None
    error: Optional[str] = None
    reason: Optional[str] = None


# ---------------------------------------------------------------------------
# 推送去重与静默策略（M4-07）
# ---------------------------------------------------------------------------


class PushPolicyCheckRequest(BaseModel):
    """发送前预演请求。"""

    userId: str = Field(min_length=1, max_length=128)
    repoId: str = Field(min_length=1, max_length=255)
    recommendationId: Optional[str] = Field(default=None, max_length=64)
    channel: Literal["inapp", "bark", "telegram", "email"] = "inapp"


class PushPolicyDecision(BaseModel):
    """单条推送判定结果。"""

    allowed: bool
    reason: str
    userId: str
    repoId: str
    recommendationId: Optional[str] = None
    channel: str
    dedupeKey: str
    quietHours: bool = False
    nextAllowedAt: Optional[datetime] = None
    existingEventId: Optional[str] = None
    dailyUsed: int = 0
    dailyLimit: int = 0


class PushEventCreate(BaseModel):
    """通道投递事件上报。"""

    userId: str = Field(min_length=1, max_length=128)
    repoId: str = Field(min_length=1, max_length=255)
    recommendationId: Optional[str] = Field(default=None, max_length=64)
    channel: Literal["inapp", "bark", "telegram", "email"] = "inapp"
    status: Literal["prepared", "sent", "failed", "skipped"] = "sent"
    reason: Optional[str] = Field(default=None, max_length=500)


class PushEventOut(BaseModel):
    """推送事件输出。"""

    id: str
    userId: str
    repoId: str
    recommendationId: Optional[str] = None
    channel: str
    status: str
    dedupeKey: str
    eventKey: str
    reason: Optional[str] = None
    createdAt: Optional[datetime] = None
    updatedAt: Optional[datetime] = None
    sentAt: Optional[datetime] = None


class PushEventListResponse(BaseModel):
    """推送事件列表。"""

    count: int
    items: list[PushEventOut]


class PushEventWriteResponse(BaseModel):
    """推送事件写入结果。"""

    id: str
    created: bool
    updated: bool
    status: str
    eventKey: str
    dedupeKey: str
    sentAt: Optional[datetime] = None


class PushQuietHoursOut(BaseModel):
    """静默时段状态。"""

    start: Optional[str] = None
    end: Optional[str] = None
    timezone: str
    active: bool
    nextAllowedAt: Optional[datetime] = None


class PushLimitsOut(BaseModel):
    """推送限额配置。"""

    dailyLimit: int
    dedupeDays: int
    crossChannel: bool
    retryIntervalMinutes: int


class PushTodayOut(BaseModel):
    """今日事件计数。"""

    prepared: int = 0
    sent: int = 0
    failed: int = 0
    skipped: int = 0
    repos: int = 0


class PushPolicyStatusOut(BaseModel):
    """策略状态快照。"""

    enabled: bool
    quietHours: PushQuietHoursOut
    limits: PushLimitsOut
    today: PushTodayOut
    recentEvents: list[PushEventOut]


class PushDeliveryOut(BaseModel):
    """统一推送投递记录输出（目标已脱敏）。"""

    id: str
    channel: str
    kind: str
    targetMasked: str = ""
    targetType: str = ""
    status: str
    itemCount: int = 0
    messageCount: int = 0
    messageId: Optional[str] = None
    subject: Optional[str] = None
    dedupeKey: str = ""
    receiptStatus: Optional[str] = None
    receiptDetail: Optional[str] = None
    error: Optional[str] = None
    attempts: int = 1
    sourceId: str = ""
    userId: Optional[str] = None
    createdAt: Optional[datetime] = None
    sentAt: Optional[datetime] = None
    finishedAt: Optional[datetime] = None
    deliveredAt: Optional[datetime] = None


class PushReceiptOut(BaseModel):
    """单条送达回执。"""

    id: str
    deliveryId: str
    channel: str
    status: str
    source: str
    externalId: Optional[str] = None
    detail: Optional[str] = None
    occurredAt: Optional[datetime] = None
    createdAt: Optional[datetime] = None


class PushDeliveryDetailOut(PushDeliveryOut):
    """投递详情（附回执时间线）。"""

    receipts: list[PushReceiptOut] = Field(default_factory=list)


class PushRecordListOut(BaseModel):
    """投递记录分页响应。"""

    total: int
    count: int
    page: int
    pageSize: int
    items: list[PushDeliveryOut]


class PushStatsOut(BaseModel):
    """投递统计响应。"""

    windowDays: int
    total: int
    byChannel: dict[str, int]
    byStatus: dict[str, int]
    receipts: dict[str, int]
    deliveryRate: float


class PushReceiptCreate(BaseModel):
    """回执写入请求（服务商回调 / 人工补记）。"""

    deliveryId: str = Field(min_length=1, max_length=64)
    status: Literal["accepted", "delivered", "bounced", "failed"]
    source: Literal["provider", "manual", "system"] = "provider"
    externalId: Optional[str] = Field(default=None, max_length=255)
    detail: Optional[str] = Field(default=None, max_length=1000)
    occurredAt: Optional[datetime] = None


class PushReceiptResponse(BaseModel):
    """回执写入结果。"""

    ok: bool
    delivery: PushDeliveryOut
    receipt: PushReceiptOut


class BackupEntryOut(BaseModel):
    """一份备份产物（文件 + 清单）。"""

    kind: str
    name: str
    path: str
    createdAt: str
    sizeBytes: int
    sha256: str = ""


class BackupKindStatusOut(BaseModel):
    """按类型汇总的备份状态。"""

    count: int
    totalBytes: int
    latest: Optional[BackupEntryOut] = None


class BackupStatusOut(BaseModel):
    """备份目录状态（M5-04）。"""

    backupDir: str
    retention: int
    maxTotalBytes: int
    totalBytes: int
    usagePercent: float
    withinBudget: bool
    freeBytes: Optional[int] = None
    counts: dict[str, int]
    kinds: dict[str, BackupKindStatusOut]
    latest: Optional[BackupEntryOut] = None


class BackupFilesOut(BaseModel):
    """备份产物列表。"""

    count: int
    items: list[BackupEntryOut]


class BackupCheckOut(BaseModel):
    """备份校验 / 演练的单项检查。"""

    name: str
    ok: bool
    detail: str


class BackupVerifyOut(BaseModel):
    """SQLite 快照 / D1 导出校验报告。"""

    ok: bool
    name: str
    path: str
    checks: list[BackupCheckOut]
    tableCounts: dict[str, int]
    sizeBytes: int
    sha256: str
    error: str = ""


class BackupDrillOut(BaseModel):
    """恢复演练报告。"""

    ok: bool
    snapshot: str
    restoredPath: str
    checks: list[BackupCheckOut]
    tableCounts: dict[str, int]
    durationMs: int
    error: str = ""


class BackupActionIn(BaseModel):
    """手动备份 / 校验 / 演练请求。"""

    name: Optional[str] = None
    label: str = ""
    keep: Optional[int] = Field(default=None, ge=1, le=365)
    maxTotalMb: Optional[int] = Field(default=None, ge=0)


# ── 本机一体化只读 API（M5-02 / REQ-202610-0940）────────────────────────
# 字段名与 edge Worker 的前端契约保持一致（camelCase），便于 admin 同源切换。


class LocalAuthUser(BaseModel):
    """本机单用户身份（不经过 GitHub OAuth）。"""

    id: str
    login: str
    name: str
    email: Optional[str] = None
    avatarUrl: Optional[str] = None


class LocalRepoItem(BaseModel):
    """`GET /local/api/repos` 列表项（与 edge RepoItem 对齐）。"""

    id: str
    fullName: str
    description: Optional[str] = None
    summary: Optional[str] = None
    language: Optional[str] = None
    stars: int = 0
    forks: int = 0
    category: Optional[str] = None
    tags: list[str] = Field(default_factory=list)
    updatedAt: Optional[str] = None
    url: str = ""


class LocalTrendingRepo(BaseModel):
    """`GET /local/api/trending` 列表项（与 edge TrendingRepo 对齐）。"""

    id: str
    owner: str
    name: str
    description: Optional[str] = None
    language: Optional[str] = None
    stars: int = 0
    starsToday: int = 0
    url: str = ""
    # 快照字段：无快照时给安全默认值，保证 admin 页面可直接渲染
    snapshotDate: Optional[str] = None
    rank: int = 0
    rankChange: Optional[int] = None
    trend: str = "same"


class LocalTrendingDetail(LocalTrendingRepo):
    """`GET /local/api/trending/{owner}/{name}` 详情。"""

    platform: str = "github"
    techStack: list[str] = Field(default_factory=list)
    summary: Optional[str] = None
    summarySource: str = "empty"
    crawledAt: Optional[str] = None
    isFavorited: bool = False


class LocalTrendingDates(BaseModel):
    """`GET /local/api/trending/dates` 可用快照日期。"""

    dates: list[str] = Field(default_factory=list)
    latest: Optional[str] = None


class LocalTrendingLanguageItem(BaseModel):
    """热榜语言分布项。"""

    language: str
    count: int = 0


class LocalTrendingLanguages(BaseModel):
    """`GET /local/api/trending/languages` 响应。"""

    date: Optional[str] = None
    languages: list[LocalTrendingLanguageItem] = Field(default_factory=list)


class LocalRecommendation(BaseModel):
    """`GET /local/api/recommendations` 列表项（与 edge Recommendation 对齐）。"""

    id: str
    repoId: str = ""
    owner: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
    language: Optional[str] = None
    stars: int = 0
    score: float = 0.0
    reason: Optional[str] = None
    basedOn: list[str] = Field(default_factory=list)
    url: Optional[str] = None
    status: str = "new"
    createdAt: Optional[str] = None


class LocalRecommendationStats(BaseModel):
    """`GET /local/api/recommendations/stats` 各状态数量。"""

    new: int = 0
    saved: int = 0
    dismissed: int = 0
    pushed: int = 0
    clicked: int = 0


class LocalCategoryItem(BaseModel):
    """分类项（含仓库计数）。"""

    id: str
    name: str
    count: int = 0
    description: Optional[str] = None


class LocalTagItem(BaseModel):
    """标签计数项（本机镜像暂未落标签表时为空）。"""

    name: str
    count: int = 0


class LocalCategoriesPayload(BaseModel):
    """`GET /local/api/categories` 响应。"""

    categories: list[LocalCategoryItem] = Field(default_factory=list)
    tags: list[LocalTagItem] = Field(default_factory=list)


class LocalDashboardStats(BaseModel):
    """`GET /local/api/dashboard/stats` 响应。"""

    totalRepos: int = 0
    trendingToday: int = 0
    pendingRecommendations: int = 0
    categoryCount: int = 0


class LocalStatus(BaseModel):
    """`GET /local/api/local/status` 本机模式状态。"""

    mode: str = "local"
    version: str
    readOnly: bool = True
    userId: str
    adminDir: str
    adminReady: bool
    database: str


# ── 监控与告警（M5-03）─────────────────────────────────────────


class MonitoringCheckItemOut(BaseModel):
    """单项健康检查结果。"""

    name: str
    ok: bool
    detail: str
    severity: str = "info"


class MonitoringAlertOut(BaseModel):
    """监控告警。"""

    id: str
    kind: str
    severity: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)
    dedupeKey: str
    status: str
    occurrences: int
    firstSeenAt: Optional[datetime] = None
    lastSeenAt: Optional[datetime] = None
    acknowledgedAt: Optional[datetime] = None
    resolvedAt: Optional[datetime] = None


class MonitoringStatusOut(BaseModel):
    """实时监控状态。"""

    status: str
    checkedAt: str
    checks: list[MonitoringCheckItemOut]
    resources: dict[str, Any]
    findings: list[dict[str, Any]] = Field(default_factory=list)
    thresholds: dict[str, int] = Field(default_factory=dict)
    alerts: list[MonitoringAlertOut] = Field(default_factory=list)
    latestRun: Optional[dict[str, Any]] = None


class MonitoringCheckResultOut(BaseModel):
    """一轮检查的执行结果。"""

    id: str
    status: str
    checkedAt: str
    checks: list[MonitoringCheckItemOut]
    resources: dict[str, Any]
    findings: list[dict[str, Any]]
    alerts: dict[str, int]
    run: dict[str, Any]


class MonitoringHistoryOut(BaseModel):
    """检查历史。"""

    items: list[dict[str, Any]]
    count: int


class MonitoringAlertsOut(BaseModel):
    """告警列表。"""

    items: list[MonitoringAlertOut]
    count: int


class MonitoringLogItemOut(BaseModel):
    """日志文件条目。"""

    name: str
    sizeMb: float
    modifiedAt: str
    expired: bool


class MonitoringLogsOut(BaseModel):
    """日志统计与保留策略。"""

    path: str
    exists: bool
    files: int
    totalMb: float
    budgetMb: int
    retentionDays: int
    oldFiles: int
    items: list[MonitoringLogItemOut] = Field(default_factory=list)


class MonitoringCleanupOut(BaseModel):
    """日志清理结果。"""

    status: str
    path: str
    retentionDays: int
    cutoff: str
    deleted: int
    kept: int
    freedMb: float
    dryRun: bool = False


class ReadyCheckOut(BaseModel):
    """就绪探针响应。"""

    status: str
    service: str
    version: str
    checks: list[MonitoringCheckItemOut]


class DuplicateScanRequest(BaseModel):
    """重复 / 相似项目扫描请求（M6-03）。"""

    scope: Literal["my", "trending", "all"] = "all"
    myRepoIds: Optional[list[str]] = Field(
        default=None,
        max_length=2000,
        description="当前用户收藏库 id 列表；edge 传入以限制跨用户数据",
    )
    minScore: Optional[float] = Field(default=None, ge=0.0, le=1.0, description="最低置信度")
    nameThreshold: Optional[float] = Field(
        default=None, ge=0.5, le=1.0, description="名称相似度阈值"
    )
    maxRepos: Optional[int] = Field(default=None, ge=2, le=5000, description="参与扫描的仓库上限")
    maxClusters: Optional[int] = Field(default=None, ge=1, le=200, description="返回簇上限")


class DuplicateThresholdsOut(BaseModel):
    """本次扫描使用的阈值。"""

    minScore: float
    nameThreshold: float
    descriptionThreshold: float
    vectorThreshold: float
    maxRepos: int
    maxClusters: int


class DuplicateFieldSourceOut(BaseModel):
    """字段建议的来源仓库。"""

    source: str
    repoId: str


class DuplicateFieldSuggestionOut(BaseModel):
    """单个字段的合并建议。"""

    field: str
    value: Any
    from_: DuplicateFieldSourceOut = Field(alias="from")
    reason: str

    model_config = ConfigDict(populate_by_name=True)


class DuplicateSuggestionOut(BaseModel):
    """合并建议：保留项、合并项与字段级建议。"""

    action: Literal["merge", "review"]
    keep: DuplicateFieldSourceOut
    mergeTargets: list[DuplicateFieldSourceOut]
    fields: list[DuplicateFieldSuggestionOut]
    notes: str


class DuplicateSignalsOut(BaseModel):
    """成员与簇内其他成员的相似信号。"""

    nameSimilarity: float = 0.0
    descriptionSimilarity: float = 0.0
    vectorSimilarity: Optional[float] = None
    exactKey: bool = False


class DuplicateMemberOut(BaseModel):
    """重复簇成员（未按用户水合，edge 负责权限过滤）。"""

    source: str
    repoId: str
    fullName: str
    name: str = ""
    description: str = ""
    language: str = ""
    stars: int = 0
    url: str = ""
    platform: str = ""
    categoryId: str = ""
    readmeSummary: str = ""
    techStack: list[str] = Field(default_factory=list)
    role: Literal["canonical", "merge"] = "merge"
    signals: DuplicateSignalsOut = Field(default_factory=DuplicateSignalsOut)


class DuplicateClusterOut(BaseModel):
    """一个重复 / 相似项目簇。"""

    id: str
    kind: Literal["exact", "name", "semantic", "mixed"]
    confidence: float
    reasons: list[str] = Field(default_factory=list)
    members: list[DuplicateMemberOut] = Field(default_factory=list)
    suggestion: DuplicateSuggestionOut


class DuplicateScanResponse(BaseModel):
    """重复检测扫描结果。"""

    scanId: str
    scope: str
    scanned: int
    compared: int
    clusters: list[DuplicateClusterOut]
    tookMs: int
    thresholds: DuplicateThresholdsOut
