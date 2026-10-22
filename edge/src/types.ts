/**
 * 类型定义：Env 绑定 + 数据库行 + API 响应实体
 * 前端管理后台依赖的 JSON 形状见各实体接口。
 */
import type { LicenseInfo } from './license/compliance';

/** Worker 运行时绑定（wrangler.toml vars + secrets） */
export interface Env {
  // D1 数据库
  DB: D1Database;
  // GitHub OAuth（CLIENT_SECRET 通过 `wrangler secret put` 设置）
  GITHUB_CLIENT_ID: string;
  GITHUB_CLIENT_SECRET: string;
  // 会话/签名密钥
  SESSION_SECRET: string;
  // 允许的前端 origin（CORS 精确回显）
  ALLOWED_ORIGIN: string;
  // 本地 VPS Python 节点（FastAPI + Celery），可为空
  VPS_NODE_URL: string;
  // 可选：边缘 → VPS 节点的内部调用令牌（当前）
  INTERNAL_TOKEN?: string;
  // 可选：上一枚内部令牌（轮换过渡期仍接受；验证完成后删除）
  INTERNAL_TOKEN_PREVIOUS?: string;
  // 接口限流（M5-05）：默认开启，显式 false / 0 关闭
  RATE_LIMIT_ENABLED?: string;
  RATE_LIMIT_READ_PER_MINUTE?: string;
  RATE_LIMIT_WRITE_PER_MINUTE?: string;
  RATE_LIMIT_AUTH_PER_MINUTE?: string;
  // 登录防护（M5-05）
  LOGIN_MAX_FAILURES?: string;
  LOGIN_FAILURE_WINDOW_SECONDS?: string;
  LOGIN_LOCKOUT_SECONDS?: string;
  // Vectorize 向量索引绑定（未配置时内部向量接口返回 503）
  VECTORIZE?: Vectorize;
}

// ── 数据库行 ────────────────────────────────────────────────────

export interface UserRow {
  id: string;
  login: string;
  name: string | null;
  email: string | null;
  avatar_url: string | null;
  created_at: string;
}

export interface SessionRow {
  id: string;
  user_id: string;
  created_at: string;
  expires_at: string;
}

export interface TagSuggestionRow {
  id: string;
  user_id: string;
  repo_id: string;
  tag_name: string;
  normalized_name: string;
  category: string;
  score: number;
  reason: string | null;
  evidence: string | null;
  status: string;
  created_at: string;
  updated_at: string;
  /** JOIN my_repositories 得到的展示字段（可选） */
  repo_name?: string | null;
  repo_url?: string | null;
  readme_summary?: string | null;
}

export interface RepoRow {
  id: string;
  platform: string;
  name: string;
  description: string | null;
  html_url: string;
  stars: number | null;
  language: string | null;
  readme_summary: string | null;
  category_id: string | null;
  created_at: string | null;
  user_id: string | null;
  owner: string | null;
  forks: number | null;
  updated_at: string | null;
  synced_at: string | null;
  /** 最近一次 push（GitHub pushed_at，M6-05） */
  pushed_at?: string | null;
  /** 未关闭 issue / PR 数（M6-05） */
  open_issues_count?: number | null;
  /** 是否归档（SQLite 0/1，M6-05） */
  archived?: number | null;
  /** 是否被 GitHub 禁用（SQLite 0/1，M6-05） */
  disabled?: number | null;
  /** 最近一次健康度计算结果（M6-05） */
  health_status?: string | null;
  health_score?: number | null;
  health_checked_at?: string | null;
  /** License 识别（M6-06） */
  license_spdx: string | null;
  license_name: string | null;
  license_source: string | null;
  license_checked_at: string | null;
  /** JOIN 得到的分类名（可选） */
  category_name?: string | null;
  /** 聚合得到的标签名列表（可选） */
  tag_names?: string | null;
}

export interface TrendingRow {
  id: string;
  platform: string;
  name: string;
  html_url: string;
  stars_today: number | null;
  description: string | null;
  tech_stack: string | null;
  crawled_at: string | null;
  owner: string | null;
  language: string | null;
  stars: number | null;
  /** VPS 生成的中文摘要（M2-04） */
  readme_summary: string | null;
  /** License 识别（M6-06） */
  license_spdx: string | null;
  license_name: string | null;
  license_source: string | null;
  license_checked_at: string | null;
}

/** 热榜按日快照（M2-05） */
export interface TrendingSnapshotRow {
  snapshot_date: string;
  repo_id: string;
  platform: string;
  owner: string | null;
  name: string;
  html_url: string;
  description: string | null;
  language: string | null;
  tech_stack: string | null;
  stars: number | null;
  stars_today: number | null;
  rank: number | null;
  language_rank: number | null;
  star_delta: number | null;
  rank_delta: number | null;
  appearances: number | null;
  is_new: number | null;
  trend: string | null;
  trending_pages: string | null;
  /** LEFT JOIN trending_repositories 得到的 License 字段（M6-06，可选） */
  license_spdx?: string | null;
  license_name?: string | null;
  license_source?: string | null;
  license_checked_at?: string | null;
}

/** GET /api/trending/:owner/:name 详情 */
export interface TrendingRepoDetail extends TrendingRepo {
  platform: string;
  techStack: string[];
  summary: string | null;
  summarySource: 'readme' | 'description' | 'tech' | 'empty';
  crawledAt: string | null;
  isFavorited: boolean;
}

/** POST /api/trending/:owner/:name/favorite 响应 */
export interface FavoriteResult {
  favorited: boolean;
  created?: boolean;
  removed?: boolean;
  repoId: string;
}

export interface RecommendationRow {
  id: string;
  user_id: string | null;
  repo_id?: string | null;
  owner: string | null;
  name: string | null;
  description: string | null;
  language: string | null;
  stars: number | null;
  score: number | null;
  reason: string | null;
  based_on: string | null;
  url: string | null;
  status: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export type RecommendationFeedbackAction = 'saved' | 'dismissed' | 'clicked';

export interface RecommendationFeedbackRow {
  id: string;
  user_id: string;
  recommendation_id: string;
  repo_id: string;
  action: RecommendationFeedbackAction;
  reason: string | null;
  created_at: string;
}

export interface NotificationRow {
  id: string;
  user_id: string;
  type: string | null;
  title: string;
  body: string | null;
  url: string | null;
  repo_id: string | null;
  recommendation_id: string | null;
  dedupe_key: string | null;
  score: number | null;
  reason: string | null;
  language: string | null;
  stars: number | null;
  status: string | null;
  payload: string | null;
  created_at: string | null;
  read_at: string | null;
}

/** 推送偏好（M4-06） */
export interface PushPreferenceRow {
  user_id: string;
  enabled: number;
  time_of_day: string;
  timezone: string;
  min_score: number;
  min_quality_score: number;
  channel_inapp: number;
  channel_bark: number;
  channel_telegram: number;
  channel_email: number;
  updated_at: string | null;
}

export interface CategoryRow {
  id: string;
  name: string;
  parent_id: string | null;
  description: string | null;
  sort_order: number | null;
}

export interface CategoryWithCountRow extends CategoryRow {
  count: number;
}

export interface TagCountRow {
  name: string;
  count: number;
}

// ── API 响应实体（前端契约）─────────────────────────────────────

/** GET /api/auth/me */
export interface AuthUser {
  id: string;
  login: string;
  name: string | null;
  email: string | null;
  avatarUrl: string | null;
}

/** GET /api/repos 列表项 */
export interface RepoItem {
  id: string;
  fullName: string;
  description: string | null;
  /** VPS 生成的 README 中文摘要（可为空） */
  summary?: string | null;
  language: string | null;
  stars: number;
  forks: number;
  category: string | null;
  tags: string[];
  updatedAt: string | null;
  url: string;
  /** 项目健康度（M6-05，始终由 D1 字段本地计算，VPS 回写后可覆盖） */
  health: RepoHealth;
  /** License 合规提示（M6-06；未识别过为 null） */
  license?: LicenseInfo | null;
}

/** 项目健康度状态（M6-05） */
export type HealthStatus = 'active' | 'attention' | 'stale' | 'archived' | 'unknown';

export interface RepoHealth {
  status: HealthStatus;
  label: string;
  score: number;
  lastPushAt: string | null;
  daysSincePush: number | null;
  openIssues: number;
  archived: boolean;
  reasons: string[];
  checkedAt: string | null;
}

/** GET /api/repos/health 汇总 */
export interface RepoHealthSummary {
  total: number;
  active: number;
  attention: number;
  stale: number;
  archived: number;
  unknown: number;
  averageScore: number;
}

/** GET /api/trending 列表项 */
export interface TrendingRepo {
  id: string;
  owner: string;
  name: string;
  description: string | null;
  /** VPS 生成的中文摘要（可为空） */
  summary?: string | null;
  language: string | null;
  stars: number;
  starsToday: number;
  url: string;
  /** 快照日期（YYYY-MM-DD）；兼容旧数据时取 crawled_at */
  snapshotDate: string | null;
  /** 当日排名（从 1 开始） */
  rank: number;
  /** 相对上一快照日的排名变化（正数 = 上升，null = 新上榜） */
  rankChange: number | null;
  /** 趋势类型（steady 统一映射为 same） */
  trend: 'up' | 'down' | 'new' | 'same';
  /** M2-05 扩展字段（详情页 / 历史趋势备用） */
  languageRank?: number;
  starDelta?: number;
  rankDelta?: number;
  appearances?: number;
  isNew?: boolean;
  /** License 合规提示（M6-06；未识别过为 null） */
  license?: LicenseInfo | null;
}

/** GET /api/recommendations 列表项 */
export interface Recommendation {
  id: string;
  repoId: string | null;
  owner: string | null;
  name: string | null;
  description: string | null;
  language: string | null;
  stars: number;
  score: number;
  reason: string | null;
  basedOn: string[];
  url: string | null;
  status: string;
  createdAt: string | null;
}

/** GET /api/recommendations/stats 计数 */
export interface RecommendationStats {
  new: number;
  saved: number;
  dismissed: number;
  pushed: number;
  clicked: number;
}

/** GET /api/notifications 列表项 */
export interface NotificationItem {
  id: string;
  type: string;
  title: string;
  body: string | null;
  url: string | null;
  repoId: string | null;
  recommendationId: string | null;
  score: number | null;
  reason: string | null;
  language: string | null;
  stars: number;
  status: 'unread' | 'read' | 'dismissed';
  createdAt: string;
  readAt: string | null;
}

/** GET /api/notifications */
export interface NotificationsPayload {
  items: NotificationItem[];
  total: number;
  unread: number;
  limit: number;
  offset: number;
  hasMore: boolean;
}

/** GET /api/categories 列表项（扁平结构，前端按 parentId 组树） */
export interface CategoryItem {
  id: string;
  name: string;
  parentId: string | null;
  description: string | null;
  sortOrder: number;
  count: number;
}

/** GET /api/categories */
export interface CategoriesPayload {
  categories: CategoryItem[];
  tags: Array<{ name: string; count: number }>;
}

/** GET /api/dashboard/stats */
export interface DashboardStats {
  totalRepos: number;
  trendingToday: number;
  pendingRecommendations: number;
  categoryCount: number;
}

/** POST /api/search/semantic 结果条目 */
/** 查询理解（同义词 / 技术栈词表，M3-10） */
export interface SearchUnderstanding {
  query: string;
  rewritten: string;
  expanded: boolean;
  techStack: string[];
  concepts: string[];
  terms: string[];
  keywordTerms: string[];
  maxTerms: number;
}

export interface SearchResultItem {
  id: string;
  source: 'my' | 'trending';
  fullName: string;
  name: string;
  description: string;
  language: string;
  stars: number;
  starsToday: number;
  url: string;
  score: number;
  reason: string;
  /** README 全文命中片段（M6-01） */
  snippet?: string;
  matchedTerms?: string[];
}

/** POST /api/search/semantic、/api/search/fulltext 响应 */
export interface SearchResponse {
  query: string;
  mode: 'vectorize' | 'local' | 'keyword' | 'fts' | 'like';
  count: number;
  tookMs: number;
  backend: string;
  model: string;
  dim: number;
  items: SearchResultItem[];
  scope: 'my' | 'trending' | 'all';
  understanding?: SearchUnderstanding;
  /** 全文检索分词结果（M6-01） */
  terms?: string[];
}

/** GET /api/similar 响应（相似项目「看了又看」） */
export interface SimilarResponse {
  source: 'my' | 'trending';
  repoId: string;
  mode: 'local' | 'keyword';
  count: number;
  tookMs: number;
  items: SearchResultItem[];
}

/** 重复 / 相似项目检测（M6-03） */
export type DuplicateScope = 'my' | 'trending' | 'all';
export type DuplicateKind = 'exact' | 'name' | 'semantic' | 'mixed';
export type DuplicateSource = 'my' | 'trending';

export interface DuplicateSignals {
  nameSimilarity: number;
  descriptionSimilarity: number;
  vectorSimilarity: number | null;
  exactKey: boolean;
}

export interface DuplicateMember {
  source: DuplicateSource;
  repoId: string;
  fullName: string;
  name: string;
  description: string;
  language: string;
  stars: number;
  url: string;
  platform: string;
  categoryId: string;
  readmeSummary: string;
  techStack: string[];
  role: 'canonical' | 'merge';
  signals: DuplicateSignals;
}

export interface DuplicateFieldSuggestion {
  field: string;
  value: unknown;
  from: { source: DuplicateSource; repoId: string };
  reason: string;
}

export interface DuplicateSuggestion {
  action: 'merge' | 'review';
  keep: { source: DuplicateSource; repoId: string };
  mergeTargets: Array<{ source: DuplicateSource; repoId: string }>;
  fields: DuplicateFieldSuggestion[];
  notes: string;
}

export interface DuplicateCluster {
  id: string;
  kind: DuplicateKind;
  confidence: number;
  reasons: string[];
  members: DuplicateMember[];
  suggestion: DuplicateSuggestion;
}

export interface DuplicateThresholds {
  minScore: number;
  nameThreshold: number;
  descriptionThreshold: number;
  vectorThreshold: number;
  maxRepos: number;
  maxClusters: number;
}

export interface DuplicateScanResponse {
  scanId: string;
  scope: DuplicateScope;
  mode: 'vps' | 'hybrid' | 'local';
  count: number;
  scanned: number;
  compared: number;
  tookMs: number;
  thresholds: DuplicateThresholds;
  dismissedCount: number;
  clusters: DuplicateCluster[];
}

export interface DuplicateDismissal {
  clusterId: string;
  repoIds: string[];
  reason: string | null;
  createdAt: string | null;
}

// ── 自动分类建议（M7-02）──────────────────────────────────────

export interface CategorySuggestionRow {
  id: string;
  user_id: string;
  repo_id: string;
  category_name: string;
  business_line: string;
  score: number;
  reason: string | null;
  evidence: string | null;
  status: 'pending' | 'accepted' | 'dismissed';
  created_at: string | null;
  updated_at: string | null;
}

export interface CategorySuggestionListItem {
  id: string;
  repoId: string;
  repoName: string;
  repoUrl: string;
  summary: string | null;
  categoryName: string;
  businessLine: string;
  score: number;
  reason: string | null;
  evidence: string | null;
  status: 'pending' | 'accepted' | 'dismissed';
  currentCategory: string | null;
  updatedAt: string | null;
}

export interface CategorySuggestionSummary {
  total: number;
  pending: number;
  accepted: number;
  dismissed: number;
  repos: number;
  avgScore: number;
}

export interface CategorySuggestionListResponse {
  items: CategorySuggestionListItem[];
  summary: CategorySuggestionSummary;
  categories: Array<{ id: string; name: string }>;
}

/** GitHub /user 接口返回（仅取所需字段） */
export interface GithubUser {
  id: number;
  login: string;
  name: string | null;
  email: string | null;
  avatar_url: string | null;
}

/** GitHub OAuth token 响应 */
export interface GithubTokenResponse {
  access_token?: string;
  token_type?: string;
  scope?: string;
  error?: string;
  error_description?: string;
}

// ── 精选报告（M7-03）───────────────────────────────────────────

export type ReportKind = 'weekly' | 'monthly';
export type ReportStatus = 'ready' | 'empty';
export type ReportItemSource = 'collection' | 'recommendation' | 'trending';

/** 报告统计口径（数字均为报告生成时快照） */
export interface ReportStats {
  totalRepos: number;
  newRepos: number;
  totalStars: number;
  newStars: number;
  categoryCount: number;
  languageCount: number;
  recommendationCount: number;
  trendingCount: number;
  topLanguage: string | null;
  topCategory: string | null;
}

/** 报告中的一条精选项目 */
export interface ReportItem {
  id: string;
  name: string;
  url: string;
  description: string | null;
  language: string | null;
  stars: number;
  starsDelta: number;
  reason: string | null;
  source: ReportItemSource;
  category: string | null;
  tags: string[];
}

export interface ReportSection {
  key: 'new' | 'top' | 'recommendations' | 'trending';
  title: string;
  description: string;
  items: ReportItem[];
}

/** curated_reports 数据库行 */
export interface CuratedReportRow {
  id: string;
  user_id: string;
  kind: string;
  period_start: string;
  period_end: string;
  title: string;
  summary: string;
  stats: string;
  sections: string;
  markdown: string;
  status: string;
  generated_at: string;
}

/** GET /api/reports 列表项 */
export interface ReportSummary {
  id: string;
  kind: ReportKind;
  title: string;
  periodStart: string;
  periodEnd: string;
  status: ReportStatus;
  summary: string;
  stats: ReportStats;
  generatedAt: string;
}

/** GET /api/reports/:id */
export interface CuratedReport extends ReportSummary {
  sections: ReportSection[];
  markdown: string;
}

/** Hono 上下文变量（挂载当前用户） */
export interface Variables {
  user: UserRow | null;
}
