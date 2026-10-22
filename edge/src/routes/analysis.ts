/**
 * 依赖分析路由（M6-07 / REQ-202610-0954）
 *
 * GET  /api/analysis/dependencies?top=20
 * POST /api/analysis/dependencies/refresh
 *
 * 链路：
 *   1. 按当前用户从 D1 取仓库 id / 语言；
 *   2. GET 代理到 VPS `/api/analysis/dependencies`（依赖明细只存在 VPS 本地库）；
 *   3. VPS 不可达 → `buildLocalOverview` 用 D1 语言数据给出本地概览（mode=local）。
 *
 * 权限：两个接口都要求登录，且只传当前用户的仓库 id，避免越权读取他人依赖。
 */
import { Hono } from 'hono';
import type { Env, RepoRow, Variables } from '../types';
import { all } from '../db';
import {
  buildLocalOverview,
  clampAnalysisTop,
  parseRepoIds,
  type DependencyAnalysisPayload,
  type RepoLanguageRow,
} from '../dependencies/helpers';

const analysis = new Hono<{ Bindings: Env; Variables: Variables }>();

interface VpsRefreshResponse {
  status: string;
  scanned: number;
  ok: number;
  noManifest: number;
  failed: number;
  dependencies: number;
  repos: Array<Record<string, unknown>>;
}

async function userRepos(env: Env, userId: string): Promise<RepoLanguageRow[]> {
  return all<RepoRow & RepoLanguageRow>(
    env.DB,
    `SELECT id, name, language FROM my_repositories WHERE user_id = ? ORDER BY stars DESC, id ASC`,
    [userId]
  );
}

async function getVpsAnalysis(
  env: Env,
  ids: string[],
  top: number
): Promise<DependencyAnalysisPayload | null> {
  const base = env.VPS_NODE_URL?.trim();
  if (!base) return null;
  const url = new URL(`${base.replace(/\/+$/, '')}/api/analysis/dependencies`);
  url.searchParams.set('top', String(top));
  if (ids.length > 0) url.searchParams.set('repoIds', ids.join(','));
  try {
    const res = await fetch(url.toString(), {
      headers: { 'X-Internal-Token': env.INTERNAL_TOKEN ?? '' },
    });
    if (!res.ok) return null;
    return (await res.json()) as DependencyAnalysisPayload;
  } catch (err) {
    console.error('vps /api/analysis/dependencies failed:', err);
    return null;
  }
}

async function postVpsRefresh(env: Env, ids: string[]): Promise<VpsRefreshResponse | null> {
  const base = env.VPS_NODE_URL?.trim();
  if (!base) return null;
  try {
    const res = await fetch(`${base.replace(/\/+$/, '')}/api/analysis/dependencies/refresh`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Internal-Token': env.INTERNAL_TOKEN ?? '',
      },
      body: JSON.stringify({ repoIds: ids, force: true, limit: ids.length }),
    });
    if (!res.ok) return null;
    return (await res.json()) as VpsRefreshResponse;
  } catch (err) {
    console.error('vps /api/analysis/dependencies/refresh failed:', err);
    return null;
  }
}

analysis.get('/dependencies', async (c) => {
  const user = c.get('user');
  if (!user) return c.json({ error: 'unauthorized' }, 401);

  const rows = await userRepos(c.env, user.id);
  const top = clampAnalysisTop(c.req.query('top'));
  const ids = rows
    .map((row) => row.id ?? '')
    .filter((id) => id.length > 0)
    .slice(0, 100);

  const payload = ids.length > 0 ? await getVpsAnalysis(c.env, ids, top) : null;
  if (payload) {
    return c.json({ ...payload, mode: 'vps' as const });
  }
  return c.json({ ...buildLocalOverview(rows), mode: 'local' as const });
});

analysis.post('/dependencies/refresh', async (c) => {
  const user = c.get('user');
  if (!user) return c.json({ error: 'unauthorized' }, 401);

  const rows = await userRepos(c.env, user.id);
  const ids = parseRepoIds(
    rows
      .map((row) => row.id ?? '')
      .filter(Boolean)
      .join(',')
  );
  if (ids.length === 0) {
    return c.json({
      status: 'empty',
      mode: 'local' as const,
      message: '当前账号还没有可分析的仓库',
      scanned: 0,
      ok: 0,
      noManifest: 0,
      failed: 0,
      dependencies: 0,
      repos: [],
    });
  }

  const result = await postVpsRefresh(c.env, ids);
  if (!result) {
    return c.json({
      status: 'unavailable',
      mode: 'local' as const,
      message: 'VPS 节点不可达，稍后再试',
      scanned: 0,
      ok: 0,
      noManifest: 0,
      failed: 0,
      dependencies: 0,
      repos: [],
    });
  }
  return c.json({ ...result, mode: 'vps' as const });
});

export default analysis;
