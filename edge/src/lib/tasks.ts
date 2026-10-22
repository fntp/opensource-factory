/**
 * 同步任务工具（REQ-202610-0900 / M1-08）
 *
 * - 归一化 VPS / Celery 任务状态为前端契约；
 * - 解析 D1 中的 JSON 快照；
 * - 拉取 VPS `GET /api/tasks/{taskId}` 并回写 D1。
 */
import type { Env, SyncTask, SyncTaskRow, TaskProgress } from '../types';

/** 终态：不再轮询 VPS */
export const TERMINAL_STATUSES = new Set(['success', 'failure']);

const STATUS_MAP: Record<string, string> = {
  pending: 'pending',
  received: 'pending',
  retry: 'started',
  started: 'started',
  progress: 'progress',
  success: 'success',
  failure: 'failure',
  revoked: 'failure',
};

/** 把 Celery / VPS 的状态字符串归一化为前端契约值 */
export function normalizeTaskStatus(raw: string | null | undefined): string {
  const key = String(raw ?? '').trim().toLowerCase();
  return STATUS_MAP[key] ?? 'unknown';
}

export function isTerminalStatus(status: string): boolean {
  return TERMINAL_STATUSES.has(status);
}

/** 安全解析 D1 中的 JSON 文本列 */
export function parseJson<T>(value: string | null | undefined): T | null {
  if (!value) return null;
  try {
    return JSON.parse(value) as T;
  } catch {
    return null;
  }
}

/** D1 行 → API 响应 */
export function toSyncTask(row: SyncTaskRow, stale = false): SyncTask {
  return {
    taskId: row.id,
    type: row.task_type,
    status: normalizeTaskStatus(row.status),
    progress: parseJson<TaskProgress>(row.progress),
    result: parseJson<unknown>(row.result) ?? row.result,
    error: row.error,
    createdAt: row.created_at,
    updatedAt: row.updated_at,
    finishedAt: row.finished_at,
    ...(stale ? { stale: true } : {}),
  };
}

/** 入队成功后写入任务表；失败只记日志（不阻塞已入队的同步任务） */
export async function createSyncTask(
  env: Env,
  taskId: string,
  userId: string | null,
  taskType = 'sync'
): Promise<boolean> {
  try {
    await env.DB.prepare(
      `INSERT INTO sync_tasks (id, user_id, task_type, status, created_at, updated_at)
       VALUES (?, ?, ?, 'pending', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
       ON CONFLICT(id) DO UPDATE SET
         user_id = excluded.user_id,
         task_type = excluded.task_type,
         status = 'pending',
         updated_at = CURRENT_TIMESTAMP`
    )
      .bind(taskId, userId, taskType)
      .run();
    return true;
  } catch (err) {
    console.error('create sync task failed:', err);
    return false;
  }
}

export interface VpsTaskSnapshot {
  taskId: string;
  status: string;
  progress: TaskProgress | null;
  result: unknown;
  error: string | null;
}

/** 查询 VPS 任务状态；VPS 未配置 / 不可达 / 响应异常时返回 null（调用方降级） */
export async function fetchVpsTask(env: Env, taskId: string): Promise<VpsTaskSnapshot | null> {
  const base = env.VPS_NODE_URL?.trim();
  if (!base) return null;

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 5000);
  try {
    const res = await fetch(
      `${base.replace(/\/+$/, '')}/api/tasks/${encodeURIComponent(taskId)}`,
      {
        headers: { 'X-Internal-Token': env.INTERNAL_TOKEN ?? '' },
        signal: controller.signal,
      }
    );
    if (!res.ok) return null;
    const body = (await res.json()) as {
      taskId?: string;
      status?: string;
      progress?: TaskProgress | null;
      result?: unknown;
      error?: string | null;
    };
    if (!body || typeof body !== 'object' || !body.status) return null;
    return {
      taskId: body.taskId ?? taskId,
      status: normalizeTaskStatus(body.status),
      progress: body.progress ?? null,
      result: body.result ?? null,
      error: body.error ? String(body.error).slice(0, 500) : null,
    };
  } catch (err) {
    console.error('fetch vps task failed:', err);
    return null;
  } finally {
    clearTimeout(timer);
  }
}

/** 把 VPS 最新快照写回 D1，返回更新后的行 */
export async function persistTaskSnapshot(
  env: Env,
  row: SyncTaskRow,
  snapshot: VpsTaskSnapshot
): Promise<SyncTaskRow> {
  const now = new Date().toISOString();
  const terminal = isTerminalStatus(snapshot.status);
  const progress =
    snapshot.progress != null ? JSON.stringify(snapshot.progress) : row.progress;
  const result =
    snapshot.result != null ? JSON.stringify(snapshot.result) : row.result;
  const error = snapshot.error ?? (snapshot.status === 'success' ? null : row.error);
  const finishedAt = terminal ? (row.finished_at ?? now) : null;

  await env.DB.prepare(
    `UPDATE sync_tasks
        SET status = ?, progress = ?, result = ?, error = ?, updated_at = ?, finished_at = ?
      WHERE id = ?`
  )
    .bind(snapshot.status, progress, result, error, now, finishedAt, row.id)
    .run();

  return {
    ...row,
    status: snapshot.status,
    progress,
    result,
    error,
    updated_at: now,
    finished_at: finishedAt,
  };
}
