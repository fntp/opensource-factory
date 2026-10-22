/**
 * 相似项目推荐路由（M6-02「看了又看」）
 *
 * GET /api/similar?source=my|trending&repoId=owner/name&topK=8&scope=all
 *
 * 链路：
 *   1. VPS `POST /api/search/similar`：以种子仓库向量做本地余弦近邻（mode=local）
 *   2. VPS 不可达 / 种子未向量化 / 无命中 → D1 同语言 + 技术栈兜底（mode=keyword）
 *   3. edge 按当前用户水合 `my` 行（trending 为全局数据）
 *
 * 权限：`source=my` 必须登录，且种子仓库必须属于当前用户。
 */
import { Hono } from 'hono';
import type { Env, RepoRow, SearchResultItem, SimilarResponse, TrendingRow, Variables } from '../types';
import { all, first } from '../db';
import { hydrateHits, toSearchItem } from '../search/items';
import { parseTechStack } from '../trending/detail';
import {
  clampSimilarTopK,
  fallbackReason,
  fallbackScore,
  normalizeSimilarScope,
  normalizeSimilarSource,
  parseBoolean,
  sharedTechStack,
} from '../similar/helpers';

const similar = new Hono<{ Bindings: Env; Variables: Variables }>();

interface VpsHit {
  source?: string;
  repoId?: string;
  score?: number;
}

interface VpsSimilarResponse {
  items?: VpsHit[];
}

async function postVps<T>(env: Env, path: string, body: unknown): Promise<T | null> {
  const base = env.VPS_NODE_URL?.trim();
  if (!base) return null;
  try {
    const res = await fetch(`${base.replace(/\/+$/, '')}${path}`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Internal-Token': env.INTERNAL_TOKEN ?? '',
      },
      body: JSON.stringify(body),
    });
    if (!res.ok) return null;
    return (await res.json()) as T;
  } catch (err) {
    console.error(`vps ${path} failed:`, err);
    return null;
  }
}

function validHits(items: VpsHit[] | undefined): Array<{ source: string; repoId: string; score: number }> {
  return (items ?? [])
    .filter(
      (item): item is { source: string; repoId: string; score: number } =>
        (item.source === 'my' || item.source === 'trending') &&
        typeof item.repoId === 'string' &&
        typeof item.score === 'number'
    )
    .map((item) => ({ source: item.source, repoId: item.repoId, score: item.score }));
}

interface Candidate {
  row: RepoRow | TrendingRow;
  source: 'my' | 'trending';
}

/** 关键词兜底：同语言 / 共享技术栈，按规则分排序；明确不是语义相似度。 */
async function keywordFallback(
  env: Env,
  user: Variables['user'],
  seed: RepoRow | TrendingRow,
  seedSource: 'my' | 'trending',
  scope: 'my' | 'trending' | 'all',
  topK: number,
  excludeSaved: boolean
): Promise<SearchResultItem[]> {
  const seedLanguage = seed.language ?? '';
  const seedTech = seedSource === 'trending' ? parseTechStack((seed as TrendingRow).tech_stack) : [];
  const candidates: Candidate[] = [];

  if (scope === 'all' || scope === 'trending') {
    const rows = await all<TrendingRow>(
      env.DB,
      `SELECT * FROM trending_repositories WHERE id != ? ORDER BY stars_today DESC LIMIT ?`,
      [seed.id, topK * 6]
    );
    for (const row of rows) candidates.push({ row, source: 'trending' });
  }
  if (scope === 'all' || scope === 'my') {
    if (user && !excludeSaved) {
      const rows = await all<RepoRow>(
        env.DB,
        `SELECT * FROM my_repositories WHERE user_id = ? AND id != ? ORDER BY stars DESC LIMIT ?`,
        [user.id, seed.id, topK * 6]
      );
      for (const row of rows) candidates.push({ row, source: 'my' });
    }
  }

  const scored = candidates
    .map((candidate) => {
      const candidateLanguage = candidate.row.language ?? '';
      const candidateTech =
        candidate.source === 'trending'
          ? parseTechStack((candidate.row as TrendingRow).tech_stack)
          : [];
      const score = fallbackScore(seedLanguage, seedTech, candidateLanguage, candidateTech);
      const shared = sharedTechStack(seedTech, candidateTech);
      return { ...candidate, score, shared };
    })
    .filter((candidate) => candidate.score > 0)
    .sort((a, b) => b.score - a.score)
    .slice(0, topK);

  return scored.map((candidate) => {
    const item = toSearchItem(candidate.row, candidate.source, candidate.score);
    item.reason = fallbackReason(seed.name, item.language, candidate.shared);
    return item;
  });
}

similar.get('/', async (c) => {
  const started = Date.now();
  const user = c.get('user');
  const source = normalizeSimilarSource(c.req.query('source'));
  if (!source) {
    return c.json({ error: 'invalid_source', message: 'source 仅支持 my / trending' }, 400);
  }
  if (source === 'my' && !user) {
    return c.json({ error: 'unauthorized' }, 401);
  }
  const repoId = (c.req.query('repoId') ?? '').trim();
  if (!repoId || repoId.length > 255) {
    return c.json({ error: 'invalid_repo_id', message: 'repoId 长度需为 1~255' }, 400);
  }
  const scope = normalizeSimilarScope(c.req.query('scope'));
  if (!scope) {
    return c.json({ error: 'invalid_scope', message: 'scope 仅支持 my / trending / all' }, 400);
  }
  const topK = clampSimilarTopK(c.req.query('topK'));
  const excludeSaved = parseBoolean(c.req.query('excludeSaved'), false);
  const rawMinScore = c.req.query('minScore');
  let minScore: number | undefined;
  if (rawMinScore !== undefined && rawMinScore !== '') {
    minScore = Number(rawMinScore);
    if (!Number.isFinite(minScore) || minScore < -1 || minScore > 1) {
      return c.json({ error: 'invalid_min_score', message: 'minScore 需在 -1~1' }, 400);
    }
  }

  let seed: RepoRow | TrendingRow | null;
  if (source === 'my') {
    seed = await first<RepoRow>(
      c.env.DB,
      `SELECT * FROM my_repositories WHERE id = ? AND user_id = ?`,
      [repoId, user!.id]
    );
  } else {
    seed = await first<TrendingRow>(c.env.DB, `SELECT * FROM trending_repositories WHERE id = ?`, [
      repoId,
    ]);
  }
  if (!seed) {
    return c.json({ error: 'seed_not_found', message: '种子仓库不存在或无权访问' }, 404);
  }

  // 1) VPS 本地向量近邻
  const local = await postVps<VpsSimilarResponse>(c.env, '/api/search/similar', {
    source,
    repoId,
    topK,
    scope,
    ...(minScore === undefined ? {} : { minScore }),
    excludeSaved,
  });
  const hits = validHits(local?.items);
  if (hits.length > 0) {
    const items = await hydrateHits(c.env, user?.id ?? '', hits, topK, seed.name);
    if (items.length > 0) {
      return c.json({
        source,
        repoId,
        mode: 'local',
        count: items.length,
        tookMs: Date.now() - started,
        items,
      } satisfies SimilarResponse);
    }
  }

  // 2) D1 关键词兜底
  const items = await keywordFallback(c.env, user, seed, source, scope, topK, excludeSaved);
  return c.json({
    source,
    repoId,
    mode: 'keyword',
    count: items.length,
    tookMs: Date.now() - started,
    items,
  } satisfies SimilarResponse);
});

export default similar;
