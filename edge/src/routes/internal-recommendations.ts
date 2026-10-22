/**
 * 内部推荐接口（VPS → edge）。
 *
 * 仅允许携带 `X-Internal-Token` 的服务端调用；未配置令牌时返回 503（默认关闭）。
 *
 * POST /api/internal/recommendations/upsert   推荐生成结果回写 D1
 * GET  /api/internal/recommendations/feedback 读取用户反馈（saved / dismissed / clicked）
 */
import { Hono } from 'hono';
import type { Env, RecommendationRow, Variables } from '../types';
import { all, first, run } from '../db';
import { deriveRepoId, shouldKeepUserStatus } from '../recommend/feedback';

const router = new Hono<{ Bindings: Env; Variables: Variables }>();

const MAX_ITEMS = 500;
const MAX_TEXT = 500;
const MAX_REASON = 5000;

type UpsertItem = {
  id: string;
  repoId: string;
  score: number;
  reason: string | null;
  basedOn: string[];
  owner: string | null;
  name: string | null;
  description: string | null;
  language: string | null;
  stars: number;
  url: string | null;
  status: string;
};

function text(value: unknown, max: number): string | null {
  if (typeof value !== 'string') return null;
  const trimmed = value.trim();
  if (!trimmed) return null;
  return trimmed.slice(0, max);
}

function isItem(value: unknown): value is UpsertItem {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false;
  const item = value as Record<string, unknown>;
  if (typeof item.id !== 'string' || !item.id.trim() || item.id.length > 64) return false;
  if (typeof item.repoId !== 'string' || !item.repoId.trim() || item.repoId.length > 255) return false;
  if (typeof item.score !== 'number' || !Number.isFinite(item.score)) return false;
  if (item.basedOn !== undefined && !Array.isArray(item.basedOn)) return false;
  if (typeof item.stars !== 'number' || !Number.isFinite(item.stars)) return false;
  return true;
}

function normalizeItem(value: unknown): UpsertItem | null {
  if (!isItem(value)) return null;
  return {
    id: value.id.trim(),
    repoId: value.repoId.trim(),
    score: Math.max(0, Math.min(1, value.score)),
    reason: text(value.reason, MAX_REASON),
    basedOn: Array.isArray(value.basedOn) ? value.basedOn.map((v) => String(v)).slice(0, 20) : [],
    owner: text(value.owner, MAX_TEXT),
    name: text(value.name, MAX_TEXT),
    description: text(value.description, MAX_REASON),
    language: text(value.language, MAX_TEXT),
    stars: Math.max(0, Math.trunc(value.stars)),
    url: text(value.url, MAX_REASON),
    status: text(value.status, 32) ?? 'new',
  };
}

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

// 内部令牌鉴权：未配置 → 503（与 Vectorize / 一致性接口口径一致）；不匹配 → 401
router.use('*', async (c, next) => {
  const expected = (c.env.INTERNAL_TOKEN ?? '').trim();
  if (!expected) {
    return c.json({ error: 'internal_token_not_configured' }, 503);
  }
  const provided = (c.req.header('X-Internal-Token') ?? '').trim();
  if (provided !== expected) {
    return c.json({ error: 'unauthorized' }, 401);
  }
  await next();
});

router.post('/upsert', async (c) => {
  const body = await readBody(c);
  const userId = text(body?.userId, 128);
  const rawItems = body?.items;
  if (!userId) return c.json({ error: 'invalid_body', message: 'userId 必填' }, 400);
  if (!Array.isArray(rawItems) || rawItems.length === 0 || rawItems.length > MAX_ITEMS) {
    return c.json({ error: 'invalid_batch', message: `items 数量需为 1~${MAX_ITEMS}` }, 400);
  }

  const items = rawItems.map(normalizeItem);
  if (items.some((item) => item === null)) {
    return c.json({ error: 'invalid_item', message: '推荐条目格式不合法' }, 400);
  }

  let count = 0;
  for (const item of items as UpsertItem[]) {
    const existing = await first<Pick<RecommendationRow, 'status'>>(
      c.env.DB,
      'SELECT status FROM recommendations WHERE id = ?',
      [item.id]
    );
    const status = existing && shouldKeepUserStatus(existing.status) ? existing.status : item.status;

    await run(
      c.env.DB,
      `INSERT INTO recommendations
         (id, user_id, repo_id, owner, name, description, language, stars, score, reason,
          based_on, url, status, created_at, updated_at)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
       ON CONFLICT(id) DO UPDATE SET
         user_id = excluded.user_id,
         repo_id = excluded.repo_id,
         owner = excluded.owner,
         name = excluded.name,
         description = excluded.description,
         language = excluded.language,
         stars = excluded.stars,
         score = excluded.score,
         reason = excluded.reason,
         based_on = excluded.based_on,
         url = excluded.url,
         status = CASE
           WHEN recommendations.status IN ('saved', 'dismissed') THEN recommendations.status
           ELSE excluded.status
         END,
         updated_at = CURRENT_TIMESTAMP`,
      [
        item.id,
        userId,
        item.repoId,
        item.owner,
        item.name,
        item.description,
        item.language,
        item.stars,
        item.score,
        item.reason,
        JSON.stringify(item.basedOn),
        item.url,
        status,
      ]
    );
    count += 1;
  }

  return c.json({ ok: true, count });
});

router.get('/feedback', async (c) => {
  const userId = (c.req.query('userId') ?? '').trim();
  if (!userId) return c.json({ error: 'invalid_query', message: 'userId 必填' }, 400);

  const feedbackRows = await all<{ repo_id: string | null; action: string }>(
    c.env.DB,
    `SELECT repo_id, action
       FROM recommendation_feedback
      WHERE user_id = ?`,
    [userId]
  );

  const statusRows = await all<RecommendationRow>(
    c.env.DB,
    `SELECT * FROM recommendations
      WHERE user_id = ? AND status IN ('saved', 'dismissed')`,
    [userId]
  );

  const saved = new Set<string>();
  const dismissed = new Set<string>();
  const clicked = new Set<string>();

  for (const row of feedbackRows) {
    const repoId = (row.repo_id ?? '').trim();
    if (!repoId) continue;
    if (row.action === 'saved') saved.add(repoId);
    if (row.action === 'dismissed') dismissed.add(repoId);
    if (row.action === 'clicked') clicked.add(repoId);
  }
  for (const row of statusRows) {
    const repoId = deriveRepoId(row);
    if (!repoId) continue;
    if (row.status === 'saved') saved.add(repoId);
    if (row.status === 'dismissed') dismissed.add(repoId);
  }

  return c.json({
    userId,
    savedRepoIds: [...saved].sort(),
    dismissedRepoIds: [...dismissed].sort(),
    clickedRepoIds: [...clicked].sort(),
  });
});

export default router;
