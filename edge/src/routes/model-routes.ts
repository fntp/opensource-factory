/**
 * 模型路由代理（REQ-202610-0965 / M7-06）
 *
 * 全部端点要求登录态，转发到 VPS `/api/model-routes`，并透传内部令牌：
 *   GET    /api/model-routes
 *   PUT    /api/model-routes/:task
 *   DELETE /api/model-routes/:task
 *   POST   /api/model-routes/reset
 *   POST   /api/model-routes/upgrade
 *   GET    /api/model-routes/health
 */
import { Hono } from 'hono';
import type { Env, Variables } from '../types';

type AppEnv = { Bindings: Env; Variables: Variables };

interface VpsResult<T> {
  ok: boolean;
  data?: T;
  error?: string;
  detail?: string;
  status?: number;
}

async function vpsRequest<T>(
  env: Env,
  path: string,
  init: RequestInit = {}
): Promise<VpsResult<T>> {
  const base = (env.VPS_NODE_URL ?? '').trim();
  if (!base) {
    return { ok: false, error: 'vps_node_not_configured' };
  }
  try {
    const response = await fetch(`${base.replace(/\/+$/, '')}${path}`, {
      ...init,
      headers: {
        'Content-Type': 'application/json',
        'X-Internal-Token': env.INTERNAL_TOKEN ?? '',
        ...(init.headers ?? {}),
      },
      signal: AbortSignal.timeout(5000),
    });
    if (!response.ok) {
      let detail = '';
      try {
        const payload = (await response.json()) as { detail?: string; error?: string };
        detail = payload.detail ?? payload.error ?? '';
      } catch {
        detail = '';
      }
      return {
        ok: false,
        error: `vps_http_${response.status}`,
        detail,
        status: response.status,
      };
    }
    return { ok: true, data: (await response.json()) as T };
  } catch (err) {
    console.error(`vps ${path} failed:`, err);
    return { ok: false, error: 'vps_node_unreachable' };
  }
}

function errorStatus(result: VpsResult<unknown>): 400 | 404 | 502 | 503 {
  if (result.error === 'vps_node_not_configured') return 503;
  if (result.status === 400) return 400;
  if (result.status === 404) return 404;
  return 502;
}

function errorBody(result: VpsResult<unknown>): { error: string; detail?: string } {
  return result.detail
    ? { error: result.error ?? 'vps_unavailable', detail: result.detail }
    : { error: result.error ?? 'vps_unavailable' };
}

const modelRoutes = new Hono<AppEnv>();

modelRoutes.get('/', async (c) => {
  if (!c.get('user')) return c.json({ error: 'unauthorized' }, 401);
  const result = await vpsRequest<Record<string, unknown>>(c.env, '/api/model-routes');
  if (!result.ok) return c.json(errorBody(result), errorStatus(result));
  return c.json(result.data);
});

modelRoutes.put('/:task', async (c) => {
  if (!c.get('user')) return c.json({ error: 'unauthorized' }, 401);
  let payload: unknown;
  try {
    payload = await c.req.json();
  } catch {
    return c.json({ error: 'invalid_json' }, 400);
  }
  const task = encodeURIComponent(c.req.param('task'));
  const result = await vpsRequest<Record<string, unknown>>(
    c.env,
    `/api/model-routes/${task}`,
    { method: 'PUT', body: JSON.stringify(payload) }
  );
  if (!result.ok) return c.json(errorBody(result), errorStatus(result));
  return c.json(result.data);
});

modelRoutes.delete('/:task', async (c) => {
  if (!c.get('user')) return c.json({ error: 'unauthorized' }, 401);
  const task = encodeURIComponent(c.req.param('task'));
  const result = await vpsRequest<Record<string, unknown>>(
    c.env,
    `/api/model-routes/${task}`,
    { method: 'DELETE' }
  );
  if (!result.ok) return c.json(errorBody(result), errorStatus(result));
  return c.json(result.data);
});

modelRoutes.post('/reset', async (c) => {
  if (!c.get('user')) return c.json({ error: 'unauthorized' }, 401);
  const result = await vpsRequest<Record<string, unknown>>(
    c.env,
    '/api/model-routes/reset',
    { method: 'POST' }
  );
  if (!result.ok) return c.json(errorBody(result), errorStatus(result));
  return c.json(result.data);
});

modelRoutes.post('/upgrade', async (c) => {
  if (!c.get('user')) return c.json({ error: 'unauthorized' }, 401);
  let payload: unknown;
  try {
    payload = await c.req.json();
  } catch {
    return c.json({ error: 'invalid_json' }, 400);
  }
  const result = await vpsRequest<Record<string, unknown>>(
    c.env,
    '/api/model-routes/upgrade',
    { method: 'POST', body: JSON.stringify(payload) }
  );
  if (!result.ok) return c.json(errorBody(result), errorStatus(result));
  return c.json(result.data);
});

modelRoutes.get('/health', async (c) => {
  if (!c.get('user')) return c.json({ error: 'unauthorized' }, 401);
  const result = await vpsRequest<Record<string, unknown>>(
    c.env,
    '/api/model-routes/health'
  );
  if (!result.ok) return c.json(errorBody(result), errorStatus(result));
  return c.json(result.data);
});

export default modelRoutes;
