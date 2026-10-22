/**
 * 监控与告警路由（REQ-202610-0941 / M5-03）
 *
 * 登录态：
 *   GET  /api/monitoring/health       边缘存活 + 指标能力（公开）
 *   GET  /api/monitoring/overview     Workers 指标 + VPS 状态统一视图
 *   POST /api/monitoring/check        代理 VPS 立即检查
 *   POST /api/monitoring/alerts/:id/ack  代理 VPS 确认告警
 *
 * 内部（X-Internal-Token）：
 *   GET  /api/internal/analytics      Workers 请求指标
 */
import { Hono } from 'hono';
import type { Env, Variables } from '../types';
import {
  combineStatus,
  getWorkerMetricsSummary,
  parseMetricDays,
  type WorkerMetricsSummary,
} from '../monitoring/metrics';

type AppEnv = { Bindings: Env; Variables: Variables };

const monitoring = new Hono<AppEnv>();

interface VpsResult<T> {
  ok: boolean;
  data?: T;
  error?: string;
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
      return { ok: false, error: `vps_http_${response.status}`, status: response.status };
    }
    return { ok: true, data: (await response.json()) as T };
  } catch (err) {
    console.error(`vps ${path} failed:`, err);
    return { ok: false, error: 'vps_node_unreachable' };
  }
}

monitoring.get('/health', (c) =>
  c.json({ status: 'ok', service: 'opensource-factory-edge', metrics: true })
);

monitoring.get('/overview', async (c) => {
  const user = c.get('user');
  if (!user) {
    return c.json({ error: 'unauthorized' }, 401);
  }

  const days = parseMetricDays(c.req.query('days'));
  let workers: WorkerMetricsSummary | null = null;
  let workersError: string | null = null;
  try {
    workers = await getWorkerMetricsSummary(c.env.DB, days);
  } catch (err) {
    console.error('worker metrics query failed:', err);
    workersError = 'worker_metrics_unavailable';
  }

  const vps = await vpsRequest<Record<string, unknown>>(c.env, '/api/monitoring/status');
  const vpsStatus = vps.ok ? (vps.data?.status as string | undefined) : undefined;

  return c.json({
    status: combineStatus(vpsStatus, workers),
    generatedAt: new Date().toISOString(),
    edge: { status: 'ok', metrics: true },
    workers,
    workersError,
    vps: vps.ok ? vps.data : null,
    vpsError: vps.ok ? null : vps.error ?? 'vps_unavailable',
  });
});

monitoring.post('/check', async (c) => {
  const user = c.get('user');
  if (!user) {
    return c.json({ error: 'unauthorized' }, 401);
  }
  const result = await vpsRequest<Record<string, unknown>>(c.env, '/api/monitoring/check', {
    method: 'POST',
  });
  if (!result.ok) {
    return c.json({ error: result.error ?? 'vps_unavailable' }, 502);
  }
  return c.json(result.data);
});

monitoring.post('/alerts/:id/ack', async (c) => {
  const user = c.get('user');
  if (!user) {
    return c.json({ error: 'unauthorized' }, 401);
  }
  const alertId = encodeURIComponent(c.req.param('id'));
  const result = await vpsRequest<Record<string, unknown>>(
    c.env,
    `/api/monitoring/alerts/${alertId}/ack`,
    { method: 'POST' }
  );
  if (!result.ok) {
    const status = result.status === 404 ? 404 : 502;
    return c.json({ error: result.error ?? 'vps_unavailable' }, status);
  }
  return c.json(result.data);
});

export const internalAnalytics = new Hono<AppEnv>();

internalAnalytics.get('/', async (c) => {
  const expected = (c.env.INTERNAL_TOKEN ?? '').trim();
  if (!expected) {
    return c.json({ error: 'internal_token_not_configured' }, 503);
  }
  if ((c.req.header('X-Internal-Token') ?? '') !== expected) {
    return c.json({ error: 'unauthorized' }, 401);
  }
  const days = parseMetricDays(c.req.query('days'));
  const summary = await getWorkerMetricsSummary(c.env.DB, days);
  return c.json(summary);
});

export default monitoring;
