/**
 * 推荐路由（当前用户）
 *
 * GET  /api/recommendations?status=new|saved|dismissed|all&limit=50
 * GET  /api/recommendations/stats
 * POST /api/recommendations/:id/save      收藏（写入 my_repositories + 反馈）
 * POST /api/recommendations/:id/dismiss   忽略（可带原因 + 反馈）
 * POST /api/recommendations/:id/click     记录查看点击（反馈回流）
 */
import { Hono } from 'hono';
import type {
  Env,
  RecommendationFeedbackAction,
  RecommendationRow,
  RecommendationStats,
  Variables,
} from '../types';
import { all, first, run } from '../db';
import {
  buildFeedbackRow,
  deriveRepoId,
  normalizeDismissReason,
  normalizeStatusFilter,
  toRecommendation,
} from '../recommend/feedback';

const recommend = new Hono<{ Bindings: Env; Variables: Variables }>();

const DEFAULT_LIMIT = 50;
const MAX_LIMIT = 100;

type RecommendationOwnerRow = Pick<
  RecommendationRow,
  'id' | 'user_id' | 'repo_id' | 'owner' | 'name' | 'description' | 'language' | 'stars' | 'url'
>;

async function readBody(c: { req: { json: () => Promise<unknown> } }): Promise<Record<string, unknown> | null> {
  try {
    const body = await c.req.json();
    return body && typeof body === 'object' && !Array.isArray(body)
      ? (body as Record<string, unknown>)
      : null;
  } catch {
    return null;
  }
}

/** 读取当前用户可见的推荐（本人 + 全局），不存在或不可见时返回 null。 */
async function findRecommendation(
  db: D1Database,
  userId: string,
  id: string
): Promise<RecommendationOwnerRow | null> {
  return await first<RecommendationOwnerRow>(
    db,
    `SELECT id, user_id, repo_id, owner, name, description, language, stars, url
       FROM recommendations
      WHERE id = ? AND (user_id = ? OR user_id IS NULL)`,
    [id, userId]
  );
}

/** 写入一条反馈（唯一键去重，重复点击幂等）。 */
async function recordFeedback(
  db: D1Database,
  userId: string,
  recommendationId: string,
  repoId: string,
  action: RecommendationFeedbackAction,
  reason: string | null
): Promise<void> {
  const row = buildFeedbackRow({
    id: crypto.randomUUID(),
    userId,
    recommendationId,
    repoId,
    action,
    reason,
  });
  await run(
    db,
    `INSERT OR IGNORE INTO recommendation_feedback
       (id, user_id, recommendation_id, repo_id, action, reason, created_at)
     VALUES (?, ?, ?, ?, ?, ?, ?)`,
    [row.id, row.user_id, row.recommendation_id, row.repo_id, row.action, row.reason, row.created_at]
  );
}

recommend.get('/', async (c) => {
  const user = c.get('user');
  if (!user) return c.json({ error: 'unauthorized' }, 401);

  const raw = Number.parseInt(c.req.query('limit') ?? '', 10);
  const limit = Number.isFinite(raw) && raw > 0 ? Math.min(raw, MAX_LIMIT) : DEFAULT_LIMIT;
  const status = normalizeStatusFilter(c.req.query('status'));

  const where = ['(user_id = ? OR user_id IS NULL)'];
  const params: Array<string | number | null> = [user.id];
  if (status !== 'all') {
    where.push('status = ?');
    params.push(status);
  }
  params.push(limit);

  const rows = await all<RecommendationRow>(
    c.env.DB,
    `SELECT * FROM recommendations
      WHERE ${where.join(' AND ')}
      ORDER BY COALESCE(NULLIF(rerank_score, 0), score) DESC, score DESC, created_at DESC
      LIMIT ?`,
    params
  );

  return c.json(rows.map(toRecommendation));
});

recommend.get('/stats', async (c) => {
  const user = c.get('user');
  if (!user) return c.json({ error: 'unauthorized' }, 401);

  const rows = await all<{ status: string | null; n: number }>(
    c.env.DB,
    `SELECT status, COUNT(*) AS n
       FROM recommendations
      WHERE user_id = ? OR user_id IS NULL
      GROUP BY status`,
    [user.id]
  );
  const clicked = await first<{ n: number }>(
    c.env.DB,
    `SELECT COUNT(*) AS n
       FROM recommendation_feedback
      WHERE user_id = ? AND action = 'clicked'`,
    [user.id]
  );

  const stats: RecommendationStats = {
    new: 0,
    saved: 0,
    dismissed: 0,
    pushed: 0,
    clicked: clicked?.n ?? 0,
  };
  for (const row of rows) {
    const key = row.status ?? 'new';
    if (key === 'new' || key === 'saved' || key === 'dismissed' || key === 'pushed') {
      stats[key] = row.n;
    }
  }
  return c.json(stats);
});

recommend.post('/:id/save', async (c) => {
  const user = c.get('user');
  if (!user) return c.json({ error: 'unauthorized' }, 401);

  const id = c.req.param('id');
  const row = await findRecommendation(c.env.DB, user.id, id);
  if (!row) return c.json({ error: 'not_found' }, 404);

  const repoId = deriveRepoId(row);
  if (!repoId) return c.json({ error: 'invalid_repo' }, 400);

  const owner = (row.owner ?? repoId.split('/')[0] ?? '').trim();
  const name = (row.name ?? repoId.split('/')[1] ?? repoId).trim();

  const existing = await first<{ user_id: string | null }>(
    c.env.DB,
    'SELECT user_id FROM my_repositories WHERE id = ?',
    [repoId]
  );
  if (existing?.user_id && existing.user_id !== user.id) {
    return c.json({ error: 'repo_owned_by_other_user' }, 409);
  }

  await run(
    c.env.DB,
    `UPDATE recommendations
        SET status = 'saved', updated_at = CURRENT_TIMESTAMP
      WHERE id = ?`,
    [id]
  );

  await run(
    c.env.DB,
    `INSERT INTO my_repositories
       (id, platform, name, description, html_url, stars, language, user_id, owner, created_at, updated_at)
     VALUES (?, 'github', ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
     ON CONFLICT(id) DO UPDATE SET
       name = excluded.name,
       description = excluded.description,
       html_url = excluded.html_url,
       stars = excluded.stars,
       language = excluded.language,
       owner = excluded.owner,
       user_id = COALESCE(my_repositories.user_id, excluded.user_id),
       updated_at = CURRENT_TIMESTAMP`,
    [
      repoId,
      name,
      row.description ?? null,
      row.url ?? `https://github.com/${repoId}`,
      row.stars ?? 0,
      row.language ?? null,
      user.id,
      owner || null,
    ]
  );

  await recordFeedback(c.env.DB, user.id, id, repoId, 'saved', null);

  return c.json({ ok: true, status: 'saved', repoId });
});

recommend.post('/:id/dismiss', async (c) => {
  const user = c.get('user');
  if (!user) return c.json({ error: 'unauthorized' }, 401);

  const id = c.req.param('id');
  const row = await findRecommendation(c.env.DB, user.id, id);
  if (!row) return c.json({ error: 'not_found' }, 404);

  const repoId = deriveRepoId(row);
  if (!repoId) return c.json({ error: 'invalid_repo' }, 400);

  const body = await readBody(c);
  const reason = normalizeDismissReason(body?.reason);

  await run(
    c.env.DB,
    `UPDATE recommendations
        SET status = 'dismissed', updated_at = CURRENT_TIMESTAMP
      WHERE id = ?`,
    [id]
  );
  await recordFeedback(c.env.DB, user.id, id, repoId, 'dismissed', reason);

  return c.json({ ok: true, status: 'dismissed', repoId });
});

recommend.post('/:id/click', async (c) => {
  const user = c.get('user');
  if (!user) return c.json({ error: 'unauthorized' }, 401);

  const id = c.req.param('id');
  const row = await findRecommendation(c.env.DB, user.id, id);
  if (!row) return c.json({ error: 'not_found' }, 404);

  const repoId = deriveRepoId(row);
  if (!repoId) return c.json({ error: 'invalid_repo' }, 400);

  await recordFeedback(c.env.DB, user.id, id, repoId, 'clicked', null);
  return c.json({ ok: true });
});

export default recommend;
