/**
 * Star 趋势与洞察路由（M7-05）。
 *
 * GET /api/star-trends?days=30&scope=trending|my&language=
 * - 登录态；复用 M2-05 `trending_snapshots`，不新增表；
 * - `scope=my` 先取当前用户收藏仓库白名单，再按 repo_id 分片查询快照；
 * - 聚合逻辑全部在 `src/insights/star-trends.ts` 纯函数中完成。
 */
import { Hono } from 'hono';
import type { Env, Variables } from '../types';
import { all } from '../db';
import {
  buildStarTrends,
  type PortfolioRepoRow,
  type StarSnapshotRow,
  type StarTrendScope,
} from '../insights/star-trends';

const starTrends = new Hono<{ Bindings: Env; Variables: Variables }>();

const MAX_ROWS = 20000;
const MY_CHUNK_SIZE = 50;

const SNAPSHOT_COLUMNS = `snapshot_date, repo_id, owner, name, html_url, description,
  language, stars, stars_today, rank, language_rank, star_delta, rank_delta,
  appearances, is_new, trend`;

function parseDays(raw: string | undefined): number {
  const parsed = Number.parseInt(raw ?? '', 10);
  if (!Number.isFinite(parsed) || parsed <= 0) return 30;
  return Math.min(365, parsed);
}

function cutoffDate(days: number, now = new Date()): string {
  const start = new Date(now.getTime() - (days - 1) * 86400000);
  return start.toISOString().slice(0, 10);
}

function chunk<T>(items: readonly T[], size: number): T[][] {
  const chunks: T[][] = [];
  for (let index = 0; index < items.length; index += size) {
    chunks.push(items.slice(index, index + size));
  }
  return chunks;
}

async function loadPortfolio(
  db: D1Database,
  userId: string
): Promise<PortfolioRepoRow[]> {
  return all<PortfolioRepoRow>(
    db,
    `SELECT id, name, stars, language
       FROM my_repositories
      WHERE user_id = ?
      ORDER BY stars DESC, id ASC`,
    [userId]
  );
}

async function loadMySnapshots(
  db: D1Database,
  repoIds: readonly string[],
  cutoff: string,
  language: string | null
): Promise<StarSnapshotRow[]> {
  const rows: StarSnapshotRow[] = [];
  for (const ids of chunk(repoIds, MY_CHUNK_SIZE)) {
    if (ids.length === 0) continue;
    const placeholders = ids.map(() => '?').join(', ');
    const params: Array<string | number | null> = [cutoff, ...ids];
    let sql = `SELECT ${SNAPSHOT_COLUMNS}
                 FROM trending_snapshots
                WHERE snapshot_date >= ?
                  AND repo_id IN (${placeholders})`;
    if (language) {
      sql += ' AND LOWER(language) = ?';
      params.push(language.toLowerCase());
    }
    sql += ' ORDER BY snapshot_date ASC, repo_id ASC LIMIT 5000';
    rows.push(...(await all<StarSnapshotRow>(db, sql, params)));
  }
  return rows;
}

starTrends.get('/', async (c) => {
  const user = c.get('user');
  if (!user) return c.json({ error: 'unauthorized' }, 401);

  const days = parseDays(c.req.query('days'));
  const scope: StarTrendScope =
    c.req.query('scope') === 'my' ? 'my' : 'trending';
  const language = (c.req.query('language') ?? '').trim().slice(0, 64) || null;
  const cutoff = cutoffDate(days);

  let rows: StarSnapshotRow[] = [];
  let portfolio: PortfolioRepoRow[] = [];

  if (scope === 'my') {
    portfolio = await loadPortfolio(c.env.DB, user.id);
    rows = await loadMySnapshots(
      c.env.DB,
      portfolio.map((repo) => repo.id),
      cutoff,
      language
    );
  } else {
    const params: Array<string | number | null> = [cutoff];
    let sql = `SELECT ${SNAPSHOT_COLUMNS}
                 FROM trending_snapshots
                WHERE snapshot_date >= ?`;
    if (language) {
      sql += ' AND LOWER(language) = ?';
      params.push(language.toLowerCase());
    }
    sql += ' ORDER BY snapshot_date ASC, repo_id ASC LIMIT ?';
    params.push(MAX_ROWS);
    rows = await all<StarSnapshotRow>(c.env.DB, sql, params);
  }

  return c.json(
    buildStarTrends(rows, {
      days,
      scope,
      language,
      portfolio,
      now: new Date(),
    })
  );
});

export default starTrends;
