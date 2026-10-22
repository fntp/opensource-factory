/**
 * 趋势路由（公开）
 * GET /api/trending?date=&language=&limit=20
 *   - 有按日快照时优先读 trending_snapshots（默认最近一天，可按日期 / 语言筛选）；
 *   - 无快照时回退 trending_repositories 最新状态，保持旧前端兼容。
 * GET /api/trending/dates     可用快照日期
 * GET /api/trending/history?repoId=&days=  单仓库历史
 */
import { Hono } from 'hono';
import type { Env, TrendingRepo, TrendingRow, TrendingSnapshotRow, Variables } from '../types';
import { all, first } from '../db';

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

/** 快照行 → 前端 TrendingRepo（附带趋势字段） */
export function toTrendingRepoFromSnapshot(row: TrendingSnapshotRow): TrendingRepo {
  const owner = row.owner ?? row.repo_id.split('/')[0] ?? '';
  return {
    id: row.repo_id,
    owner,
    name: row.name,
    description: row.description ?? null,
    language: row.language ?? null,
    stars: row.stars ?? 0,
    starsToday: row.stars_today ?? 0,
    url: row.html_url,
    snapshotDate: row.snapshot_date,
    rank: row.rank ?? 0,
    languageRank: row.language_rank ?? 0,
    starDelta: row.star_delta ?? 0,
    rankDelta: row.rank_delta ?? 0,
    appearances: row.appearances ?? 1,
    isNew: Boolean(row.is_new),
    trend: row.trend ?? 'steady',
  };
}

function parseLimit(raw: string | undefined): number {
  const parsed = Number.parseInt(raw ?? '', 10);
  return Number.isFinite(parsed) && parsed > 0 ? Math.min(parsed, MAX_LIMIT) : DEFAULT_LIMIT;
}

trending.get('/dates', async (c) => {
  const limit = parseLimit(c.req.query('limit'));
  const rows = await all<{ snapshot_date: string; n: number }>(
    c.env.DB,
    `SELECT snapshot_date, COUNT(*) AS n
       FROM trending_snapshots
      GROUP BY snapshot_date
      ORDER BY snapshot_date DESC
      LIMIT ?`,
    [limit]
  );
  return c.json(rows.map((row) => ({ date: row.snapshot_date, count: row.n })));
});

trending.get('/history', async (c) => {
  const repoId = (c.req.query('repoId') ?? '').trim();
  if (!repoId) return c.json({ error: 'repoId_required' }, 400);
  const rawDays = Number.parseInt(c.req.query('days') ?? '', 10);
  const days = Number.isFinite(rawDays) && rawDays > 0 ? Math.min(rawDays, 365) : 30;
  const cutoff = new Date(Date.now() - days * 86400000).toISOString().slice(0, 10);

  const rows = await all<TrendingSnapshotRow>(
    c.env.DB,
    `SELECT * FROM trending_snapshots
      WHERE repo_id = ? AND snapshot_date >= ?
      ORDER BY snapshot_date ASC`,
    [repoId, cutoff]
  );
  return c.json(rows.map(toTrendingRepoFromSnapshot));
});

trending.get('/', async (c) => {
  const limit = parseLimit(c.req.query('limit'));
  const dateParam = (c.req.query('date') ?? '').trim();
  const language = (c.req.query('language') ?? '').trim();

  // 优先按日快照；未指定日期时取最近一天
  let snapshotDate = dateParam;
  if (!snapshotDate) {
    const latest = await first<{ d: string | null }>(
      c.env.DB,
      'SELECT MAX(snapshot_date) AS d FROM trending_snapshots'
    );
    snapshotDate = latest?.d ?? '';
  }

  if (snapshotDate) {
    const where = ['snapshot_date = ?'];
    const params: Array<string | number> = [snapshotDate];
    if (language) {
      where.push('LOWER(language) = ?');
      params.push(language.toLowerCase());
    }
    params.push(limit);
    const rows = await all<TrendingSnapshotRow>(
      c.env.DB,
      `SELECT * FROM trending_snapshots
        WHERE ${where.join(' AND ')}
        ORDER BY rank ASC
        LIMIT ?`,
      params
    );
    if (rows.length > 0) {
      return c.json(rows.map(toTrendingRepoFromSnapshot));
    }
    // 明确指定了日期或语言但无匹配：返回空，避免回退成「最新状态」造成误导
    if (dateParam || language) {
      return c.json([]);
    }
  }

  // 兼容：尚无任何快照时读最新状态表
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
