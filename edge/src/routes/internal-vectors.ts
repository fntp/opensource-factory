/**
<<<<<<< HEAD
 * Vectorize 索引内部路由（VPS → Cloudflare Vectorize）
 *
 * - POST /api/internal/vectors/upsert：批量 upsert（≤1000 条）
 * - POST /api/internal/vectors/check：按 id 批量查询存在性（≤100 条）
 * - POST /api/internal/vectors/delete：按 id 批量删除（≤1000 条）
 * - GET  /api/internal/vectors/stats：索引统计（describe）
 *
 * 仅内部调用：校验 X-Internal-Token；未配置 INTERNAL_TOKEN 时返回 503（默认关闭）。
 * VPS 不持有 Cloudflare 凭据，所有 Vectorize 操作都通过本路由的绑定完成。
=======
 * 内部 Vectorize 索引接口（VPS → edge）。
 *
 * 仅允许携带 `X-Internal-Token` 的服务端调用；未配置令牌时返回 503（默认关闭）。
 * VPS 负责生成向量与同步编排，本路由只做参数校验与 Vectorize 绑定调用。
>>>>>>> feat/req-202610-0922-semantic-search
 */
import { Hono } from 'hono';
import type { Env, Variables } from '../types';

<<<<<<< HEAD
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
=======
type MetadataValue = string | number | boolean;
type VectorInput = {
  id: string;
  values: number[];
  metadata?: Record<string, MetadataValue>;
};

const router = new Hono<{ Bindings: Env; Variables: Variables }>();

const MAX_UPSERT = 1000;
const MAX_CHECK = 100;
const MAX_DELETE = 1000;
const MAX_METADATA_KEYS = 10;

function isMetadata(value: unknown): value is Record<string, MetadataValue> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false;
  const entries = Object.entries(value as Record<string, unknown>);
  if (entries.length > MAX_METADATA_KEYS) return false;
  return entries.every(
    ([, item]) =>
      typeof item === 'string' || typeof item === 'number' || typeof item === 'boolean'
  );
}

function isVectorInput(value: unknown): value is VectorInput {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false;
  const item = value as Record<string, unknown>;
  if (typeof item.id !== 'string' || item.id.length === 0 || item.id.length > 64) return false;
  if (!Array.isArray(item.values) || item.values.length === 0) return false;
  if (!item.values.every((v) => typeof v === 'number' && Number.isFinite(v))) return false;
  if (item.metadata !== undefined && !isMetadata(item.metadata)) return false;
  return true;
}

async function readBody(c: { req: { json: () => Promise<unknown> } }): Promise<unknown> {
  try {
    return await c.req.json();
  } catch {
    return null;
  }
}

function vectorizeError(err: unknown): { error: string; message: string } {
  console.error('vectorize error:', err);
  const message = err instanceof Error ? err.message : String(err);
  return { error: 'vectorize_error', message: message.slice(0, 200) };
}

// 内部令牌鉴权：未配置 → 503（与一致性快照接口口径一致）；不匹配 → 401
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
  const index = c.env.VECTORIZE;
  if (!index) return c.json({ error: 'vectorize_binding_missing' }, 503);

  const body = (await readBody(c)) as { vectors?: unknown } | null;
  if (!body || !Array.isArray(body.vectors)) {
    return c.json({ error: 'invalid_body', message: 'vectors 必须是数组' }, 400);
  }
  if (body.vectors.length === 0 || body.vectors.length > MAX_UPSERT) {
    return c.json({ error: 'invalid_batch', message: `单批 1~${MAX_UPSERT} 条` }, 400);
  }
  const vectors = body.vectors.filter(isVectorInput);
  if (vectors.length !== body.vectors.length) {
    return c.json({ error: 'invalid_vectors', message: '向量格式不合法' }, 400);
  }

  try {
    const result = await index.upsert(vectors);
    return c.json({ ok: true, count: result.count ?? vectors.length });
  } catch (err) {
    return c.json(vectorizeError(err), 502);
  }
});

router.post('/check', async (c) => {
  const index = c.env.VECTORIZE;
  if (!index) return c.json({ error: 'vectorize_binding_missing' }, 503);

  const body = (await readBody(c)) as { ids?: unknown } | null;
  if (!body || !Array.isArray(body.ids) || body.ids.length === 0) {
    return c.json({ error: 'invalid_body', message: 'ids 必须是非空数组' }, 400);
  }
  if (body.ids.length > MAX_CHECK) {
    return c.json({ error: 'invalid_batch', message: `单次最多 ${MAX_CHECK} 个 id` }, 400);
  }
  const ids = body.ids.filter((id): id is string => typeof id === 'string' && id.length > 0);
  if (ids.length !== body.ids.length) {
    return c.json({ error: 'invalid_ids', message: 'id 必须是非空字符串' }, 400);
  }

  try {
    const found = await index.getByIds(ids);
    return c.json({
      ok: true,
      vectors: found.map((item) => ({ id: item.id, metadata: item.metadata ?? {} })),
    });
  } catch (err) {
    return c.json(vectorizeError(err), 502);
  }
});

router.post('/delete', async (c) => {
  const index = c.env.VECTORIZE;
  if (!index) return c.json({ error: 'vectorize_binding_missing' }, 503);

  const body = (await readBody(c)) as { ids?: unknown } | null;
  if (!body || !Array.isArray(body.ids) || body.ids.length === 0) {
    return c.json({ error: 'invalid_body', message: 'ids 必须是非空数组' }, 400);
  }
  if (body.ids.length > MAX_DELETE) {
    return c.json({ error: 'invalid_batch', message: `单次最多 ${MAX_DELETE} 个 id` }, 400);
  }
  const ids = body.ids.filter((id): id is string => typeof id === 'string' && id.length > 0);
  if (ids.length !== body.ids.length) {
    return c.json({ error: 'invalid_ids', message: 'id 必须是非空字符串' }, 400);
  }

  try {
    const result = await index.deleteByIds(ids);
    return c.json({ ok: true, count: result.count ?? ids.length });
  } catch (err) {
    return c.json(vectorizeError(err), 502);
  }
});

router.get('/stats', async (c) => {
  const index = c.env.VECTORIZE;
  if (!index) return c.json({ error: 'vectorize_binding_missing' }, 503);

  try {
    const info = (await index.describe()) as unknown as Record<string, unknown>;
    return c.json({
      ok: true,
      vectorCount: Number(info.vectorCount ?? 0),
      dimensions: info.dimensions ?? null,
      processedUpToMutation: info.processedUpToMutation ?? null,
      processedUpToDatetime: info.processedUpToDatetime ?? null,
    });
  } catch (err) {
    return c.json(vectorizeError(err), 502);
  }
});

router.get('/list', async (c) => {
  const index = c.env.VECTORIZE;
  if (!index) return c.json({ error: 'vectorize_binding_missing' }, 503);

  type ListResult = {
    vectors?: Array<{ id?: unknown; metadata?: unknown }>;
    cursor?: string | null;
    isTruncated?: boolean;
  };
  const maybeList = (
    index as unknown as {
      list?: (options: { count?: number; cursor?: string }) => Promise<ListResult>;
    }
  ).list;
  if (typeof maybeList !== 'function') {
    return c.json({ error: 'vectorize_list_unsupported' }, 501);
  }

  const rawCount = Number.parseInt(c.req.query('count') ?? '1000', 10);
  const count = Number.isFinite(rawCount) ? Math.min(1000, Math.max(1, rawCount)) : 1000;
  const cursor = c.req.query('cursor') || undefined;

  try {
    const result = await maybeList.call(index, { count, cursor });
    const vectors = (result.vectors ?? [])
      .map((item) => ({ id: String(item.id ?? ''), metadata: item.metadata ?? {} }))
      .filter((item) => item.id.length > 0);
    return c.json({
      ok: true,
      vectors,
      cursor: result.cursor ?? null,
      isTruncated: Boolean(result.isTruncated),
    });
  } catch (err) {
    return c.json(vectorizeError(err), 502);
  }
});

export default router;
>>>>>>> feat/req-202610-0922-semantic-search
