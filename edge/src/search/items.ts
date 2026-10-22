/**
 * 搜索结果水合（语义搜索 / 相似推荐共用）。
 *
 * 输入是按 id 命中的 `{source, repoId, score}`，输出完整项目卡片：
 * - `my` 行按当前用户过滤，避免跨用户泄漏；
 * - `trending` 行为全局数据；
 * - 行已删除 / 无权限时跳过，不阻断整批结果。
 */
import type { Env, RepoRow, SearchResultItem, TrendingRow } from '../types';
import { all } from '../db';

const HYDRATE_CHUNK = 50;

export interface SimilarHit {
  source: string;
  repoId: string;
  score: number;
}

export function chunk<T>(items: T[], size: number): T[][] {
  const groups: T[][] = [];
  for (let index = 0; index < items.length; index += size) {
    groups.push(items.slice(index, index + size));
  }
  return groups;
}

export function placeholders(count: number): string {
  return Array.from({ length: count }, () => '?').join(', ');
}

export function reasonFor(
  score: number,
  language: string,
  description: string,
  keyword = false,
  seedName?: string
): string {
  const percent = Math.round(Math.max(0, Math.min(1, score)) * 100);
  const prefix = keyword
    ? `关键词匹配度 ${percent}%。`
    : seedName
      ? `与「${seedName}」语义相似度 ${percent}%。`
      : `与查询语义相似度 ${percent}%。`;
  const parts = [prefix];
  if (language) parts.push(`主要使用 ${language} 开发；`);
  if (description) parts.push(`项目简介：${description.slice(0, 80)}。`);
  return parts.join('');
}

export function toSearchItem(
  row: RepoRow | TrendingRow,
  source: 'my' | 'trending',
  score: number,
  keyword = false,
  seedName?: string
): SearchResultItem {
  const description = row.description ?? ('readme_summary' in row ? row.readme_summary : null) ?? '';
  const language = row.language ?? '';
  const owner = row.owner ?? row.id.split('/')[0] ?? '';
  return {
    id: row.id,
    source,
    fullName: owner ? `${owner}/${row.name}` : row.id,
    name: row.name,
    description,
    language,
    stars: row.stars ?? 0,
    starsToday: 'stars_today' in row ? (row.stars_today ?? 0) : 0,
    url: row.html_url,
    score: Math.round(score * 10000) / 10000,
    reason: reasonFor(score, language, description, keyword, seedName),
  };
}

/** 按 id 批量取行；`my` 额外按 user_id 过滤，避免跨用户泄漏。 */
export async function hydrateHits(
  env: Env,
  userId: string,
  hits: SimilarHit[],
  limit: number,
  seedName?: string
): Promise<SearchResultItem[]> {
  const wanted = hits.slice(0, Math.max(limit * 4, limit));
  const myIds = [...new Set(wanted.filter((h) => h.source === 'my').map((h) => h.repoId))];
  const trendingIds = [
    ...new Set(wanted.filter((h) => h.source === 'trending').map((h) => h.repoId)),
  ];

  const rows = new Map<string, { row: RepoRow | TrendingRow; source: 'my' | 'trending' }>();
  for (const group of chunk(myIds, HYDRATE_CHUNK)) {
    const found = await all<RepoRow>(
      env.DB,
      `SELECT * FROM my_repositories WHERE id IN (${placeholders(group.length)}) AND user_id = ?`,
      [...group, userId]
    );
    for (const row of found) rows.set(`my:${row.id}`, { row, source: 'my' });
  }
  for (const group of chunk(trendingIds, HYDRATE_CHUNK)) {
    const found = await all<TrendingRow>(
      env.DB,
      `SELECT * FROM trending_repositories WHERE id IN (${placeholders(group.length)})`,
      group
    );
    for (const row of found) rows.set(`trending:${row.id}`, { row, source: 'trending' });
  }

  const items: SearchResultItem[] = [];
  for (const hit of wanted) {
    if (items.length >= limit) break;
    const entry = rows.get(`${hit.source}:${hit.repoId}`);
    if (!entry) continue;
    items.push(toSearchItem(entry.row, entry.source, hit.score, false, seedName));
  }
  return items;
}
