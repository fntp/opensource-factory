/**
 * 类型定义：Env 绑定 + 数据库行 + API 响应实体
 * 前端管理后台依赖的 JSON 形状见各实体接口。
 */

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
  // 可选：边缘 → VPS 节点的内部调用令牌
  INTERNAL_TOKEN?: string;
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

/** GET /api/categories */
export interface CategoriesPayload {
  categories: Array<{ id: string; name: string; count: number; description: string | null }>;
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
}

/** POST /api/search/semantic 响应 */
export interface SearchResponse {
  query: string;
  mode: 'vectorize' | 'local' | 'keyword';
  count: number;
  tookMs: number;
  backend: string;
  model: string;
  dim: number;
  items: SearchResultItem[];
  scope: 'my' | 'trending' | 'all';
  understanding?: SearchUnderstanding;
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

/** Hono 上下文变量（挂载当前用户） */
export interface Variables {
  user: UserRow | null;
}
