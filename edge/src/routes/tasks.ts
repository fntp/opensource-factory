/**
 * 同步任务路由（REQ-202610-0900 / M1-08）
 *
 * - GET /api/tasks          当前用户最近任务（默认 20 条，最多 100）
 * - GET /api/tasks/:taskId  任务详情；非终态任务会向 VPS 拉取最新状态并回写 D1
 *
 * 契约对齐 VPS `GET /api/tasks/{taskId}`：{taskId, status, progress?, result?, error?}
 */
import { Hono } from 'hono';
import type { Env, SyncTaskRow, Variables } from '../types';
import {
  fetchVpsTask,
  isTerminalStatus,
  normalizeTaskStatus,
  persistTaskSnapshot,
  toSyncTask,
} from '../lib/tasks';

const tasks = new Hono<{ Bindings: Env; Variables: Variables }>();

/** 列表接口最多顺带刷新 5 个活跃任务，避免一次请求打爆 VPS */
const MAX_REFRESH_PER_LIST = 5;

tasks.get('/', async (c) => {
  const user = c.get('user');
  if (!user) {
    return c.json({ error: 'unauthorized' }, 401);
  }

  const rawLimit = Number(c.req.query('limit') ?? 20);
  const limit = Number.isFinite(rawLimit)
    ? Math.min(Math.max(Math.trunc(rawLimit), 1), 100)
    : 20;

  const { results } = await c.env.DB.prepare(
    `SELECT id, user_id, task_type, status, progress, result, error,
            created_at, updated_at, finished_at
       FROM sync_tasks
      WHERE user_id = ?
      ORDER BY created_at DESC
      LIMIT ?`
  )
    .bind(user.id, limit)
    .all<SyncTaskRow>();

  const rows = results ?? [];
  const active = rows
    .filter((row) => !isTerminalStatus(normalizeTaskStatus(row.status)))
    .slice(0, MAX_REFRESH_PER_LIST);

  const refreshed = new Map<string, SyncTaskRow>();
  await Promise.all(
    active.map(async (row) => {
      const snapshot = await fetchVpsTask(c.env, row.id);
      if (!snapshot) return;
      try {
        refreshed.set(row.id, await persistTaskSnapshot(c.env, row, snapshot));
      } catch (err) {
        console.error('persist task snapshot failed:', err);
      }
    })
  );

  return c.json({
    tasks: rows.map((row) => toSyncTask(refreshed.get(row.id) ?? row)),
  });
});

tasks.get('/:taskId', async (c) => {
  const user = c.get('user');
  if (!user) {
    return c.json({ error: 'unauthorized' }, 401);
  }

  const taskId = c.req.param('taskId');
  const row = await c.env.DB.prepare(
    `SELECT id, user_id, task_type, status, progress, result, error,
            created_at, updated_at, finished_at
       FROM sync_tasks
      WHERE id = ? AND user_id = ?`
  )
    .bind(taskId, user.id)
    .first<SyncTaskRow>();

  if (!row) {
    return c.json({ error: 'not_found' }, 404);
  }

  if (isTerminalStatus(normalizeTaskStatus(row.status))) {
    return c.json(toSyncTask(row));
  }

  const snapshot = await fetchVpsTask(c.env, taskId);
  if (!snapshot) {
    // VPS 不可达：返回 D1 最后一次快照，标记 stale，避免 admin 因 5xx 中断轮询
    return c.json(toSyncTask(row, true));
  }

  try {
    const updated = await persistTaskSnapshot(c.env, row, snapshot);
    return c.json(toSyncTask(updated));
  } catch (err) {
    console.error('persist task snapshot failed:', err);
    return c.json(toSyncTask(row, true));
  }
});

export default tasks;
