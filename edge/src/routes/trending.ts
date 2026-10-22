/**
 * 趋势路由（列表公开，详情可选登录，收藏需登录）
 * GET    /api/trending                         按 stars_today 降序的 TrendingRepo[]
 * GET    /api/trending/:owner/:name            热榜详情（摘要 + 元信息 + 收藏态）
 * POST   /api/trending/:owner/:name/favorite   一键收藏到我的仓库（幂等）
 * DELETE /api/trending/:owner/:name/favorite   取消收藏
 */
import { Hono } from 'hono';
import type { Env, FavoriteResult, TrendingRepo, TrendingRepoDetail, TrendingRow, Variables } from '../types';
import { all, first, run } from '../db';
import { toTrendingDetail } from '../trending/detail';

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

function repoIdFromParams(owner: string, name: string): string {
  return `${owner}/${name}`;
}

async function findTrending(db: D1Database, id: string): Promise<TrendingRow | null> {
  return first<TrendingRow>(db, 'SELECT * FROM trending_repositories WHERE id = ?', [id]);
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

trending.get('/:owner/:name', async (c) => {
  const id = repoIdFromParams(c.req.param('owner'), c.req.param('name'));
  const row = await findTrending(c.env.DB, id);
  if (!row) return c.json({ error: 'not_found', repoId: id }, 404);

  const user = c.get('user');
  let isFavorited = false;
  if (user) {
    const favorite = await first<{ id: string }>(
      c.env.DB,
      'SELECT id FROM my_repositories WHERE id = ? AND user_id = ?',
      [id, user.id]
    );
    isFavorited = favorite !== null;
  }

  const detail: TrendingRepoDetail = toTrendingDetail(row, isFavorited);
  return c.json(detail);
});

trending.post('/:owner/:name/favorite', async (c) => {
  const user = c.get('user');
  if (!user) return c.json({ error: 'unauthorized' }, 401);

  const id = repoIdFromParams(c.req.param('owner'), c.req.param('name'));
  const row = await findTrending(c.env.DB, id);
  if (!row) return c.json({ error: 'not_found', repoId: id }, 404);

  const now = new Date().toISOString();
  const owner = row.owner ?? id.split('/')[0] ?? '';
  const summary = (row.readme_summary ?? '').trim() || row.description || null;

  const result = await run(
    c.env.DB,
    `INSERT OR IGNORE INTO my_repositories
       (id, platform, name, description, html_url, stars, language, readme_summary,
        category_id, user_id, owner, forks, updated_at, synced_at)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, 0, ?, ?)`,
    [
      id,
      row.platform,
      row.name,
      row.description ?? null,
      row.html_url,
      row.stars ?? 0,
      row.language ?? null,
      summary,
      user.id,
      owner,
      now,
      now,
    ]
  );

  const created = (result.meta?.changes ?? 0) > 0;
  if (!created) {
    // 已存在：同用户视为幂等成功；他人资产不覆盖；历史无主行可认领
    const existing = await first<{ user_id: string | null }>(
      c.env.DB,
      'SELECT user_id FROM my_repositories WHERE id = ?',
      [id]
    );
    if (existing?.user_id && existing.user_id !== user.id) {
      return c.json({ error: 'repo_exists', repoId: id }, 409);
    }
    if (existing && !existing.user_id) {
      await run(c.env.DB, 'UPDATE my_repositories SET user_id = ? WHERE id = ?', [
        user.id,
        id,
      ]);
    }
  }

  const body: FavoriteResult = { favorited: true, created, repoId: id };
  return c.json(body);
});

trending.delete('/:owner/:name/favorite', async (c) => {
  const user = c.get('user');
  if (!user) return c.json({ error: 'unauthorized' }, 401);

  const id = repoIdFromParams(c.req.param('owner'), c.req.param('name'));
  const result = await run(
    c.env.DB,
    'DELETE FROM my_repositories WHERE id = ? AND user_id = ?',
    [id, user.id]
  );
  const body: FavoriteResult = {
    favorited: false,
    removed: (result.meta?.changes ?? 0) > 0,
    repoId: id,
  };
  return c.json(body);
});

export default trending;
