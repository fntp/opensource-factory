/**
 * 热榜详情纯函数：摘要回退、技术栈拆分与 DTO 映射。
 * 不依赖 Hono / D1，便于在 node:test 中直接覆盖。
 */
import type { TrendingRepoDetail, TrendingRow } from '../types';
import { licenseFromRow } from '../license/compliance.ts';

export type SummarySource = TrendingRepoDetail['summarySource'];

/** 逗号分隔的技术栈 → 去重数组 */
export function parseTechStack(value: string | null | undefined): string[] {
  if (!value) return [];
  const seen = new Set<string>();
  const result: string[] = [];
  for (const raw of value.split(',')) {
    const item = raw.trim();
    if (item && !seen.has(item)) {
      seen.add(item);
      result.push(item);
    }
  }
  return result;
}

/** 摘要优先级：M2-04 README 摘要 → 项目描述 → 技术栈提示 → 空 */
export function buildTrendingSummary(
  row: Pick<TrendingRow, 'readme_summary' | 'description' | 'tech_stack'>
): { summary: string | null; source: SummarySource } {
  const readme = (row.readme_summary ?? '').trim();
  if (readme) return { summary: readme, source: 'readme' };

  const description = (row.description ?? '').trim();
  if (description) return { summary: description, source: 'description' };

  const tech = parseTechStack(row.tech_stack);
  if (tech.length > 0) {
    return { summary: `该项目主要使用 ${tech.join(', ')}。`, source: 'tech' };
  }
  return { summary: null, source: 'empty' };
}

/** 把 D1 行映射为详情 DTO；owner 缺失时从 id 推导 */
export function toTrendingDetail(row: TrendingRow, isFavorited = false): TrendingRepoDetail {
  const owner = row.owner ?? row.id.split('/')[0] ?? '';
  const { summary, source } = buildTrendingSummary(row);
  return {
    id: row.id,
    platform: row.platform,
    owner,
    name: row.name,
    description: row.description ?? null,
    language: row.language ?? null,
    stars: row.stars ?? 0,
    starsToday: row.stars_today ?? 0,
    url: row.html_url,
    // 详情接口不查询快照，趋势字段给中性默认值（列表页仍按快照展示）
    snapshotDate: row.crawled_at ?? null,
    rank: 0,
    rankChange: null,
    trend: 'same',
    techStack: parseTechStack(row.tech_stack),
    summary,
    summarySource: source,
    crawledAt: row.crawled_at ?? null,
    isFavorited,
    license: licenseFromRow(row),
  };
}

/** 拆分 owner/repo；非法 id 返回 null */
export function splitRepoId(id: string): { owner: string; name: string } | null {
  const parts = id.trim().split('/');
  if (parts.length !== 2 || !parts[0] || !parts[1]) return null;
  return { owner: parts[0], name: parts[1] };
}
