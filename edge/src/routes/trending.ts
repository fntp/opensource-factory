/**
 * 趋势路由（公开）
 * GET /api/trending?limit=20  按 stars_today 降序的 TrendingRepo[]
 */
import { Hono } from 'hono';
import type { Env, TrendingRepo, TrendingRow, Variables } from '../types';
import { all } from '../db';

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
    language: row.language ?? null,
    stars: row.stars ?? 0,
    starsToday: row.stars_today ?? 0,
    url: row.html_url,
  };
}

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
