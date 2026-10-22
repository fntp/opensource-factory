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
}

export interface RecommendationRow {
  id: string;
  user_id: string | null;
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

export interface SyncTaskRow {
  id: string;
  user_id: string | null;
  task_type: string;
  status: string;
  progress: string | null;
  result: string | null;
  error: string | null;
  created_at: string;
  updated_at: string;
  finished_at: string | null;
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
  language: string | null;
  stars: number;
  starsToday: number;
  url: string;
}

/** GET /api/recommendations 列表项 */
export interface Recommendation {
  id: string;
  owner: string | null;
  name: string | null;
  description: string | null;
  language: string | null;
  stars: number;
  score: number;
  reason: string | null;
  basedOn: string[];
  url: string | null;
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

/** 任务进度快照（与 VPS `GET /api/tasks/{taskId}` 的 progress 字段一致） */
export interface TaskProgress {
  phase?: string;
  page?: number;
  pagesTotal?: number | null;
  fetched?: number;
  total?: number | null;
  percent?: number;
  done?: boolean;
}

/** GET /api/tasks 列表项 / GET /api/tasks/{taskId} */
export interface SyncTask {
  taskId: string;
  type: string;
  status: string;
  progress: TaskProgress | null;
  result: unknown;
  error: string | null;
  createdAt: string;
  updatedAt: string;
  finishedAt: string | null;
  stale?: boolean;
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
