/**
 * 内部 Vectorize 索引接口（VPS → edge）。
 *
 * 仅允许携带 `X-Internal-Token` 的服务端调用；未配置令牌时返回 503（默认关闭）。
 * VPS 负责生成向量与同步编排，本路由只做参数校验与 Vectorize 绑定调用。
 */
import { Hono } from 'hono';
import type { Env, Variables } from '../types';

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
