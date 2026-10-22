/**
 * 自动分类建议的纯函数工具（M7-02）：状态归一化、参数收敛、稳定 id。
 * 不依赖 Hono / D1，便于 node:test 直接测试。
 */
import { sha256Hex } from '../security/crypto.ts';

export type CategorySuggestionStatus = 'pending' | 'accepted' | 'dismissed';

/** 状态参数：缺省 pending，非法值返回 null（路由层 400）。 */
export function normalizeStatus(value: unknown): CategorySuggestionStatus | 'all' | null {
  if (value === undefined || value === null || value === '') return 'pending';
  return value === 'pending' || value === 'accepted' || value === 'dismissed' || value === 'all'
    ? value
    : null;
}

/** 列表分页：1~200，默认 100。 */
export function clampLimit(value: unknown, fallback = 100, max = 200): number {
  const parsed = typeof value === 'number' ? value : Number.parseInt(String(value ?? ''), 10);
  if (!Number.isFinite(parsed)) return fallback;
  return Math.min(max, Math.max(1, Math.trunc(parsed)));
}

/** 每仓库建议条数：1~5，默认 3。 */
export function clampPerRepo(value: unknown): number {
  return clampLimit(value, 3, 5);
}

/** 置信度阈值：0~1，默认 0.55。 */
export function clampMinScore(value: unknown): number {
  const parsed = typeof value === 'number' ? value : Number.parseFloat(String(value ?? ''));
  if (!Number.isFinite(parsed)) return 0.55;
  return Math.min(1, Math.max(0, parsed));
}

/** 偏移量：>=0，默认 0。 */
export function clampOffset(value: unknown): number {
  const parsed = typeof value === 'number' ? value : Number.parseInt(String(value ?? ''), 10);
  if (!Number.isFinite(parsed)) return 0;
  return Math.max(0, Math.trunc(parsed));
}

/** 分类名归一化：去首尾空白、压缩连续空白。 */
export function normalizeCategoryName(value: string): string {
  return value.trim().replace(/\s+/g, ' ');
}

/** 稳定建议 id：同一用户 + 仓库 + 分类始终得到同一 id。 */
export async function stableSuggestionId(
  userId: string,
  repoId: string,
  categoryName: string
): Promise<string> {
  const digest = await sha256Hex(
    `${userId}|${repoId}|${normalizeCategoryName(categoryName).toLowerCase()}`
  );
  return `cs_${digest.slice(0, 32)}`;
}

/** 分类 id：按分类名生成稳定 id，便于自动建分类后重复采纳。 */
export async function categoryIdForName(name: string): Promise<string> {
  const digest = await sha256Hex(normalizeCategoryName(name).toLowerCase());
  return `cat_${digest.slice(0, 16)}`;
}

/** 标签聚合列（GROUP_CONCAT 逗号分隔）→ 去重数组。 */
export function splitTags(value: string | null | undefined): string[] {
  if (!value) return [];
  return [...new Set(value.split(',').map((item) => item.trim()).filter(Boolean))];
}

/** 合并 VPS 与本地建议：同业务线 / 同分类名只保留分数更高的一条。 */
export function mergeSuggestions<T extends { categoryName: string; score: number }>(
  ...groups: T[][]
): T[] {
  const merged = new Map<string, T>();
  for (const group of groups) {
    for (const item of group) {
      const key = normalizeCategoryName(item.categoryName).toLowerCase();
      const existing = merged.get(key);
      if (!existing || item.score > existing.score) merged.set(key, item);
    }
  }
  return [...merged.values()].sort((a, b) => b.score - a.score);
}
