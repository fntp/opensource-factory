/**
 * Vectorize 索引内部路由（VPS → Cloudflare Vectorize）
 *
 * - POST /api/internal/vectors/upsert：批量 upsert（≤1000 条）
 * - POST /api/internal/vectors/check：按 id 批量查询存在性（≤100 条）
 * - POST /api/internal/vectors/delete：按 id 批量删除（≤1000 条）
 * - GET  /api/internal/vectors/stats：索引统计（describe）
 *
 * 仅内部调用：校验 X-Internal-Token；未配置 INTERNAL_TOKEN 时返回 503（默认关闭）。
 * VPS 不持有 Cloudflare 凭据，所有 Vectorize 操作都通过本路由的绑定完成。
 */
import { Hono } from 'hono';
import type { Env, Variables } from '../types';

const internalVectors = new Hono<{ Bindings: Env; Variables: Variables }>();

const MAX_UPSERT = 1000;
const MAX_CHECK = 100;

interface VectorItem {
  id?: unknown;
  values?: unknown;
  metadata?: unknown;
}

function authorize(c: { env: Env; req: { header: (name: string) => string | undefined } }): Response | null {
  const expected = (c.env.INTERNAL_TOKEN ?? '').trim();
  if (!expected) {
    return Response.json({ error: 'internal_token_not_configured' }, { status: 503 });
  }
  const provided = c.req.header('X-Internal-Token') ?? '';
  if (provided !== expected) {
    return Response.json({ error: 'unauthorized' }, { status: 401 });
  }
  return null;
}

function vectorizeOrNull(env: Env): Vectorize | null {
  return env.VECTORIZE ?? null;
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/** 对 Vectorize 瞬时错误做指数退避重试（约 200ms / 400ms）。 */
async function withRetry<T>(fn: () => Promise<T>, attempts = 3): Promise<T> {
  let last: unknown;
  for (let i = 0; i < attempts; i += 1) {
    try {
      return await fn();
    } catch (err) {
      last = err;
      if (i < attempts - 1) await sleep(200 * 2 ** i);
    }
  }
  throw last;
}

function normalizeItem(raw: VectorItem, expectedDim: number): { id: string; values: number[]; metadata: Record<string, string | number | boolean | string[]> } | null {
  const id = typeof raw.id === 'string' ? raw.id.trim() : '';
  if (!id) return null;
  if (!Array.isArray(raw.values) || raw.values.length === 0) return null;
  if (expectedDim > 0 && raw.values.length !== expectedDim) return null;
  const values: number[] = [];
  for (const value of raw.values) {
    if (typeof value !== 'number' || !Number.isFinite(value)) return null;
    values.push(value);
  }
  const metadata: Record<string, string | number | boolean | string[]> = {};
  if (raw.metadata && typeof raw.metadata === 'object' && !Array.isArray(raw.metadata)) {
    for (const [key, value] of Object.entries(raw.metadata as Record<string, unknown>)) {
      if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') {
        metadata[key] = value;
      } else if (Array.isArray(value) && value.every((item) => typeof item === 'string')) {
        metadata[key] = value as string[];
      }
    }
  }
  return { id, values, metadata };
}

function errorMessage(err: unknown): string {
  if (err instanceof Error) return err.message;
  return String(err);
}

internalVectors.post('/upsert', async (c) => {
  const denied = authorize(c);
  if (denied) return denied;
  const index = vectorizeOrNull(c.env);
  if (!index) return c.json({ error: 'vectorize_not_configured' }, 503);

  let body: { items?: unknown } | null = null;
  try {
    body = await c.req.json<{ items?: unknown }>();
  } catch {
    return c.json({ error: 'invalid_json' }, 400);
  }
  if (!body || !Array.isArray(body.items)) {
    return c.json({ error: 'invalid_body', message: 'items 必须是数组' }, 400);
  }
  const items = (body.items as VectorItem[]).slice(0, MAX_UPSERT);
  if (items.length === 0) return c.json({ total: 0, upserted: 0, skipped: 0 });

  // 同一批必须同维度；维度由第一条决定（索引维度由 Cloudflare 侧最终校验）。
  const first = items[0];
  const expectedDim = Array.isArray(first?.values) ? first.values.length : 0;
  const vectors: VectorizeVector[] = [];
  let skipped = 0;
  for (const raw of items) {
    const normalized = normalizeItem(raw, expectedDim);
    if (!normalized) {
      skipped += 1;
      continue;
    }
    vectors.push(normalized);
  }
  if (vectors.length === 0) {
    return c.json({ total: items.length, upserted: 0, skipped, error: 'no_valid_vectors' }, 400);
  }

  try {
    const result = await withRetry(() => index.upsert(vectors));
    const mutationId = (result as { mutationId?: string }).mutationId ?? null;
    return c.json({ total: items.length, upserted: vectors.length, skipped, mutationId });
  } catch (err) {
    return c.json({ error: 'vectorize_upsert_failed', message: errorMessage(err) }, 502);
  }
});

internalVectors.post('/check', async (c) => {
  const denied = authorize(c);
  if (denied) return denied;
  const index = vectorizeOrNull(c.env);
  if (!index) return c.json({ error: 'vectorize_not_configured' }, 503);

  let body: { ids?: unknown } | null = null;
  try {
    body = await c.req.json<{ ids?: unknown }>();
  } catch {
    return c.json({ error: 'invalid_json' }, 400);
  }
  if (!body || !Array.isArray(body.ids)) {
    return c.json({ error: 'invalid_body', message: 'ids 必须是数组' }, 400);
  }
  const ids = (body.ids as unknown[])
    .map((id) => (typeof id === 'string' ? id.trim() : ''))
    .filter(Boolean)
    .slice(0, MAX_CHECK);
  if (ids.length === 0) return c.json({ total: 0, found: [], missing: [] });

  try {
    const vectors = await withRetry(() => index.getByIds(ids));
    const found = vectors.map((vector) => vector.id);
    const foundSet = new Set(found);
    return c.json({ total: ids.length, found, missing: ids.filter((id) => !foundSet.has(id)) });
  } catch (err) {
    return c.json({ error: 'vectorize_check_failed', message: errorMessage(err) }, 502);
  }
});

internalVectors.post('/delete', async (c) => {
  const denied = authorize(c);
  if (denied) return denied;
  const index = vectorizeOrNull(c.env);
  if (!index) return c.json({ error: 'vectorize_not_configured' }, 503);

  let body: { ids?: unknown } | null = null;
  try {
    body = await c.req.json<{ ids?: unknown }>();
  } catch {
    return c.json({ error: 'invalid_json' }, 400);
  }
  if (!body || !Array.isArray(body.ids)) {
    return c.json({ error: 'invalid_body', message: 'ids 必须是数组' }, 400);
  }
  const ids = (body.ids as unknown[])
    .map((id) => (typeof id === 'string' ? id.trim() : ''))
    .filter(Boolean)
    .slice(0, MAX_UPSERT);
  if (ids.length === 0) return c.json({ total: 0, deleted: 0 });

  try {
    const result = await withRetry(() => index.deleteByIds(ids));
    const mutationId = (result as { mutationId?: string }).mutationId ?? null;
    return c.json({ total: ids.length, deleted: ids.length, mutationId });
  } catch (err) {
    return c.json({ error: 'vectorize_delete_failed', message: errorMessage(err) }, 502);
  }
});

internalVectors.get('/stats', async (c) => {
  const denied = authorize(c);
  if (denied) return denied;
  const index = vectorizeOrNull(c.env);
  if (!index) return c.json({ error: 'vectorize_not_configured' }, 503);

  try {
    const info = await withRetry(() => index.describe());
    return c.json({
      vectorCount: info.vectorCount,
      dimensions: info.dimensions,
      processedUpToDatetime: info.processedUpToDatetime,
      processedUpToMutation: info.processedUpToMutation,
    });
  } catch (err) {
    return c.json({ error: 'vectorize_stats_failed', message: errorMessage(err) }, 502);
  }
});

export default internalVectors;
