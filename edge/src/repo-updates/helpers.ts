/**
 * 收藏项目更新提醒（M7-04）纯函数辅助：参数归一化、DTO 转换、通知标题。
 * 不访问 D1 / 网络，便于 Node 原生测试直接引用。
 */
import type { RepoUpdateRow } from '../types';
import { truncateText } from '../notifications/helpers';

export const UPDATE_STATUS_FILTERS = ['all', 'unread', 'read', 'dismissed'] as const;
export type UpdateStatusFilter = (typeof UPDATE_STATUS_FILTERS)[number];

export const UPDATE_TYPE_FILTERS = ['all', 'release', 'major'] as const;
export type UpdateTypeFilter = (typeof UPDATE_TYPE_FILTERS)[number];

/** 状态筛选；未知值回退 all。 */
export function normalizeUpdateStatus(
  value: string | null | undefined
): UpdateStatusFilter {
  const raw = String(value ?? '').trim().toLowerCase();
  return (UPDATE_STATUS_FILTERS as readonly string[]).includes(raw)
    ? (raw as UpdateStatusFilter)
    : 'all';
}

/** 类型筛选；未知值回退 all。 */
export function normalizeUpdateType(
  value: string | null | undefined
): UpdateTypeFilter {
  const raw = String(value ?? '').trim().toLowerCase();
  return (UPDATE_TYPE_FILTERS as readonly string[]).includes(raw)
    ? (raw as UpdateTypeFilter)
    : 'all';
}

/** limit 默认 20，范围 1~100。 */
export function normalizeUpdateLimit(
  value: string | number | null | undefined,
  fallback = 20,
  max = 100
): number {
  const parsed = Number.parseInt(String(value ?? ''), 10);
  if (!Number.isFinite(parsed) || parsed <= 0) return fallback;
  return Math.min(parsed, max);
}

/** offset 默认 0，最大 10000。 */
export function normalizeUpdateOffset(
  value: string | number | null | undefined,
  max = 10000
): number {
  const parsed = Number.parseInt(String(value ?? ''), 10);
  if (!Number.isFinite(parsed) || parsed < 0) return 0;
  return Math.min(parsed, max);
}

/** 版本状态归一化：只有 read / dismissed 生效，其余按 unread。 */
export function normalizeUpdateState(
  value: string | null | undefined
): 'unread' | 'read' | 'dismissed' {
  const raw = String(value ?? '').trim().toLowerCase();
  if (raw === 'read' || raw === 'dismissed') return raw;
  return 'unread';
}

/** 更新类型归一化：未知按 release。 */
export function normalizeUpdateKind(value: string | null | undefined): 'release' | 'major' {
  return String(value ?? '').trim().toLowerCase() === 'major' ? 'major' : 'release';
}

/** 稳定 ID：同一用户 + 仓库 + 版本只落一行；各段 URL 编码避免 `/` 破坏路由参数。 */
export function buildRepoUpdateId(
  userId: string,
  repoId: string,
  version: string
): string {
  return `repo-update:${encodeURIComponent(truncateText(userId, 128))}:${encodeURIComponent(
    truncateText(repoId, 255)
  )}:${encodeURIComponent(truncateText(version, 128))}`;
}

/** 通知标题：重大变更更醒目，普通版本突出仓库名。 */
export function repoUpdateNotificationTitle(
  type: string | null | undefined,
  repoName: string | null | undefined,
  version: string
): string {
  const name = truncateText(repoName, 255) || '收藏项目';
  return normalizeUpdateKind(type) === 'major'
    ? `【重大变更】${name} ${version}`
    : `${name} 发布新版本 ${version}`;
}

/** D1 行 → 前端 DTO（camelCase）。 */
export function toRepoUpdateItem(row: RepoUpdateRow) {
  return {
    id: row.id,
    repoId: row.repo_id,
    repoName: row.repo_name ?? row.repo_id.split('/').pop() ?? row.repo_id,
    repoUrl: row.repo_url ?? `https://github.com/${row.repo_id}`,
    type: normalizeUpdateKind(row.type),
    version: row.version,
    title: row.title,
    summary: row.summary ?? '',
    url: row.url ?? '',
    publishedAt: row.published_at,
    detectedAt: row.detected_at,
    status: normalizeUpdateState(row.status),
    readAt: row.read_at,
  };
}
