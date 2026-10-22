/**
 * 同步触发路由（REQ-202610-0900 / M1-08）
 * POST /api/sync
 * - 配置了 VPS_NODE_URL：转发到 `${VPS_NODE_URL}/api/tasks/sync`（带内部令牌），
 *   把返回的 taskId 写入 `sync_tasks`，返回 202 {"status":"queued","taskId":"..."}
 * - 未配置：仅接受请求，返回 202 {"status":"accepted","note":"vps node not configured"}
 */
import { Hono } from 'hono';
import type { Env, Variables } from '../types';
import { createSyncTask } from '../lib/tasks';

const sync = new Hono<{ Bindings: Env; Variables: Variables }>();

sync.post('/', async (c) => {
  const user = c.get('user');
  if (!user) {
    return c.json({ error: 'unauthorized' }, 401);
  }
  const vpsUrl = c.env.VPS_NODE_URL?.trim();

  if (!vpsUrl) {
    return c.json({ status: 'accepted', note: 'vps node not configured' }, 202);
  }

  try {
    const res = await fetch(`${vpsUrl.replace(/\/+$/, '')}/api/tasks/sync`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Internal-Token': c.env.INTERNAL_TOKEN ?? '',
      },
      body: JSON.stringify({
        requestedBy: user.id,
        requestedAt: new Date().toISOString(),
      }),
    });

    if (!res.ok) {
      return c.json({ error: 'vps_node_error', upstreamStatus: res.status }, 502);
    }

    const payload = (await res.json().catch(() => null)) as { taskId?: string } | null;
    const taskId = payload?.taskId;
    if (!taskId) {
      return c.json({ error: 'vps_invalid_response' }, 502);
    }

    const tracked = await createSyncTask(c.env, taskId, user.id, 'sync');
    return c.json({ status: 'queued', taskId, tracked }, 202);
  } catch (err) {
    console.error('sync forward failed:', err);
    return c.json({ error: 'vps_node_unreachable' }, 502);
  }
});

export default sync;
