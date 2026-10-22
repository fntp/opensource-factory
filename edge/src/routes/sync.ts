/**
 * 同步触发路由
 * POST /api/sync
 * - 配置了 VPS_NODE_URL：转发到 `${VPS_NODE_URL}/api/tasks/sync`（带内部令牌），返回 202 {"status":"queued"}
 * - 未配置：仅接受请求，返回 202 {"status":"accepted","note":"vps node not configured"}
 */
import { Hono } from 'hono';
import type { Env, Variables } from '../types';

const sync = new Hono<{ Bindings: Env; Variables: Variables }>();

sync.post('/', async (c) => {
  const user = c.get('user');
  const vpsUrl = c.env.VPS_NODE_URL?.trim();
  // 默认增量；`?mode=full` 触发全量对账（REQ-202610-0899）
  const mode = c.req.query('mode') === 'full' ? 'full' : 'incremental';

  if (!vpsUrl) {
    return c.json({ status: 'accepted', note: 'vps node not configured' }, 202);
  }

  try {
    const res = await fetch(`${vpsUrl.replace(/\/+$/, '')}/api/tasks/sync?mode=${mode}`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Internal-Token': c.env.INTERNAL_TOKEN ?? '',
      },
      body: JSON.stringify({
        requestedBy: user?.id ?? null,
        requestedAt: new Date().toISOString(),
      }),
    });

    if (!res.ok) {
      return c.json({ error: 'vps_node_error', upstreamStatus: res.status }, 502);
    }
    return c.json({ status: 'queued' }, 202);
  } catch (err) {
    console.error('sync forward failed:', err);
    return c.json({ error: 'vps_node_unreachable' }, 502);
  }
});

export default sync;
