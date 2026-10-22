/**
 * 依赖分析（M6-07）边缘侧纯函数。
 *
 * - `clampAnalysisTop` / `parseRepoIds`：入参归一化，防止超长 URL 与越界 top；
 * - `buildLocalOverview`：VPS 不可达时，用 D1 的仓库语言数据给出本地技术栈概览，
 *   保证页面仍可展示（依赖明细为空，状态标记 unknown）。
 */

export interface RepoLanguageRow {
  id?: string | null;
  name?: string | null;
  language?: string | null;
}

export interface DependencyAnalysisPayload {
  generatedAt: string;
  summary: {
    repos: number;
    analyzed: number;
    noManifest: number;
    failed: number;
    pending: number;
    dependencyRows: number;
    uniqueDependencies: number;
    ecosystems: number;
  };
  techStack: Array<{ language: string; count: number; percent: number }>;
  ecosystems: Array<{ ecosystem: string; repos: number; dependencies: number }>;
  dependencies: Array<Record<string, unknown>>;
  links: Array<Record<string, unknown>>;
  repos: Array<Record<string, unknown>>;
}

export function clampAnalysisTop(
  value: string | number | undefined,
  fallback = 20,
  max = 100
): number {
  if (value === undefined || String(value).trim() === '') return fallback;
  const parsed = typeof value === 'number' ? value : Number(value);
  if (!Number.isFinite(parsed)) return fallback;
  return Math.min(Math.max(Math.trunc(parsed), 1), max);
}

/** 逗号分隔的仓库 id：去空白、去重、限制数量与单 id 长度。 */
export function parseRepoIds(value: string | undefined, max = 100): string[] {
  if (!value) return [];
  const seen = new Set<string>();
  const ids: string[] = [];
  for (const raw of value.split(',')) {
    const id = raw.trim();
    if (!id || id.length > 255 || seen.has(id)) continue;
    seen.add(id);
    ids.push(id);
    if (ids.length >= max) break;
  }
  return ids;
}

/** 本地降级：只按仓库 language 聚合技术栈，不伪造依赖数据。 */
export function buildLocalOverview(rows: RepoLanguageRow[]): DependencyAnalysisPayload {
  const counts = new Map<string, number>();
  for (const row of rows) {
    const language = (row.language ?? '').trim();
    if (language) counts.set(language, (counts.get(language) ?? 0) + 1);
  }
  const total = [...counts.values()].reduce((sum, count) => sum + count, 0);
  const techStack = [...counts.entries()]
    .map(([language, count]) => ({
      language,
      count,
      percent: total ? Math.round((count / total) * 10000) / 10000 : 0,
    }))
    .sort((a, b) => b.count - a.count || a.language.localeCompare(b.language));

  const repos = rows
    .map((row) => ({
      repoId: row.id ?? '',
      name: row.name ?? '',
      language: row.language ?? '',
      status: 'unknown',
      manifests: [],
      dependencyCount: 0,
      error: null,
      topDependencies: [],
    }))
    .sort((a, b) => a.repoId.localeCompare(b.repoId));

  return {
    generatedAt: new Date().toISOString(),
    summary: {
      repos: rows.length,
      analyzed: 0,
      noManifest: 0,
      failed: 0,
      pending: rows.length,
      dependencyRows: 0,
      uniqueDependencies: 0,
      ecosystems: 0,
    },
    techStack,
    ecosystems: [],
    dependencies: [],
    links: [],
    repos,
  };
}
