/**
 * 收藏项目更新提醒路由（M7-04）。
 *
 * 登录态接口：
 *   GET  /api/repo-updates                  列表 + 汇总（status / type / limit / offset）
 *   GET  /api/repo-updates/unread-count     未读数（含重大变更未读数）
 *   POST /api/repo-updates/read-all         全部已读
 *   POST /api/repo-updates/:id/read         单条已读
 *   POST /api/repo-updates/:id/dismiss      忽略
 *   POST /api/repo-updates/scan             触发 VPS 扫描当前用户收藏
 *
 * 内部接口（X-Internal-Token）：
 *   POST /api/internal/repo-updates/ingest  VPS 回写更新事件，按仓库归属扇出
 */
import { Hono } from 'hono';
import type { Context } from 'hono';
import type { Env, RepoUpdateRow, Variables } from '../types';
import { all, count, first, run } from '../db';
import { truncateText } from '../notifications/helpers';
import {
  buildRepoUpdateId,
  normalizeUpdateKind,
  normalizeUpdateLimit,
  normalizeUpdateOffset,
  normalizeUpdateState,
  normalizeUpdateStatus,
  normalizeUpdateType,
  repoUpdateNotificationTitle,
  toRepoUpdateItem,
} from '../repo-updates/helpers';

type AppEnv = { Bindings: Env; Variables: Variables };
type AppContext = Context<AppEnv>;

const repoUpdates = new Hono<AppEnv>();

const INSERT_REPO_UPDATE_SQL = `INSERT OR IGNORE INTO repo_updates
  (id, user_id, repo_id, repo_name, repo_url, type, version, title, summary,
   url, published_at, detected_at, status, read_at, payload, created_at)
  VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'unread', NULL, ?, ?)`;

const INSERT_UPDATE_NOTIFICATION_SQL = `INSERT OR IGNORE INTO notifications
  (id, user_id, type, title, body, url, repo_id, recommendation_id,
   dedupe_key, score, reason, language, stars, status, payload, created_at)
  VALUES (?, ?, 'repo_update', ?, ?, ?, ?, NULL, ?, NULL, NULL, NULL, 0, 'unread', ?, ?)`;

export function hasInternalToken(c: AppContext): boolean {
  const expected = c.env.INTERNAL_TOKEN;
  const actual = c.req.header('X-Internal-Token');
  return Boolean(expected) && actual === expected;
}

function normalizeDateTime(value: unknown): string | null {
  if (typeof value !== 'string') return null;
  const text = value.trim();
  if (!text || text.length > 40) return null;
  return text;
}

// ── 登录态接口 ──────────────────────────────────────────────────

repoUpdates.get('/', async (c) => {
  const user = c.get('user');
  if (!user) return c.json({ error: 'unauthorized' }, 401);

  const status = normalizeUpdateStatus(c.req.query('status'));
  const type = normalizeUpdateType(c.req.query('type'));
  const limit = normalizeUpdateLimit(c.req.query('limit'));
  const offset = normalizeUpdateOffset(c.req.query('offset'));

  const statusSql =
    status === 'unread'
      ? `status = 'unread'`
      : status === 'read'
        ? `status = 'read'`
        : status === 'dismissed'
          ? `status = 'dismissed'`
          : `status IN ('unread', 'read', 'dismissed')`;
  const typeSql =
    type === 'major' ? `type = 'major'` : type === 'release' ? `type = 'release'` : '1 = 1';
  const whereSql = `user_id = ? AND ${statusSql} AND ${typeSql}`;

  const rows = await all<RepoUpdateRow>(
    c.env.DB,
    `SELECT * FROM repo_updates
      WHERE ${whereSql}
      ORDER BY detected_at DESC, id DESC
      LIMIT ? OFFSET ?`,
    [user.id, limit, offset]
  );
  const total = await count(
    c.env.DB,
    `SELECT COUNT(*) AS n FROM repo_updates WHERE ${whereSql}`,
    [user.id]
  );
  const summaryRow = await first<{
    total: number;
    unread: number;
    read: number;
    dismissed: number;
    release: number;
    major: number;
    majorUnread: number;
  }>(
    c.env.DB,
    `SELECT
       COUNT(*) AS total,
       SUM(CASE WHEN status = 'unread' THEN 1 ELSE 0 END) AS unread,
       SUM(CASE WHEN status = 'read' THEN 1 ELSE 0 END) AS read,
       SUM(CASE WHEN status = 'dismissed' THEN 1 ELSE 0 END) AS dismissed,
       SUM(CASE WHEN type = 'release' THEN 1 ELSE 0 END) AS release,
       SUM(CASE WHEN type = 'major' THEN 1 ELSE 0 END) AS major,
       SUM(CASE WHEN type = 'major' AND status = 'unread' THEN 1 ELSE 0 END) AS majorUnread
     FROM repo_updates WHERE user_id = ?`,
    [user.id]
  );

  return c.json({
    items: rows.map(toRepoUpdateItem),
    total,
    limit,
    offset,
    hasMore: offset + rows.length < total,
    summary: {
      total: summaryRow?.total ?? 0,
      unread: summaryRow?.unread ?? 0,
      read: summaryRow?.read ?? 0,
      dismissed: summaryRow?.dismissed ?? 0,
      release: summaryRow?.release ?? 0,
      major: summaryRow?.major ?? 0,
      majorUnread: summaryRow?.majorUnread ?? 0,
    },
  });
});

repoUpdates.get('/unread-count', async (c) => {
  const user = c.get('user');
  if (!user) return c.json({ error: 'unauthorized' }, 401);

  const row = await first<{ unread: number; majorUnread: number }>(
    c.env.DB,
    `SELECT
       SUM(CASE WHEN status = 'unread' THEN 1 ELSE 0 END) AS unread,
       SUM(CASE WHEN status = 'unread' AND type = 'major' THEN 1 ELSE 0 END) AS majorUnread
     FROM repo_updates WHERE user_id = ?`,
    [user.id]
  );
  return c.json({ unread: row?.unread ?? 0, majorUnread: row?.majorUnread ?? 0 });
});

repoUpdates.post('/read-all', async (c) => {
  const user = c.get('user');
  if (!user) return c.json({ error: 'unauthorized' }, 401);

  const result = await run(
    c.env.DB,
    `UPDATE repo_updates
        SET status = 'read', read_at = CURRENT_TIMESTAMP
      WHERE user_id = ? AND status = 'unread'`,
    [user.id]
  );
  return c.json({ updated: result.meta?.changes ?? 0, unread: 0 });
});

repoUpdates.post('/:id/read', async (c) => {
  const user = c.get('user');
  if (!user) return c.json({ error: 'unauthorized' }, 401);

  const id = c.req.param('id');
  const row = await first<RepoUpdateRow>(
    c.env.DB,
    `SELECT * FROM repo_updates WHERE id = ? AND user_id = ?`,
    [id, user.id]
  );
  if (!row || normalizeUpdateState(row.status) === 'dismissed') {
    return c.json({ error: 'not_found' }, 404);
  }
  if (normalizeUpdateState(row.status) === 'unread') {
    await run(
      c.env.DB,
      `UPDATE repo_updates
          SET status = 'read', read_at = CURRENT_TIMESTAMP
        WHERE id = ? AND user_id = ?`,
      [id, user.id]
    );
  }
  const updated = await first<RepoUpdateRow>(
    c.env.DB,
    `SELECT * FROM repo_updates WHERE id = ? AND user_id = ?`,
    [id, user.id]
  );
  return c.json({
    id,
    status: 'read',
    readAt: updated?.read_at ?? null,
  });
});

repoUpdates.post('/:id/dismiss', async (c) => {
  const user = c.get('user');
  if (!user) return c.json({ error: 'unauthorized' }, 401);

  const id = c.req.param('id');
  const row = await first<RepoUpdateRow>(
    c.env.DB,
    `SELECT * FROM repo_updates WHERE id = ? AND user_id = ?`,
    [id, user.id]
  );
  if (!row) return c.json({ error: 'not_found' }, 404);

  await run(
    c.env.DB,
    `UPDATE repo_updates
        SET status = 'dismissed', read_at = CURRENT_TIMESTAMP
      WHERE id = ? AND user_id = ?`,
    [id, user.id]
  );
  return c.json({ id, status: 'dismissed' });
});

repoUpdates.post('/scan', async (c) => {
  const user = c.get('user');
  if (!user) return c.json({ error: 'unauthorized' }, 401);

  const vpsUrl = c.env.VPS_NODE_URL?.trim();
  if (!vpsUrl) {
    return c.json({ status: 'accepted', note: 'vps node not configured' }, 202);
  }

  const repoRows = await all<{ id: string }>(
    c.env.DB,
    `SELECT id FROM my_repositories
      WHERE user_id = ?
      ORDER BY stars DESC
      LIMIT 200`,
    [user.id]
  );
  if (repoRows.length === 0) {
    return c.json({ status: 'accepted', note: 'no repositories to scan', taskId: null }, 202);
  }

  try {
    const res = await fetch(`${vpsUrl.replace(/\/+$/, '')}/api/repos/updates/scan`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Internal-Token': c.env.INTERNAL_TOKEN ?? '',
      },
      body: JSON.stringify({
        repoIds: repoRows.map((row) => row.id),
        limit: repoRows.length,
      }),
    });
    if (!res.ok) {
      return c.json({ error: 'vps_node_error', upstreamStatus: res.status }, 502);
    }
    const payload = (await res.json().catch(() => ({}))) as { taskId?: string };
    return c.json({ status: 'queued', taskId: payload.taskId ?? null }, 202);
  } catch (err) {
    console.error('repo updates scan forward failed:', err);
    return c.json({ error: 'vps_node_unreachable' }, 502);
  }
});

// ── 内部接口：VPS 回写 ──────────────────────────────────────────

interface InternalUpdateInput {
  repoId?: unknown;
  repoName?: unknown;
  repoUrl?: unknown;
  type?: unknown;
  version?: unknown;
  title?: unknown;
  summary?: unknown;
  url?: unknown;
  publishedAt?: unknown;
  detectedAt?: unknown;
}

export const internalRepoUpdates = new Hono<AppEnv>();

internalRepoUpdates.post('/ingest', async (c) => {
  if (!hasInternalToken(c)) {
    return c.json({ error: 'unauthorized' }, 401);
  }

  let body: { items?: InternalUpdateInput[] };
  try {
    body = (await c.req.json()) as { items?: InternalUpdateInput[] };
  } catch {
    return c.json({ error: 'invalid_json' }, 400);
  }
  const items = Array.isArray(body.items) ? body.items : [];
  if (items.length === 0) return c.json({ error: 'empty_items' }, 400);
  if (items.length > 100) return c.json({ error: 'too_many_items' }, 400);

  const now = new Date().toISOString();
  const normalized = items
    .map((item) => {
      const repoId = truncateText(item.repoId, 255);
      const version = truncateText(item.version, 128);
      if (!repoId || !version) return null;
      return {
        repoId,
        repoName: truncateText(item.repoName, 255) || repoId.split('/').pop() || repoId,
        repoUrl: truncateText(item.repoUrl, 1000) || `https://github.com/${repoId}`,
        type: normalizeUpdateKind(typeof item.type === 'string' ? item.type : ''),
        version,
        title: truncateText(item.title, 500) || version,
        summary: truncateText(item.summary, 4000) || null,
        url: truncateText(item.url, 1000) || null,
        publishedAt: normalizeDateTime(item.publishedAt),
        detectedAt: normalizeDateTime(item.detectedAt) ?? now,
      };
    })
    .filter((item): item is NonNullable<typeof item> => item !== null);

  if (normalized.length === 0) {
    return c.json({ error: 'no_valid_items' }, 400);
  }

  const repoIds = [...new Set(normalized.map((item) => item.repoId))];
  const placeholders = repoIds.map(() => '?').join(',');
  const ownerRows = await all<{ id: string; user_id: string }>(
    c.env.DB,
    `SELECT id, user_id FROM my_repositories
      WHERE id IN (${placeholders}) AND user_id IS NOT NULL`,
    repoIds
  );
  const ownersByRepo = new Map<string, string[]>();
  for (const row of ownerRows) {
    const owners = ownersByRepo.get(row.id) ?? [];
    owners.push(row.user_id);
    ownersByRepo.set(row.id, owners);
  }

  const statements: D1PreparedStatement[] = [];
  const kinds: Array<'update' | 'notification'> = [];
  for (const item of normalized) {
    for (const userId of ownersByRepo.get(item.repoId) ?? []) {
      const payload = JSON.stringify({
        repoId: item.repoId,
        version: item.version,
        type: item.type,
        publishedAt: item.publishedAt,
      });
      statements.push(
        c.env.DB.prepare(INSERT_REPO_UPDATE_SQL).bind(
          buildRepoUpdateId(userId, item.repoId, item.version),
          userId,
          item.repoId,
          item.repoName,
          item.repoUrl,
          item.type,
          item.version,
          item.title,
          item.summary,
          item.url,
          item.publishedAt,
          item.detectedAt,
          payload,
          now
        )
      );
      kinds.push('update');

      statements.push(
        c.env.DB.prepare(INSERT_UPDATE_NOTIFICATION_SQL).bind(
          crypto.randomUUID(),
          userId,
          repoUpdateNotificationTitle(item.type, item.repoName, item.version),
          item.summary ?? item.title,
          item.url,
          item.repoId,
          `repo-update:${item.repoId}:${item.version}`,
          JSON.stringify({ repoId: item.repoId, version: item.version, type: item.type }),
          now
        )
      );
      kinds.push('notification');
    }
  }

  if (statements.length === 0) {
    return c.json({ created: 0, skipped: normalized.length, notifications: 0 });
  }

  const results = await c.env.DB.batch(statements);
  let created = 0;
  let notifications = 0;
  results.forEach((result, index) => {
    const changes = result.meta?.changes ?? 0;
    if (kinds[index] === 'update') created += changes;
    else notifications += changes;
  });
  const attempted = kinds.filter((kind) => kind === 'update').length;

  return c.json({
    created,
    skipped: attempted - created,
    notifications,
    unmatched: normalized.filter((item) => !ownersByRepo.has(item.repoId)).length,
  });
});

export default repoUpdates;
