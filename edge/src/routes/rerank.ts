/**
 * 精排路由（REQ-202610-0966 / M7-07）
 *
 * POST /api/rerank/preview  精排预览（不落库）
 * POST /api/rerank/apply    精排并写回 D1
 *
 * 链路：
 *   1. 读取当前用户活跃推荐（new / qualified / filtered）；
 *   2. 优先把候选发给 VPS `POST /api/recommend/rerank/preview`（六路信号 + MMR）；
 *   3. VPS 不可达时用 `localRerank` 做本地启发式精排（mode=local）；
 *   4. apply 时把精排分 / 名次 / 明细写回 recommendations。
 */
import { Hono } from 'hono';
import type { Env, RecommendationRow, RerankDetail, Variables } from '../types';
import { all, run } from '../db';
import {
  candidateFromRow,
  localRerank,
  normalizeRerankWeights,
  toRerankDetail,
  type RerankCandidateInput,
  type RerankResult,
  type RerankWeights,
} from '../rerank/helpers';

const rerank = new Hono<{ Bindings: Env; Variables: Variables }>();

const DEFAULT_TOP_K = 20;
const MAX_TOP_K = 100;
const DEFAULT_POOL_SIZE = 100;
const MAX_POOL_SIZE = 500;

interface RerankBody {
  topK?: unknown;
  poolSize?: unknown;
  mmrLambda?: unknown;
  weights?: unknown;
}

function intInRange(value: unknown, fallback: number, min: number, max: number): number {
  const num = typeof value === 'number' ? value : Number(value);
  if (!Number.isFinite(num)) return fallback;
  return Math.min(max, Math.max(min, Math.trunc(num)));
}

function floatInRange(value: unknown, fallback: number, min: number, max: number): number {
  const num = typeof value === 'number' ? value : Number(value);
  if (!Number.isFinite(num)) return fallback;
  return Math.min(max, Math.max(min, num));
}

function parseWeights(raw: unknown): Partial<RerankWeights> | null {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return null;
  const source = raw as Record<string, unknown>;
  const result: Partial<RerankWeights> = {};
  for (const key of ['relevance', 'affinity', 'freshness', 'momentum', 'popularity', 'health'] as const) {
    const value = source[key];
    if (typeof value === 'number' && Number.isFinite(value)) {
      result[key] = Math.max(0, value);
    }
  }
  return Object.keys(result).length > 0 ? result : null;
}

async function readBody(c: { req: { json: () => Promise<unknown> } }): Promise<RerankBody | null> {
  try {
    const body = await c.req.json();
    return body && typeof body === 'object' && !Array.isArray(body) ? (body as RerankBody) : null;
  } catch {
    return null;
  }
}

function emptyResult(weights: RerankWeights, mmrLambda: number): RerankResult {
  return {
    items: [],
    metrics: {
      total: 0,
      selected: 0,
      movedUp: 0,
      movedDown: 0,
      unchanged: 0,
      avgRankShift: 0,
      diversityBefore: 0,
      diversityAfter: 0,
      languageCoverage: 0,
    },
    weights,
    mmrLambda,
  };
}

function normalizeItems(value: unknown): RerankResult['items'] | null {
  if (!Array.isArray(value)) return null;
  const items = value.filter(
    (item): item is RerankResult['items'][number] =>
      Boolean(item) && typeof item === 'object' && typeof (item as { repoId?: unknown }).repoId === 'string'
  );
  return items.length === value.length ? items : null;
}

/** 调 VPS 无状态精排；失败 / 返回异常时返回 null。 */
async function callVpsRerank(
  env: Env,
  candidates: RerankCandidateInput[],
  options: { topK: number; mmrLambda: number; weights: Partial<RerankWeights> | null }
): Promise<{ result: RerankResult; mode: 'vps' } | null> {
  const base = env.VPS_NODE_URL?.trim();
  if (!base) return null;
  try {
    const res = await fetch(`${base.replace(/\/+$/, '')}/api/recommend/rerank/preview`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Internal-Token': env.INTERNAL_TOKEN ?? '',
      },
      body: JSON.stringify({
        items: candidates,
        topK: options.topK,
        mmrLambda: options.mmrLambda,
        weights: options.weights ?? undefined,
      }),
    });
    if (!res.ok) return null;
    const payload = (await res.json()) as {
      status?: unknown;
      items?: unknown;
      metrics?: unknown;
      weights?: unknown;
      mmrLambda?: unknown;
    };
    const items = normalizeItems(payload.items);
    if (!items || !payload.metrics || typeof payload.metrics !== 'object') return null;
    return {
      result: {
        items,
        metrics: payload.metrics as RerankResult['metrics'],
        weights: normalizeRerankWeights(payload.weights as Partial<RerankWeights> | null),
        mmrLambda: floatInRange(payload.mmrLambda, options.mmrLambda, 0, 1),
      },
      mode: 'vps',
    };
  } catch (err) {
    console.error('vps /api/recommend/rerank/preview failed:', err);
    return null;
  }
}

async function loadActiveRows(env: Env, userId: string, poolSize: number): Promise<RecommendationRow[]> {
  return all<RecommendationRow>(
    env.DB,
    `SELECT * FROM recommendations
      WHERE (user_id = ? OR user_id IS NULL)
        AND status NOT IN ('saved', 'dismissed', 'expired')
      ORDER BY COALESCE(NULLIF(rerank_score, 0), score) DESC, score DESC, created_at DESC
      LIMIT ?`,
    [userId, poolSize]
  );
}

async function computeRerank(
  env: Env,
  userId: string,
  body: RerankBody | null
): Promise<{ result: RerankResult; mode: 'vps' | 'local' }> {
  const topK = intInRange(body?.topK, DEFAULT_TOP_K, 1, MAX_TOP_K);
  const poolSize = intInRange(body?.poolSize, DEFAULT_POOL_SIZE, topK, MAX_POOL_SIZE);
  const mmrLambda = floatInRange(body?.mmrLambda, 0.75, 0, 1);
  const weights = parseWeights(body?.weights);

  const rows = await loadActiveRows(env, userId, poolSize);
  const candidates = rows.map(candidateFromRow).filter((item) => item.repoId);
  if (candidates.length === 0) {
    return { result: emptyResult(normalizeRerankWeights(weights), mmrLambda), mode: 'local' };
  }

  const remote = await callVpsRerank(env, candidates, { topK, mmrLambda, weights });
  if (remote) return remote;
  return { result: localRerank(candidates, { topK, mmrLambda, weights }), mode: 'local' };
}

rerank.post('/preview', async (c) => {
  const user = c.get('user');
  if (!user) return c.json({ error: 'unauthorized' }, 401);

  const body = await readBody(c);
  const { result, mode } = await computeRerank(c.env, user.id, body);
  return c.json({
    status: result.items.length > 0 ? 'ok' : 'empty',
    mode,
    userId: user.id,
    generatedAt: new Date().toISOString(),
    weights: result.weights,
    mmrLambda: result.mmrLambda,
    metrics: result.metrics,
    items: result.items,
    applied: false,
  });
});

rerank.post('/apply', async (c) => {
  const user = c.get('user');
  if (!user) return c.json({ error: 'unauthorized' }, 401);

  const body = await readBody(c);
  const { result, mode } = await computeRerank(c.env, user.id, body);
  if (result.items.length === 0) {
    return c.json({
      status: 'empty',
      mode,
      userId: user.id,
      generatedAt: new Date().toISOString(),
      weights: result.weights,
      mmrLambda: result.mmrLambda,
      metrics: result.metrics,
      items: [],
      applied: false,
    });
  }

  const rows = await loadActiveRows(c.env, user.id, MAX_POOL_SIZE);
  const byRepo = new Map(rows.map((row) => [row.repo_id ?? '', row]));
  let applied = 0;
  for (const item of result.items) {
    const row = byRepo.get(item.repoId);
    if (!row) continue;
    const detail: RerankDetail = toRerankDetail(item);
    await run(
      c.env.DB,
      `UPDATE recommendations
          SET score = ?, base_score = ?, rerank_score = ?, rerank_rank = ?,
              rerank_detail = ?, reranked_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
        WHERE id = ? AND (user_id = ? OR user_id IS NULL)`,
      [
        item.rerankScore,
        item.baseScore,
        item.rerankScore,
        item.rankAfter,
        JSON.stringify(detail),
        row.id,
        user.id,
      ]
    );
    applied += 1;
  }

  return c.json({
    status: 'ok',
    mode,
    userId: user.id,
    generatedAt: new Date().toISOString(),
    weights: result.weights,
    mmrLambda: result.mmrLambda,
    metrics: result.metrics,
    items: result.items,
    applied: applied > 0,
  });
});

export default rerank;
