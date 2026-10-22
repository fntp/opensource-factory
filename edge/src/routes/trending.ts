/**
 * 趋势路由（列表公开，详情可选登录，收藏需登录）
 * GET    /api/trending?date=&language=&limit=20
 *   - 有按日快照时优先读 trending_snapshots（默认最近一天，可按日期 / 语言筛选）；
 *   - 无快照时回退 trending_repositories 最新状态，保持旧前端兼容。
 * GET    /api/trending/dates     可用快照日期
 * GET    /api/trending/languages?date=  指定日期的语言分布
 * GET    /api/trending/history?repoId=&days=  单仓库历史
 * GET    /api/trending/:owner/:name            热榜详情（摘要 + 元信息 + 收藏态）
 * POST   /api/trending/:owner/:name/favorite   一键收藏到我的仓库（幂等）
 * DELETE /api/trending/:owner/:name/favorite   取消收藏
 * POST   /api/trending/summaries  内部：VPS 摘要任务批量回写热榜中文摘要
 */
import { Hono } from 'hono';
import type {
  Env,
  FavoriteResult,
  TrendingRepo,
  TrendingRepoDetail,
  TrendingRow,
  TrendingSnapshotRow,
  Variables,
} from '../types';
import { all, first, run } from '../db';
import { checkOptionalInternalToken } from '../security/internal-token.ts';
import { parseTrendingQuery } from '../trending/query';
import { toTrendingDetail } from '../trending/detail';

const trending = new Hono<{ Bindings: Env; Variables: Variables }>();

const DEFAULT_LIMIT = 20;
const MAX_LIMIT = 100;

type SnapshotTrend = TrendingRepo['trend'];

function mapTrend(row: TrendingSnapshotRow): SnapshotTrend {
  if (row.is_new) return 'new';
  // 页面按排名变化的符号标注（M2-05 的 trend 字段采用 ±3 阈值，仅作后端参考）
  if ((row.rank_delta ?? 0) > 0) return 'up';
  if ((row.rank_delta ?? 0) < 0) return 'down';
  return 'same';
}

/** 旧表行 → 前端 TrendingRepo（无趋势数据，按持平处理）。 */
export function toTrendingRepo(row: TrendingRow, rank = 0): TrendingRepo {
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
    snapshotDate: row.crawled_at,
    rank,
    rankChange: 0,
    trend: 'same',
  };
}

/** 快照行 → 前端 TrendingRepo（附带排名与趋势字段）。 */
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
    rankChange: row.is_new ? null : (row.rank_delta ?? 0),
    trend: mapTrend(row),
    languageRank: row.language_rank ?? 0,
    starDelta: row.star_delta ?? 0,
    rankDelta: row.rank_delta ?? 0,
    appearances: row.appearances ?? 1,
    isNew: Boolean(row.is_new),
  };
}

interface TrendingSummaryItem {
  repoId?: unknown;
  summary?: unknown;
}

function repoIdFromParams(owner: string, name: string): string {
  return `${owner}/${name}`;
}

async function findTrending(db: D1Database, id: string): Promise<TrendingRow | null> {
  return first<TrendingRow>(db, 'SELECT * FROM trending_repositories WHERE id = ?', [id]);
}

/**
 * POST /api/trending/summaries
 * VPS 摘要任务批量回写热榜中文摘要（M2-04）；仅限内部调用。
 */
trending.post('/summaries', async (c) => {
  const denied = await checkOptionalInternalToken(c);
  if (denied) return denied;

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

function parseLimit(raw: string | undefined): number {
  const parsed = Number.parseInt(raw ?? '', 10);
  return Number.isFinite(parsed) && parsed > 0
    ? Math.min(parsed, MAX_LIMIT)
    : DEFAULT_LIMIT;
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

trending.get('/languages', async (c) => {
  const rawDate = (c.req.query('date') ?? '').trim();
  if (rawDate) {
    const parsed = parseTrendingQuery(new URLSearchParams({ date: rawDate }));
    if (!parsed.ok) {
      return c.json(
        { error: 'invalid_query', field: parsed.field, message: parsed.message },
        400
      );
    }
  }

  let date = rawDate;
  if (!date) {
    const latest = await first<{ d: string | null }>(
      c.env.DB,
      'SELECT MAX(snapshot_date) AS d FROM trending_snapshots'
    );
    date = latest?.d ?? '';
  }

  let rows: Array<{ language: string; n: number }> = [];
  if (date) {
    rows = await all<{ language: string; n: number }>(
      c.env.DB,
      `SELECT language, COUNT(*) AS n
         FROM trending_snapshots
        WHERE snapshot_date = ?
          AND language IS NOT NULL AND language <> ''
        GROUP BY language
        ORDER BY n DESC, language ASC`,
      [date]
    );
  }
  if (rows.length === 0) {
    rows = await all<{ language: string; n: number }>(
      c.env.DB,
      `SELECT language, COUNT(*) AS n
         FROM trending_repositories
        WHERE language IS NOT NULL AND language <> ''
        GROUP BY language
        ORDER BY n DESC, language ASC`
    );
  }

  return c.json({
    date: date || null,
    languages: rows.map((row) => ({ language: row.language, count: row.n })),
  });
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
  const parsed = parseTrendingQuery(new URLSearchParams(c.req.query()));
  if (!parsed.ok) {
    return c.json(
      { error: 'invalid_query', field: parsed.field, message: parsed.message },
      400
    );
  }
  const { date: dateParam, language, limit } = parsed.query;

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
        ORDER BY rank ASC, repo_id ASC
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
  const where: string[] = [];
  const params: Array<string | number> = [];
  if (language) {
    where.push('LOWER(language) = ?');
    params.push(language.toLowerCase());
  }
  params.push(limit);
  const rows = await all<TrendingRow>(
    c.env.DB,
    `SELECT * FROM trending_repositories
      ${where.length > 0 ? `WHERE ${where.join(' AND ')}` : ''}
      ORDER BY stars_today DESC, id ASC
      LIMIT ?`,
    params
  );
  return c.json(rows.map((row, index) => toTrendingRepo(row, index + 1)));
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
