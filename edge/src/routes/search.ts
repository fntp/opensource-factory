/**
 * 搜索路由（M3-04 语义 / M6-01 全文）
 * POST /api/search/semantic
 * POST /api/search/fulltext
 *
 * 语义链路：
 *   1. VPS `/api/search/embed` 生成查询向量 → Cloudflare Vectorize 近邻检索（mode=vectorize）
 *   2. Vectorize 不可用 / 无命中 → VPS `/api/search/query` 本地向量余弦检索（mode=local）
 *   3. VPS 不可达 → D1 关键词 LIKE 检索（mode=keyword，保证页面可用）
 *
 * 全文链路：
 *   1. VPS `/api/search/fulltext` 查询 SQLite FTS5（mode=fts，短词回退 mode=like）
 *   2. VPS 不可用 / 无命中 → D1 关键词 LIKE 检索（mode=keyword）
 *
 * 权限：`my` 来源的结果只保留当前登录用户的行；`trending` 为全局数据。
 */
import { Hono } from 'hono';
import type {
  Env,
  RepoRow,
  SearchResponse,
  SearchResultItem,
  SearchUnderstanding,
  TrendingRow,
  Variables,
} from '../types';
import { all } from '../db';

const search = new Hono<{ Bindings: Env; Variables: Variables }>();

const DEFAULT_TOP_K = 10;
const MAX_TOP_K = 30;
const MAX_QUERY_LENGTH = 200;
const HYDRATE_CHUNK = 50;
const MAX_KEYWORD_TERMS = 8;

type Scope = 'my' | 'trending' | 'all';

interface VpsEmbedResponse {
  vector?: number[];
  dim?: number;
  model?: string;
  backend?: string;
  understanding?: SearchUnderstanding;
}

interface VpsHit {
  source?: string;
  repoId?: string;
  score?: number;
}

interface VpsQueryResponse {
  items?: VpsHit[];
  model?: string;
  backend?: string;
  dim?: number;
  understanding?: SearchUnderstanding;
}

interface VpsFulltextItem {
  id?: string;
  source?: string;
  fullName?: string;
  name?: string;
  description?: string;
  language?: string;
  stars?: number;
  starsToday?: number;
  url?: string;
  score?: number;
  reason?: string;
  snippet?: string;
  matchedTerms?: string[];
}

interface VpsFulltextResponse {
  mode?: string;
  items?: VpsFulltextItem[];
  terms?: string[];
}

interface Hit {
  source: string;
  repoId: string;
  score: number;
}

function normalizeScope(value: unknown): Scope | null {
  if (value === undefined || value === null || value === '') return 'all';
  return value === 'my' || value === 'trending' || value === 'all' ? value : null;
}

function clampTopK(value: unknown): number {
  const parsed = typeof value === 'number' ? value : Number.parseInt(String(value ?? ''), 10);
  if (!Number.isFinite(parsed)) return DEFAULT_TOP_K;
  return Math.min(MAX_TOP_K, Math.max(1, Math.trunc(parsed)));
}

async function postVps<T>(env: Env, path: string, body: unknown): Promise<T | null> {
  const base = env.VPS_NODE_URL?.trim();
  if (!base) return null;
  try {
    const res = await fetch(`${base.replace(/\/+$/, '')}${path}`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Internal-Token': env.INTERNAL_TOKEN ?? '',
      },
      body: JSON.stringify(body),
    });
    if (!res.ok) return null;
    return (await res.json()) as T;
  } catch (err) {
    console.error(`vps ${path} failed:`, err);
    return null;
  }
}

function metaString(metadata: Record<string, unknown> | undefined, key: string): string {
  const value = metadata?.[key];
  return typeof value === 'string' ? value : '';
}

function chunk<T>(items: T[], size: number): T[][] {
  const groups: T[][] = [];
  for (let index = 0; index < items.length; index += size) {
    groups.push(items.slice(index, index + size));
  }
  return groups;
}

function placeholders(count: number): string {
  return Array.from({ length: count }, () => '?').join(', ');
}

function reasonFor(score: number, language: string, description: string, keyword = false): string {
  const percent = Math.round(Math.max(0, Math.min(1, score)) * 100);
  const prefix = keyword ? `关键词匹配度 ${percent}%。` : `与查询语义相似度 ${percent}%。`;
  const parts = [prefix];
  if (language) parts.push(`主要使用 ${language} 开发；`);
  if (description) parts.push(`项目简介：${description.slice(0, 80)}。`);
  return parts.join('');
}

function toItem(
  row: RepoRow | TrendingRow,
  source: 'my' | 'trending',
  score: number,
  keyword = false
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
    reason: reasonFor(score, language, description, keyword),
  };
}

/** 按 id 批量取行；`my` 额外按 user_id 过滤，避免跨用户泄漏。 */
async function hydrate(
  env: Env,
  userId: string,
  hits: Hit[],
  limit: number
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
    items.push(toItem(entry.row, entry.source, hit.score));
  }
  return items;
}

/** 全文检索命中：仍以 D1 行为准做用户隔离 / 存在性校验，并保留 README 片段。 */
async function hydrateFulltext(
  env: Env,
  userId: string,
  hits: VpsFulltextItem[],
  limit: number
): Promise<SearchResultItem[]> {
  const wanted = hits
    .filter(
      (hit): hit is VpsFulltextItem & { source: 'my' | 'trending'; id: string } =>
        (hit.source === 'my' || hit.source === 'trending') && typeof hit.id === 'string'
    )
    .slice(0, Math.max(limit * 4, limit));
  const myIds = [...new Set(wanted.filter((hit) => hit.source === 'my').map((hit) => hit.id))];
  const trendingIds = [
    ...new Set(wanted.filter((hit) => hit.source === 'trending').map((hit) => hit.id)),
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
    const entry = rows.get(`${hit.source}:${hit.id}`);
    if (!entry) continue;
    const base = toItem(entry.row, entry.source, hit.score ?? 0);
    items.push({
      ...base,
      score: typeof hit.score === 'number' ? Math.round(hit.score * 10000) / 10000 : base.score,
      reason: hit.reason || base.reason,
      snippet: hit.snippet ?? '',
      matchedTerms: hit.matchedTerms ?? [],
    });
  }
  return items;
}

/** 关键词词表：原查询 + 查询理解扩展词，去重后限 8 个。 */
function keywordTerms(query: string, understanding?: SearchUnderstanding): string[] {
  const values = [query, ...(understanding?.keywordTerms ?? [])]
    .map((item) => item.trim())
    .filter(Boolean);
  return [...new Set(values)].slice(0, MAX_KEYWORD_TERMS);
}

/** 多词 OR LIKE：每个词在给定列上做一次 LIKE，词之间 OR。 */
function likeFilter(columns: string[], terms: string[]): { sql: string; params: string[] } {
  const groups = terms.map(
    () => `(${columns.map((column) => `${column} LIKE ?`).join(' OR ')})`
  );
  const params = terms.flatMap((term) => columns.map(() => `%${term}%`));
  return { sql: groups.join(' OR '), params };
}

/** D1 关键词兜底：当前用户的收藏 + 全局热榜；使用查询理解的扩展词提升召回。 */
async function keywordSearch(
  env: Env,
  userId: string,
  query: string,
  scope: Scope,
  limit: number,
  understanding?: SearchUnderstanding
): Promise<SearchResultItem[]> {
  const terms = keywordTerms(query, understanding);
  if (terms.length === 0) return [];
  const items: SearchResultItem[] = [];

  if (scope === 'my' || scope === 'all') {
    const filter = likeFilter(['name', 'id', 'description', 'readme_summary'], terms);
    const rows = await all<RepoRow>(
      env.DB,
      `SELECT * FROM my_repositories
        WHERE user_id = ? AND (${filter.sql})
        ORDER BY stars DESC LIMIT ?`,
      [userId, ...filter.params, limit]
    );
    for (const row of rows) {
      const hit = row.name.toLowerCase().includes(query.toLowerCase()) ? 0.6 : 0.4;
      items.push(toItem(row, 'my', hit, true));
    }
  }
  if (scope === 'trending' || scope === 'all') {
    const filter = likeFilter(['name', 'id', 'description', 'tech_stack'], terms);
    const rows = await all<TrendingRow>(
      env.DB,
      `SELECT * FROM trending_repositories
        WHERE ${filter.sql}
        ORDER BY stars_today DESC LIMIT ?`,
      [...filter.params, limit]
    );
    for (const row of rows) {
      const hit = row.name.toLowerCase().includes(query.toLowerCase()) ? 0.6 : 0.4;
      items.push(toItem(row, 'trending', hit, true));
    }
  }
  return items.slice(0, limit);
}

search.post('/semantic', async (c) => {
  const user = c.get('user');
  if (!user) return c.json({ error: 'unauthorized' }, 401);

  const body = (await c.req.json().catch(() => null)) as Record<string, unknown> | null;
  if (!body || typeof body.query !== 'string') {
    return c.json({ error: 'invalid_body', message: 'query 必填' }, 400);
  }
  const query = body.query.trim().replace(/\s+/g, ' ');
  if (!query || query.length > MAX_QUERY_LENGTH) {
    return c.json({ error: 'invalid_query', message: `query 长度需为 1~${MAX_QUERY_LENGTH}` }, 400);
  }
  const scope = normalizeScope(body.scope);
  if (!scope) {
    return c.json({ error: 'invalid_scope', message: 'scope 仅支持 my / trending / all' }, 400);
  }
  const topK = clampTopK(body.topK);
  const started = Date.now();
  const base = { query, scope, count: 0, tookMs: 0 } as const;
  let understanding: SearchUnderstanding | undefined;

  // 1) Vectorize 优先
  if (c.env.VECTORIZE) {
    const embedded = await postVps<VpsEmbedResponse>(c.env, '/api/search/embed', { query });
    understanding = embedded?.understanding;
    if (embedded?.vector?.length) {
      try {
        const result = await c.env.VECTORIZE.query(embedded.vector, {
          topK: Math.min(100, topK * 4),
          returnMetadata: 'all',
        });
        const hits: Hit[] = [];
        for (const match of result.matches ?? []) {
          const metadata = match.metadata as Record<string, unknown> | undefined;
          const source = metaString(metadata, 'source');
          const repoId = metaString(metadata, 'repo_id');
          if ((source === 'my' || source === 'trending') && repoId) {
            if (scope !== 'all' && scope !== source) continue;
            hits.push({ source, repoId, score: match.score ?? 0 });
          }
        }
        const items = await hydrate(c.env, user.id, hits, topK);
        if (items.length > 0) {
          return c.json({
            ...base,
            mode: 'vectorize',
            count: items.length,
            tookMs: Date.now() - started,
            backend: embedded.backend ?? '',
            model: embedded.model ?? '',
            dim: embedded.dim ?? embedded.vector.length,
            items,
            ...(understanding ? { understanding } : {}),
          } satisfies SearchResponse);
        }
      } catch (err) {
        console.error('vectorize query failed:', err);
      }
    }
  }

  // 2) 本地向量降级
  const local = await postVps<VpsQueryResponse>(c.env, '/api/search/query', {
    query,
    topK: Math.min(50, topK * 3),
    scope,
  });
  understanding = local?.understanding ?? understanding;
  if (local?.items?.length) {
    const hits: Hit[] = local.items
      .filter(
        (item): item is VpsHit & { source: string; repoId: string; score: number } =>
          (item.source === 'my' || item.source === 'trending') &&
          typeof item.repoId === 'string' &&
          typeof item.score === 'number'
      )
      .map((item) => ({ source: item.source, repoId: item.repoId, score: item.score }));
    const items = await hydrate(c.env, user.id, hits, topK);
    if (items.length > 0) {
      return c.json({
        ...base,
        mode: 'local',
        count: items.length,
        tookMs: Date.now() - started,
        backend: local.backend ?? '',
        model: local.model ?? '',
        dim: local.dim ?? 0,
        items,
        ...(understanding ? { understanding } : {}),
      } satisfies SearchResponse);
    }
  }

  // 3) D1 关键词兜底
  const items = await keywordSearch(c.env, user.id, query, scope, topK, understanding);
  return c.json({
    ...base,
    mode: 'keyword',
    count: items.length,
    tookMs: Date.now() - started,
    backend: '',
    model: '',
    dim: 0,
    items,
    ...(understanding ? { understanding } : {}),
  } satisfies SearchResponse);
});

/** README 全文检索（M6-01）：VPS FTS5 优先，不可用 / 无命中回退 D1 关键词。 */
search.post('/fulltext', async (c) => {
  const user = c.get('user');
  if (!user) return c.json({ error: 'unauthorized' }, 401);

  const body = (await c.req.json().catch(() => null)) as Record<string, unknown> | null;
  if (!body || typeof body.query !== 'string') {
    return c.json({ error: 'invalid_body', message: 'query 必填' }, 400);
  }
  const query = body.query.trim().replace(/\s+/g, ' ');
  if (!query || query.length > MAX_QUERY_LENGTH) {
    return c.json({ error: 'invalid_query', message: `query 长度需为 1~${MAX_QUERY_LENGTH}` }, 400);
  }
  const scope = normalizeScope(body.scope);
  if (!scope) {
    return c.json({ error: 'invalid_scope', message: 'scope 仅支持 my / trending / all' }, 400);
  }
  const topK = clampTopK(body.topK);
  const offsetValue = Number.parseInt(String(body.offset ?? '0'), 10);
  const offset = Number.isFinite(offsetValue) ? Math.min(10000, Math.max(0, offsetValue)) : 0;
  const started = Date.now();

  const remote = await postVps<VpsFulltextResponse>(c.env, '/api/search/fulltext', {
    query,
    scope,
    topK,
    offset,
  });
  if (remote?.items?.length) {
    const items = await hydrateFulltext(c.env, user.id, remote.items, topK);
    if (items.length > 0) {
      return c.json({
        query,
        scope,
        mode: remote.mode === 'fts' ? 'fts' : 'like',
        count: items.length,
        tookMs: Date.now() - started,
        backend: 'sqlite-fts5',
        model: '',
        dim: 0,
        terms: remote.terms ?? [],
        items,
      } satisfies SearchResponse);
    }
  }

  // VPS 不可用 / 无命中：回退现有 D1 关键词检索
  const items = await keywordSearch(c.env, user.id, query, scope, topK);
  return c.json({
    query,
    scope,
    mode: 'keyword',
    count: items.length,
    tookMs: Date.now() - started,
    backend: '',
    model: '',
    dim: 0,
    items,
  } satisfies SearchResponse);
});

export default search;
