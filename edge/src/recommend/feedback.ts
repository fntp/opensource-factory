/**
 * 推荐反馈的纯函数：状态过滤、DTO 映射、反馈行构造。
 *
 * 与路由分离，便于 `node --test` 直接导入（不依赖 D1 / Hono 运行时）。
 */
import type {
  Recommendation,
  RecommendationFeedbackAction,
  RecommendationFeedbackRow,
  RecommendationRow,
} from '../types';

export const RECOMMENDATION_STATUSES = ['new', 'saved', 'dismissed', 'pushed'] as const;
export type RecommendationStatusFilter = 'new' | 'saved' | 'dismissed' | 'all';

const DISMISS_REASON_MAX = 200;

/** 解析 based_on（JSON 数组字符串）为 string[]，兼容旧的逗号分隔格式。 */
export function parseBasedOn(raw: string | null): string[] {
  if (!raw) return [];
  try {
    const parsed = JSON.parse(raw) as unknown;
    if (Array.isArray(parsed)) return parsed.map((value) => String(value));
    return [];
  } catch {
    return raw
      .split(',')
      .map((item) => item.trim())
      .filter(Boolean);
  }
}

/** 从推荐行推导稳定的仓库 id（`owner/name`），历史数据回退到 URL。 */
export function deriveRepoId(row: Pick<RecommendationRow, 'repo_id' | 'owner' | 'name' | 'url'>): string | null {
  const stored = (row.repo_id ?? '').trim();
  if (stored) return stored;
  const owner = (row.owner ?? '').trim();
  const name = (row.name ?? '').trim();
  if (owner && name) return `${owner}/${name}`;
  const url = (row.url ?? '').trim();
  const match = /github\.com\/([^/]+)\/([^/?#]+)/i.exec(url);
  if (match?.[1] && match?.[2]) return `${match[1]}/${match[2]}`;
  return null;
}

/** 归一化状态筛选参数：非法值回退到 `new`。 */
export function normalizeStatusFilter(raw: string | undefined | null): RecommendationStatusFilter {
  const value = (raw ?? '').trim().toLowerCase();
  if (value === 'saved' || value === 'dismissed' || value === 'all') return value;
  return 'new';
}

/** 归一化忽略原因：去空白、截断到 200 字；空串返回 null。 */
export function normalizeDismissReason(raw: unknown): string | null {
  if (typeof raw !== 'string') return null;
  const trimmed = raw.trim();
  if (!trimmed) return null;
  return trimmed.slice(0, DISMISS_REASON_MAX);
}

/** DB 行 → 前端 DTO（含状态、仓库 id 与创建时间）。 */
export function toRecommendation(row: RecommendationRow): Recommendation {
  return {
    id: row.id,
    repoId: deriveRepoId(row),
    owner: row.owner ?? null,
    name: row.name ?? null,
    description: row.description ?? null,
    language: row.language ?? null,
    stars: row.stars ?? 0,
    score: row.score ?? 0,
    reason: row.reason ?? null,
    basedOn: parseBasedOn(row.based_on),
    url: row.url ?? null,
    status: row.status ?? 'new',
    createdAt: row.created_at ?? null,
  };
}

/** 构造一条反馈记录（调用方负责生成 id / 时间）。 */
export function buildFeedbackRow(input: {
  id: string;
  userId: string;
  recommendationId: string;
  repoId: string;
  action: RecommendationFeedbackAction;
  reason?: string | null;
  createdAt?: string;
}): RecommendationFeedbackRow {
  return {
    id: input.id,
    user_id: input.userId,
    recommendation_id: input.recommendationId,
    repo_id: input.repoId,
    action: input.action,
    reason: input.reason ?? null,
    created_at: input.createdAt ?? new Date().toISOString(),
  };
}

/** 生成任务推送时是否保留用户已产生的状态（saved / dismissed 不被覆盖）。 */
export function shouldKeepUserStatus(status: string | null): boolean {
  return status === 'saved' || status === 'dismissed';
}
