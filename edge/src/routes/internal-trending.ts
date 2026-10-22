/**
 * 热榜快照内部路由（VPS → D1）
 * - POST /api/internal/trending/snapshots：按 (snapshot_date, repo_id) upsert，单批最多 500 条；
 * - GET  /api/internal/trending/retention：D1 快照总数与最早 / 最新日期；
 * - POST /api/internal/trending/retention/cleanup：按 beforeDate 删除过期快照（M2-08）。
 * 仅内部调用：校验 X-Internal-Token；未配置 INTERNAL_TOKEN 时返回 503（默认关闭）。
 */
import { Hono } from 'hono';
import type { Env, Variables } from '../types';
import { count, first, run } from '../db';
import { requireInternalToken } from '../security/internal-token.ts';

const internalTrending = new Hono<{ Bindings: Env; Variables: Variables }>();

interface SnapshotItem {
  repoId?: unknown;
  platform?: unknown;
  owner?: unknown;
  name?: unknown;
  htmlUrl?: unknown;
  description?: unknown;
  language?: unknown;
  techStack?: unknown;
  stars?: unknown;
  starsToday?: unknown;
  rank?: unknown;
  languageRank?: unknown;
  starDelta?: unknown;
  rankDelta?: unknown;
  appearances?: unknown;
  isNew?: unknown;
  trend?: unknown;
  trendingPages?: unknown;
}

const MAX_BATCH = 500;

function text(value: unknown, fallback = ''): string {
  return typeof value === 'string' ? value.trim() : fallback;
}

function num(value: unknown, fallback = 0): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback;
}

function isValidDate(value: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const parsed = new Date(`${value}T00:00:00Z`);
  return !Number.isNaN(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value;
}

internalTrending.post('/snapshots', async (c) => {
  const denied = await requireInternalToken(c);
  if (denied) return denied;

  let body: { snapshotDate?: unknown; items?: unknown } | null = null;
  try {
    body = await c.req.json<{ snapshotDate?: unknown; items?: unknown }>();
  } catch {
    return c.json({ error: 'invalid_json' }, 400);
  }
  if (!body || !Array.isArray(body.items)) {
    return c.json({ error: 'invalid_body', message: 'items 必须是数组' }, 400);
  }

  const snapshotDate = text(body.snapshotDate);
  if (!isValidDate(snapshotDate)) {
    return c.json({ error: 'invalid_snapshot_date', message: 'snapshotDate 需为 YYYY-MM-DD' }, 400);
  }

  const items = (body.items as SnapshotItem[]).slice(0, MAX_BATCH);
  let upserted = 0;
  let skipped = 0;

  for (const item of items) {
    const repoId = text(item.repoId);
    const name = text(item.name);
    const htmlUrl = text(item.htmlUrl);
    if (!repoId || !name || !htmlUrl) {
      skipped += 1;
      continue;
    }

    const trendingPages = Array.isArray(item.trendingPages)
      ? JSON.stringify(item.trendingPages.map((page) => text(page)).filter(Boolean))
      : '[]';

    await run(
      c.env.DB,
      `INSERT INTO trending_snapshots (
         snapshot_date, repo_id, platform, owner, name, html_url, description,
         language, tech_stack, stars, stars_today, rank, language_rank,
         star_delta, rank_delta, appearances, is_new, trend, trending_pages,
         created_at, updated_at
       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                 CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
       ON CONFLICT(snapshot_date, repo_id) DO UPDATE SET
         platform = excluded.platform,
         owner = excluded.owner,
         name = excluded.name,
         html_url = excluded.html_url,
         description = excluded.description,
         language = excluded.language,
         tech_stack = excluded.tech_stack,
         stars = excluded.stars,
         stars_today = excluded.stars_today,
         rank = excluded.rank,
         language_rank = excluded.language_rank,
         star_delta = excluded.star_delta,
         rank_delta = excluded.rank_delta,
         appearances = excluded.appearances,
         is_new = excluded.is_new,
         trend = excluded.trend,
         trending_pages = excluded.trending_pages,
         updated_at = CURRENT_TIMESTAMP`,
      [
        snapshotDate,
        repoId,
        text(item.platform, 'github'),
        text(item.owner) || null,
        name,
        htmlUrl,
        text(item.description),
        text(item.language) || null,
        text(item.techStack) || null,
        num(item.stars),
        num(item.starsToday),
        num(item.rank),
        num(item.languageRank),
        num(item.starDelta),
        num(item.rankDelta),
        num(item.appearances, 1),
        item.isNew ? 1 : 0,
        text(item.trend, 'steady'),
        trendingPages,
      ]
    );
    upserted += 1;
  }

  return c.json({ total: items.length, upserted, skipped });
});

internalTrending.get('/retention', async (c) => {
  const denied = await requireInternalToken(c);
  if (denied) return denied;

  const total = await count(c.env.DB, 'SELECT COUNT(*) AS n FROM trending_snapshots');
  const bounds = await first<{ oldest: string | null; newest: string | null }>(
    c.env.DB,
    'SELECT MIN(snapshot_date) AS oldest, MAX(snapshot_date) AS newest FROM trending_snapshots'
  );
  return c.json({
    total,
    oldest: bounds?.oldest ?? null,
    newest: bounds?.newest ?? null,
  });
});

internalTrending.post('/retention/cleanup', async (c) => {
  const denied = await requireInternalToken(c);
  if (denied) return denied;

  let body: { beforeDate?: unknown; dryRun?: unknown } | null = null;
  try {
    body = await c.req.json<{ beforeDate?: unknown; dryRun?: unknown }>();
  } catch {
    return c.json({ error: 'invalid_json' }, 400);
  }
  const beforeDate = text(body?.beforeDate);
  if (!isValidDate(beforeDate)) {
    return c.json({ error: 'invalid_before_date', message: 'beforeDate 需为 YYYY-MM-DD' }, 400);
  }

  const dryRun = body?.dryRun === true;
  if (dryRun) {
    const total = await count(
      c.env.DB,
      'SELECT COUNT(*) AS n FROM trending_snapshots WHERE snapshot_date < ?',
      [beforeDate]
    );
    return c.json({ beforeDate, dryRun: true, deleted: total });
  }

  const result = await run(
    c.env.DB,
    'DELETE FROM trending_snapshots WHERE snapshot_date < ?',
    [beforeDate]
  );
  return c.json({ beforeDate, dryRun: false, deleted: result.meta.changes ?? 0 });
});

export default internalTrending;
