/**
 * 站内通知中心路由（M4-02）。
 *
 * 登录态接口：
 *   GET  /api/notifications
 *   GET  /api/notifications/unread-count
 *   POST /api/notifications/:id/read
 *   POST /api/notifications/read-all
 *   POST /api/notifications/:id/dismiss
 *
 * 内部接口（X-Internal-Token）：
 *   POST /api/internal/notifications
 *   POST /api/internal/notifications/sync-recommendations
 *
 * 通知来源：D1 recommendations 中 status='pushed' 的记录在读取时惰性物化，
 * 同一用户 + 同一推荐由唯一索引保证只生成一次。
 */
import { Hono } from 'hono';
import type { Context } from 'hono';
import type {
  Env,
  NotificationRow,
  RecommendationRow,
  Variables,
} from '../types';
import { all, count, first, run } from '../db';
import {
  buildRecommendationNotification,
  normalizeNotificationLimit,
  normalizeNotificationOffset,
  normalizeNotificationStatus,
  toNotificationItem,
  truncateText,
} from '../notifications/helpers';

type AppEnv = { Bindings: Env; Variables: Variables };
type AppContext = Context<AppEnv>;

const notifications = new Hono<AppEnv>();

const INSERT_NOTIFICATION_SQL = `INSERT OR IGNORE INTO notifications
  (id, user_id, type, title, body, url, repo_id, recommendation_id,
   dedupe_key, score, reason, language, stars, status, payload, created_at)
  VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`;

/** 内部令牌校验：未配置 INTERNAL_TOKEN 时一律拒绝。 */
export function hasInternalToken(c: AppContext): boolean {
  const expected = c.env.INTERNAL_TOKEN;
  const actual = c.req.header('X-Internal-Token');
  return Boolean(expected) && actual === expected;
}

function currentUser(c: AppContext) {
  return c.get('user');
}

function notificationParams(row: NotificationRow): Array<string | number | null> {
  return [
    row.id,
    row.user_id,
    row.type,
    row.title,
    row.body,
    row.url,
    row.repo_id,
    row.recommendation_id,
    row.dedupe_key,
    row.score,
    row.reason,
    row.language,
    row.stars,
    row.status,
    row.payload,
    row.created_at,
  ];
}

/**
 * 把当前用户可见（自己的 + 全局）的 pushed 推荐物化为通知。
 * 单次最多 100 条，返回本次新生成的数量。
 */
export async function syncPushedRecommendations(
  db: D1Database,
  userId: string
): Promise<number> {
  const rows = await all<RecommendationRow>(
    db,
    `SELECT r.* FROM recommendations r
      WHERE (r.user_id = ? OR r.user_id IS NULL)
        AND r.status = 'pushed'
        AND NOT EXISTS (
          SELECT 1 FROM notifications n
           WHERE n.user_id = ? AND n.recommendation_id = r.id
        )
      ORDER BY r.created_at DESC, r.id DESC
      LIMIT 100`,
    [userId, userId]
  );
  if (rows.length === 0) return 0;

  const now = new Date().toISOString();
  const statements = rows.map((row) =>
    db
      .prepare(INSERT_NOTIFICATION_SQL)
      .bind(
        ...notificationParams(
          buildRecommendationNotification(row, userId, crypto.randomUUID(), now)
        )
      )
  );
  const results = await db.batch(statements);
  return results.reduce(
    (total, result) => total + (result.meta?.changes ?? 0),
    0
  );
}

async function unreadCount(db: D1Database, userId: string): Promise<number> {
  return count(
    db,
    `SELECT COUNT(*) AS n FROM notifications
      WHERE user_id = ? AND status = 'unread'`,
    [userId]
  );
}

// ── 登录态接口 ──────────────────────────────────────────────────

notifications.get('/', async (c) => {
  const user = currentUser(c);
  if (!user) return c.json({ error: 'unauthorized' }, 401);

  await syncPushedRecommendations(c.env.DB, user.id);

  const status = normalizeNotificationStatus(c.req.query('status'));
  const limit = normalizeNotificationLimit(c.req.query('limit'));
  const offset = normalizeNotificationOffset(c.req.query('offset'));
  const statusSql =
    status === 'unread'
      ? `status = 'unread'`
      : status === 'read'
        ? `status = 'read'`
        : `status IN ('unread', 'read')`;

  const rows = await all<NotificationRow>(
    c.env.DB,
    `SELECT * FROM notifications
      WHERE user_id = ? AND ${statusSql}
      ORDER BY created_at DESC, id DESC
      LIMIT ? OFFSET ?`,
    [user.id, limit, offset]
  );
  const total = await count(
    c.env.DB,
    `SELECT COUNT(*) AS n FROM notifications
      WHERE user_id = ? AND ${statusSql}`,
    [user.id]
  );
  const unread = await unreadCount(c.env.DB, user.id);

  return c.json({
    items: rows.map(toNotificationItem),
    total,
    unread,
    limit,
    offset,
    hasMore: offset + rows.length < total,
  });
});

notifications.get('/unread-count', async (c) => {
  const user = currentUser(c);
  if (!user) return c.json({ error: 'unauthorized' }, 401);

  await syncPushedRecommendations(c.env.DB, user.id);
  return c.json({ unread: await unreadCount(c.env.DB, user.id) });
});

notifications.post('/read-all', async (c) => {
  const user = currentUser(c);
  if (!user) return c.json({ error: 'unauthorized' }, 401);

  const result = await run(
    c.env.DB,
    `UPDATE notifications
        SET status = 'read', read_at = CURRENT_TIMESTAMP
      WHERE user_id = ? AND status = 'unread'`,
    [user.id]
  );
  return c.json({ updated: result.meta?.changes ?? 0, unread: 0 });
});

notifications.post('/:id/read', async (c) => {
  const user = currentUser(c);
  if (!user) return c.json({ error: 'unauthorized' }, 401);

  const id = c.req.param('id');
  const row = await first<NotificationRow>(
    c.env.DB,
    `SELECT * FROM notifications WHERE id = ? AND user_id = ?`,
    [id, user.id]
  );
  if (!row || row.status === 'dismissed') {
    return c.json({ error: 'not_found' }, 404);
  }

  if (row.status === 'unread') {
    await run(
      c.env.DB,
      `UPDATE notifications
          SET status = 'read', read_at = CURRENT_TIMESTAMP
        WHERE id = ? AND user_id = ?`,
      [id, user.id]
    );
  }
  const updated = await first<NotificationRow>(
    c.env.DB,
    `SELECT * FROM notifications WHERE id = ? AND user_id = ?`,
    [id, user.id]
  );
  return c.json({
    id,
    status: 'read',
    readAt: updated?.read_at ?? null,
  });
});

notifications.post('/:id/dismiss', async (c) => {
  const user = currentUser(c);
  if (!user) return c.json({ error: 'unauthorized' }, 401);

  const id = c.req.param('id');
  const row = await first<NotificationRow>(
    c.env.DB,
    `SELECT * FROM notifications WHERE id = ? AND user_id = ?`,
    [id, user.id]
  );
  if (!row) return c.json({ error: 'not_found' }, 404);

  await run(
    c.env.DB,
    `UPDATE notifications
        SET status = 'dismissed', read_at = CURRENT_TIMESTAMP
      WHERE id = ? AND user_id = ?`,
    [id, user.id]
  );

  // 忽略通知时同步关闭用户自己的推荐；全局推荐（user_id IS NULL）不改状态，
  // 否则一个用户忽略会影响所有用户。通知行本身已 dismissed，不会再物化。
  if (row.recommendation_id) {
    await run(
      c.env.DB,
      `UPDATE recommendations
          SET status = 'dismissed'
        WHERE id = ?
          AND user_id = ?
          AND status NOT IN ('saved', 'dismissed')`,
      [row.recommendation_id, user.id]
    );
  }

  return c.json({ id, status: 'dismissed' });
});

// ── 内部接口 ────────────────────────────────────────────────────

interface InternalNotificationInput {
  userId?: unknown;
  type?: unknown;
  title?: unknown;
  body?: unknown;
  url?: unknown;
  repoId?: unknown;
  recommendationId?: unknown;
  dedupeKey?: unknown;
  score?: unknown;
  reason?: unknown;
  language?: unknown;
  stars?: unknown;
  payload?: unknown;
}

export const internalNotifications = new Hono<AppEnv>();

internalNotifications.post('/', async (c) => {
  if (!hasInternalToken(c)) {
    return c.json({ error: 'unauthorized' }, 401);
  }

  let body: { notifications?: InternalNotificationInput[] };
  try {
    body = (await c.req.json()) as { notifications?: InternalNotificationInput[] };
  } catch {
    return c.json({ error: 'invalid_json' }, 400);
  }
  const items = Array.isArray(body.notifications) ? body.notifications : [];
  if (items.length === 0) return c.json({ error: 'empty_notifications' }, 400);
  if (items.length > 100) return c.json({ error: 'too_many_notifications' }, 400);

  const now = new Date().toISOString();
  const statements: D1PreparedStatement[] = [];
  for (const item of items) {
    const userId = truncateText(item.userId, 128);
    const title = truncateText(item.title, 500);
    if (!userId || !title) {
      return c.json({ error: 'user_id_and_title_required' }, 400);
    }
    const recommendationId = truncateText(item.recommendationId, 128) || null;
    const dedupeKey =
      truncateText(item.dedupeKey, 200) ||
      (recommendationId ? `recommendation:${recommendationId}` : null);
    const payload =
      typeof item.payload === 'string'
        ? item.payload.slice(0, 4000)
        : item.payload
          ? JSON.stringify(item.payload).slice(0, 4000)
          : null;

    statements.push(
      c.env.DB.prepare(INSERT_NOTIFICATION_SQL).bind(
        crypto.randomUUID(),
        userId,
        truncateText(item.type, 32) || 'system',
        title,
        truncateText(item.body, 4000) || null,
        truncateText(item.url, 1000) || null,
        truncateText(item.repoId, 255) || null,
        recommendationId,
        dedupeKey,
        typeof item.score === 'number' ? item.score : null,
        truncateText(item.reason, 2000) || null,
        truncateText(item.language, 64) || null,
        typeof item.stars === 'number' ? Math.trunc(item.stars) : 0,
        'unread',
        payload,
        now
      )
    );
  }

  const results = await c.env.DB.batch(statements);
  const created = results.reduce(
    (total, result) => total + (result.meta?.changes ?? 0),
    0
  );
  return c.json({ created, skipped: items.length - created });
});

internalNotifications.post('/sync-recommendations', async (c) => {
  if (!hasInternalToken(c)) {
    return c.json({ error: 'unauthorized' }, 401);
  }
  let body: { userId?: unknown };
  try {
    body = (await c.req.json()) as { userId?: unknown };
  } catch {
    return c.json({ error: 'invalid_json' }, 400);
  }
  const userId = truncateText(body.userId, 128);
  if (!userId) return c.json({ error: 'user_id_required' }, 400);

  const created = await syncPushedRecommendations(c.env.DB, userId);
  return c.json({ created });
});

export default notifications;
