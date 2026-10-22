/**
 * 站内通知的纯函数辅助：参数归一化、DTO 转换、推荐 → 通知物化行。
 * 不访问 D1 / 网络，便于 Node 原生测试直接引用。
 */
import type {
  NotificationItem,
  NotificationRow,
  RecommendationRow,
} from '../types';

export const NOTIFICATION_STATUS_FILTERS = ['all', 'unread', 'read'] as const;
export type NotificationStatusFilter = (typeof NOTIFICATION_STATUS_FILTERS)[number];

/** 列表筛选只接受 all / unread / read，其余回退 all。 */
export function normalizeNotificationStatus(
  value: string | null | undefined
): NotificationStatusFilter {
  const raw = String(value ?? '').trim().toLowerCase();
  return (NOTIFICATION_STATUS_FILTERS as readonly string[]).includes(raw)
    ? (raw as NotificationStatusFilter)
    : 'all';
}

/** limit 默认 20，范围 1~100。 */
export function normalizeNotificationLimit(
  value: string | number | null | undefined,
  fallback = 20,
  max = 100
): number {
  const parsed = Number.parseInt(String(value ?? ''), 10);
  if (!Number.isFinite(parsed) || parsed <= 0) return fallback;
  return Math.min(parsed, max);
}

/** offset 默认 0，最大 10000，避免深分页拖慢 D1。 */
export function normalizeNotificationOffset(
  value: string | number | null | undefined,
  max = 10000
): number {
  const parsed = Number.parseInt(String(value ?? ''), 10);
  if (!Number.isFinite(parsed) || parsed < 0) return 0;
  return Math.min(parsed, max);
}

/** 解析 recommendations.based_on（JSON 数组或旧逗号分隔格式）。 */
export function parseBasedOn(raw: string | null | undefined): string[] {
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

/** 通知状态归一化，未知值按未读处理。 */
export function normalizeNotificationState(
  value: string | null | undefined
): NotificationItem['status'] {
  if (value === 'read' || value === 'dismissed') return value;
  return 'unread';
}

/** D1 行 → 前端 DTO。 */
export function toNotificationItem(row: NotificationRow): NotificationItem {
  return {
    id: row.id,
    type: row.type ?? 'recommendation',
    title: row.title,
    body: row.body ?? null,
    url: row.url ?? null,
    repoId: row.repo_id ?? null,
    recommendationId: row.recommendation_id ?? null,
    score: row.score ?? null,
    reason: row.reason ?? null,
    language: row.language ?? null,
    stars: row.stars ?? 0,
    status: normalizeNotificationState(row.status),
    createdAt: row.created_at ?? '',
    readAt: row.read_at ?? null,
  };
}

/** 推荐通知标题：优先 owner/name，其次 name，最后兜底文案。 */
export function recommendationTitle(row: RecommendationRow): string {
  if (row.owner && row.name) return `${row.owner}/${row.name}`;
  if (row.name) return row.name;
  if (row.repo_id) return row.repo_id;
  return '为你推荐的开源项目';
}

/**
 * 把一条 `pushed` 推荐转换成待插入的 notifications 行。
 * id / createdAt 由调用方注入，保证纯函数可测试。
 */
export function buildRecommendationNotification(
  row: RecommendationRow,
  userId: string,
  id: string,
  createdAt: string
): NotificationRow {
  const basedOn = parseBasedOn(row.based_on);
  return {
    id,
    user_id: userId,
    type: 'recommendation',
    title: recommendationTitle(row),
    body: row.description ?? row.reason ?? '为你推荐的开源项目',
    url: row.url ?? null,
    repo_id:
      row.repo_id ??
      (row.owner && row.name ? `${row.owner}/${row.name}` : null),
    recommendation_id: row.id,
    dedupe_key: `recommendation:${row.id}`,
    score: row.score ?? null,
    reason: row.reason ?? null,
    language: row.language ?? null,
    stars: row.stars ?? 0,
    status: 'unread',
    payload: JSON.stringify({ basedOn }),
    created_at: row.created_at ?? createdAt,
    read_at: null,
  };
}

/** 截断内部推送标题 / 正文，避免异常长文本写库。 */
export function truncateText(
  value: unknown,
  max: number
): string {
  return String(value ?? '').trim().slice(0, max);
}
