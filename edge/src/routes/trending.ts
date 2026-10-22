/**
 * 趋势路由（公开）
 * GET /api/trending?limit=20  按 stars_today 降序的 TrendingRepo[]
 */
import { Hono } from 'hono';
import type { Env, TrendingRepo, TrendingRow, Variables } from '../types';
import { all, run } from '../db';

const trending = new Hono<{ Bindings: Env; Variables: Variables }>();

const DEFAULT_LIMIT = 20;
const MAX_LIMIT = 100;

export function toTrendingRepo(row: TrendingRow): TrendingRepo {
  const owner = row.owner ?? row.id.split('/')[0] ?? '';
  return {
    id: row.id,
    owner,
    name: row.name,
    description: row.description ?? null,
    summary: row.readme_summary ?? null,
    language: row.language ?? null,
    stars: row.stars ?? 0,
    starsToday: row.stars_today ?? 0,
    url: row.html_url,
  };
}

interface TrendingSummaryItem {
  repoId?: unknown;
  summary?: unknown;
}

/**
 * POST /api/trending/summaries
 * VPS 摘要任务批量回写热榜中文摘要（M2-04）；仅限内部调用。
 */
trending.post('/summaries', async (c) => {
  const expected = (c.env.INTERNAL_TOKEN ?? '').trim();
  if (expected) {
    const provided = c.req.header('X-Internal-Token') ?? '';
    if (provided !== expected) {
      return c.json({ error: 'unauthorized' }, 401);
    }
  }

  let body: { items?: TrendingSummaryItem[] } | null = null;
  try {
    body = await c.req.json<{ items?: TrendingSummaryItem[] }>();
  } catch {
    return c.json({ error: 'invalid_json' }, 400);
  }
  if (!body || !Array.isArray(body.items)) {
    return c.json({ error: 'invalid_body', message: 'items 必须是数组' }, 400);
  }

  const items = body.items.slice(0, 500);
  let updated = 0;
  let skipped = 0;
  for (const item of items) {
    const repoId = typeof item.repoId === 'string' ? item.repoId.trim() : '';
    const summary = typeof item.summary === 'string' ? item.summary.trim() : '';
    if (!repoId || !summary) {
      skipped += 1;
      continue;
    }
    const result = await run(
      c.env.DB,
      'UPDATE trending_repositories SET readme_summary = ? WHERE id = ?',
      [summary.slice(0, 4000), repoId]
    );
    if ((result.meta.changes ?? 0) > 0) {
      updated += 1;
    } else {
      skipped += 1;
    }
  }

  return c.json({ total: items.length, updated, skipped });
});

trending.get('/', async (c) => {
  const raw = Number.parseInt(c.req.query('limit') ?? '', 10);
  const limit = Number.isFinite(raw) && raw > 0 ? Math.min(raw, MAX_LIMIT) : DEFAULT_LIMIT;

  const rows = await all<TrendingRow>(
    c.env.DB,
    `SELECT * FROM trending_repositories
      ORDER BY stars_today DESC
      LIMIT ?`,
    [limit]
  );

  return c.json(rows.map(toTrendingRepo));
});

export default trending;
