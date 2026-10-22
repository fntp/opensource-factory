/**
 * 重复 / 相似项目检测路由（M6-03）。
 *
 * POST   /api/duplicates/scan          扫描当前用户的收藏库 / 热榜重复项
 * POST   /api/duplicates/dismiss       忽略一个重复簇（按用户存 D1）
 * GET    /api/duplicates/dismissed     已忽略列表
 * DELETE /api/duplicates/dismiss/:id   恢复（取消忽略）
 *
 * 链路：
 *   1. D1 读取当前用户收藏 + 热榜（VPS 只拿到 myRepoIds，不接触用户身份）
 *   2. 优先调 VPS `POST /api/duplicates/scan`（名称 / 简介 / 向量复核）
 *   3. VPS 不可达时用 edge 本地规则兜底；VPS 可用时本地规则补扫收藏库
 *   4. 按 D1 行水合展示字段、二次校验 my 归属，再过滤用户已忽略的簇
 */
import { Hono } from 'hono';
import type {
  DuplicateCluster,
  DuplicateDismissal,
  DuplicateFieldSuggestion,
  DuplicateKind,
  DuplicateMember,
  DuplicateScanResponse,
  DuplicateScope,
  DuplicateSignals,
  DuplicateSource,
  DuplicateThresholds,
  Env,
  RepoRow,
  TrendingRow,
  Variables,
} from '../types';
import { all, run } from '../db';
import { parseTechStack } from '../trending/detail';
import {
  clusterSignature,
  detectNameDuplicates,
  mergeDuplicateClusters,
  normalizeDuplicateScope,
  type DuplicateRepoInput,
} from '../duplicates/helpers';

const duplicates = new Hono<{ Bindings: Env; Variables: Variables }>();

const MAX_REPOS = 500;
const MAX_CLUSTERS = 50;
const LOCAL_MAX_REPOS = 300;
const DEFAULT_THRESHOLDS: DuplicateThresholds = {
  minScore: 0.7,
  nameThreshold: 0.86,
  descriptionThreshold: 0.75,
  vectorThreshold: 0.88,
  maxRepos: MAX_REPOS,
  maxClusters: MAX_CLUSTERS,
};

type RepoRowLike = RepoRow | TrendingRow;

function clampNumber(value: unknown, min: number, max: number, fallback: number): number {
  const num = typeof value === 'number' ? value : Number(value);
  if (!Number.isFinite(num)) return fallback;
  return Math.min(max, Math.max(min, num));
}

function rowKey(source: DuplicateSource, repoId: string): string {
  return `${source}:${repoId}`;
}

function rowToInput(row: RepoRowLike, source: DuplicateSource): DuplicateRepoInput {
  return {
    source,
    repoId: row.id,
    platform: row.platform,
    name: row.name,
    description: row.description,
    htmlUrl: row.html_url,
    stars: row.stars,
    language: row.language,
    readmeSummary: row.readme_summary,
    categoryId: 'category_id' in row ? row.category_id : null,
    techStack: 'tech_stack' in row ? parseTechStack(row.tech_stack) : [],
  };
}

function rowToMember(
  row: RepoRowLike,
  source: DuplicateSource,
  signals: DuplicateSignals,
  role: 'canonical' | 'merge',
  fallbackTech: string[] = []
): DuplicateMember {
  const techStack =
    'tech_stack' in row ? parseTechStack(row.tech_stack) : fallbackTech;
  const owner = row.owner ?? row.id.split('/')[0] ?? '';
  return {
    source,
    repoId: row.id,
    fullName: owner ? `${owner}/${row.name}` : row.id,
    name: row.name,
    description: row.description ?? row.readme_summary ?? '',
    language: row.language ?? '',
    stars: row.stars ?? 0,
    url: row.html_url,
    platform: row.platform ?? 'github',
    categoryId: 'category_id' in row ? (row.category_id ?? '') : '',
    readmeSummary: row.readme_summary ?? '',
    techStack,
    role,
    signals,
  };
}

function normalizeSignals(value: unknown): DuplicateSignals {
  const source = (value ?? {}) as Partial<DuplicateSignals>;
  return {
    nameSimilarity: clampNumber(source.nameSimilarity, 0, 1, 0),
    descriptionSimilarity: clampNumber(source.descriptionSimilarity, 0, 1, 0),
    vectorSimilarity:
      source.vectorSimilarity === null || source.vectorSimilarity === undefined
        ? null
        : clampNumber(source.vectorSimilarity, 0, 1, 0),
    exactKey: source.exactKey === true,
  };
}

function normalizeKind(value: unknown): DuplicateKind {
  return value === 'exact' || value === 'name' || value === 'semantic' || value === 'mixed'
    ? value
    : 'name';
}

interface VpsScanPayload {
  scanId?: unknown;
  scanned?: unknown;
  compared?: unknown;
  thresholds?: unknown;
  clusters?: unknown;
}

interface VpsMember {
  source?: unknown;
  repoId?: unknown;
  techStack?: unknown;
  signals?: unknown;
}

interface VpsCluster {
  kind?: unknown;
  confidence?: unknown;
  reasons?: unknown;
  members?: unknown;
  suggestion?: unknown;
}

function normalizeVpsClusters(
  payload: VpsScanPayload,
  ownedMyIds: Set<string>,
  rows: Map<string, RepoRowLike>
): DuplicateCluster[] {
  if (!Array.isArray(payload.clusters)) return [];
  const result: DuplicateCluster[] = [];
  for (const rawCluster of payload.clusters) {
    if (!rawCluster || typeof rawCluster !== 'object') continue;
    const cluster = rawCluster as VpsCluster;
    if (!Array.isArray(cluster.members)) continue;
    const members: DuplicateMember[] = [];
    for (const rawMember of cluster.members) {
      if (!rawMember || typeof rawMember !== 'object') continue;
      const member = rawMember as VpsMember;
      if (member.source !== 'my' && member.source !== 'trending') continue;
      if (typeof member.repoId !== 'string' || !member.repoId) continue;
      const source: DuplicateSource = member.source;
      // 二次校验：VPS 返回的 my 行必须属于当前用户；不在 D1 的 my 行直接丢弃。
      if (source === 'my' && !ownedMyIds.has(member.repoId)) continue;
      const row = rows.get(rowKey(source, member.repoId));
      if (!row) continue;
      const tech = Array.isArray(member.techStack)
        ? member.techStack.filter((item): item is string => typeof item === 'string')
        : [];
      members.push(rowToMember(row, source, normalizeSignals(member.signals), 'merge', tech));
    }
    if (members.length < 2) continue;

    const suggestion = (cluster.suggestion ?? {}) as {
      action?: unknown;
      keep?: { source?: unknown; repoId?: unknown };
      fields?: unknown;
      notes?: unknown;
    };
    const keepKey =
      suggestion.keep &&
      (suggestion.keep.source === 'my' || suggestion.keep.source === 'trending') &&
      typeof suggestion.keep.repoId === 'string'
        ? rowKey(suggestion.keep.source, suggestion.keep.repoId)
        : '';
    const canonical =
      members.find((member) => rowKey(member.source, member.repoId) === keepKey) ??
      members.find((member) => member.source === 'my') ??
      members[0]!;
    const withRoles = members.map((member) => ({
      ...member,
      role:
        rowKey(member.source, member.repoId) === rowKey(canonical.source, canonical.repoId)
          ? ('canonical' as const)
          : ('merge' as const),
    }));
    const memberKeys = new Set(withRoles.map((member) => rowKey(member.source, member.repoId)));
    const fields: DuplicateFieldSuggestion[] = [];
    if (Array.isArray(suggestion.fields)) {
      for (const item of suggestion.fields) {
        if (!item || typeof item !== 'object') continue;
        const field = item as DuplicateFieldSuggestion;
        if (
          typeof field.field === 'string' &&
          field.from &&
          (field.from.source === 'my' || field.from.source === 'trending') &&
          typeof field.from.repoId === 'string' &&
          memberKeys.has(rowKey(field.from.source, field.from.repoId))
        ) {
          fields.push({
            field: field.field,
            value: field.value,
            from: field.from,
            reason: typeof field.reason === 'string' ? field.reason : '',
          });
        }
      }
    }

    result.push({
      id: clusterSignature(withRoles),
      kind: normalizeKind(cluster.kind),
      confidence: clampNumber(cluster.confidence, 0, 1, 0),
      reasons: Array.isArray(cluster.reasons)
        ? cluster.reasons.filter((reason): reason is string => typeof reason === 'string')
        : [],
      members: withRoles,
      suggestion: {
        action: suggestion.action === 'review' ? 'review' : 'merge',
        keep: { source: canonical.source, repoId: canonical.repoId },
        mergeTargets: withRoles
          .filter((member) => member !== canonical)
          .map((member) => ({ source: member.source, repoId: member.repoId })),
        fields,
        notes: typeof suggestion.notes === 'string' ? suggestion.notes : '',
      },
    });
  }
  return result;
}

async function postVpsScan(
  env: Env,
  body: unknown
): Promise<VpsScanPayload | null> {
  const base = env.VPS_NODE_URL?.trim();
  if (!base) return null;
  try {
    const res = await fetch(`${base.replace(/\/+$/, '')}/api/duplicates/scan`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Internal-Token': env.INTERNAL_TOKEN ?? '',
      },
      body: JSON.stringify(body),
    });
    if (!res.ok) return null;
    return (await res.json()) as VpsScanPayload;
  } catch (err) {
    console.error('vps /api/duplicates/scan failed:', err);
    return null;
  }
}

async function loadRows(
  env: Env,
  userId: string,
  scope: DuplicateScope
): Promise<{ myRows: RepoRow[]; trendingRows: TrendingRow[] }> {
  let myRows: RepoRow[] = [];
  let trendingRows: TrendingRow[] = [];
  if (scope === 'my' || scope === 'all') {
    myRows = await all<RepoRow>(
      env.DB,
      `SELECT * FROM my_repositories WHERE user_id = ? ORDER BY stars DESC LIMIT ?`,
      [userId, MAX_REPOS]
    );
  }
  if (scope === 'trending' || scope === 'all') {
    const remaining = Math.max(0, MAX_REPOS - myRows.length);
    if (remaining > 0) {
      trendingRows = await all<TrendingRow>(
        env.DB,
        `SELECT * FROM trending_repositories ORDER BY stars DESC LIMIT ?`,
        [remaining]
      );
    }
  }
  return { myRows, trendingRows };
}

function readThresholds(value: unknown): DuplicateThresholds {
  const source = (value ?? {}) as Partial<DuplicateThresholds>;
  return {
    minScore: clampNumber(source.minScore, 0, 1, DEFAULT_THRESHOLDS.minScore),
    nameThreshold: clampNumber(source.nameThreshold, 0, 1, DEFAULT_THRESHOLDS.nameThreshold),
    descriptionThreshold: clampNumber(
      source.descriptionThreshold,
      0,
      1,
      DEFAULT_THRESHOLDS.descriptionThreshold
    ),
    vectorThreshold: clampNumber(
      source.vectorThreshold,
      0,
      1,
      DEFAULT_THRESHOLDS.vectorThreshold
    ),
    maxRepos: Math.round(clampNumber(source.maxRepos, 2, 5000, MAX_REPOS)),
    maxClusters: Math.round(clampNumber(source.maxClusters, 1, 200, MAX_CLUSTERS)),
  };
}

function scanId(): string {
  if (typeof crypto.randomUUID === 'function') {
    return `dup_${crypto.randomUUID().replace(/-/g, '').slice(0, 12)}`;
  }
  return `dup_${Date.now().toString(36)}`;
}

duplicates.post('/scan', async (c) => {
  const started = Date.now();
  const user = c.get('user');
  if (!user) return c.json({ error: 'unauthorized' }, 401);

  let body: Record<string, unknown> = {};
  try {
    const parsed = await c.req.json();
    if (parsed && typeof parsed === 'object') body = parsed as Record<string, unknown>;
  } catch {
    return c.json({ error: 'invalid_json' }, 400);
  }

  const scope = normalizeDuplicateScope(body.scope);
  if (!scope) {
    return c.json({ error: 'invalid_scope', message: 'scope 仅支持 my / trending / all' }, 400);
  }
  const minScore = clampNumber(body.minScore, 0, 1, DEFAULT_THRESHOLDS.minScore);
  const maxClusters = Math.round(
    clampNumber(body.maxClusters, 1, 100, DEFAULT_THRESHOLDS.maxClusters)
  );

  const { myRows, trendingRows } = await loadRows(c.env, user.id, scope);
  const ownedMyIds = new Set(myRows.map((row) => row.id));
  const rows = new Map<string, RepoRowLike>();
  for (const row of myRows) rows.set(rowKey('my', row.id), row);
  for (const row of trendingRows) rows.set(rowKey('trending', row.id), row);

  const vpsPayload = await postVpsScan(c.env, {
    scope,
    ...(scope === 'trending' ? {} : { myRepoIds: [...ownedMyIds] }),
    minScore,
    maxRepos: MAX_REPOS,
    maxClusters,
  });
  const vpsOk = vpsPayload !== null;
  const remoteClusters = vpsOk
    ? normalizeVpsClusters(vpsPayload, ownedMyIds, rows)
    : [];

  // VPS 可用时只补扫收藏库（通常规模小）；VPS 不可达时全量本地兜底。
  const localInputs: DuplicateRepoInput[] = [];
  if (vpsOk) {
    for (const row of myRows) localInputs.push(rowToInput(row, 'my'));
  } else {
    for (const row of myRows.slice(0, LOCAL_MAX_REPOS)) localInputs.push(rowToInput(row, 'my'));
    for (const row of trendingRows.slice(0, Math.max(0, LOCAL_MAX_REPOS - localInputs.length))) {
      localInputs.push(rowToInput(row, 'trending'));
    }
  }
  const localClusters = detectNameDuplicates(localInputs).filter(
    (cluster) => cluster.confidence >= minScore
  );

  let clusters = mergeDuplicateClusters([...remoteClusters, ...localClusters]);
  const dismissedRows = await all<{ cluster_key: string }>(
    c.env.DB,
    `SELECT cluster_key FROM duplicate_dismissals WHERE user_id = ?`,
    [user.id]
  );
  const dismissed = new Set(dismissedRows.map((row) => row.cluster_key));
  const beforeDismiss = clusters.length;
  const visible = clusters.filter((cluster) => !dismissed.has(cluster.id));
  clusters = visible.sort((a, b) => b.confidence - a.confidence).slice(0, maxClusters);

  const thresholds = vpsOk
    ? { ...readThresholds(vpsPayload?.thresholds), maxClusters }
    : { ...DEFAULT_THRESHOLDS, minScore, maxClusters };
  const compared = vpsOk
    ? Math.max(0, Number(vpsPayload?.compared) || 0)
    : (localInputs.length * (localInputs.length - 1)) / 2;

  return c.json({
    scanId: typeof vpsPayload?.scanId === 'string' ? vpsPayload.scanId : scanId(),
    scope,
    mode: vpsOk ? (localClusters.length > 0 ? 'hybrid' : 'vps') : 'local',
    count: clusters.length,
    scanned: myRows.length + trendingRows.length,
    compared,
    tookMs: Date.now() - started,
    thresholds,
    dismissedCount: Math.max(0, beforeDismiss - visible.length),
    clusters,
  } satisfies DuplicateScanResponse);
});

duplicates.post('/dismiss', async (c) => {
  const user = c.get('user');
  if (!user) return c.json({ error: 'unauthorized' }, 401);
  let body: Record<string, unknown> = {};
  try {
    const parsed = await c.req.json();
    if (parsed && typeof parsed === 'object') body = parsed as Record<string, unknown>;
  } catch {
    return c.json({ error: 'invalid_json' }, 400);
  }
  const clusterId = typeof body.clusterId === 'string' ? body.clusterId.trim() : '';
  if (!clusterId || clusterId.length > 128) {
    return c.json({ error: 'invalid_cluster_id' }, 400);
  }
  const repoIds = Array.isArray(body.repoIds)
    ? body.repoIds
        .filter((item): item is string => typeof item === 'string')
        .slice(0, 50)
    : [];
  const reason = typeof body.reason === 'string' ? body.reason.slice(0, 500) : null;
  await run(
    c.env.DB,
    `INSERT INTO duplicate_dismissals (id, user_id, cluster_key, repo_ids, reason)
     VALUES (?, ?, ?, ?, ?)
     ON CONFLICT (user_id, cluster_key) DO UPDATE SET
       repo_ids = excluded.repo_ids,
       reason = excluded.reason,
       created_at = CURRENT_TIMESTAMP`,
    [crypto.randomUUID(), user.id, clusterId, JSON.stringify(repoIds), reason]
  );
  return c.json({ dismissed: true, clusterId });
});

duplicates.get('/dismissed', async (c) => {
  const user = c.get('user');
  if (!user) return c.json({ error: 'unauthorized' }, 401);
  const rows = await all<{
    cluster_key: string;
    repo_ids: string | null;
    reason: string | null;
    created_at: string | null;
  }>(
    c.env.DB,
    `SELECT cluster_key, repo_ids, reason, created_at
     FROM duplicate_dismissals WHERE user_id = ? ORDER BY created_at DESC LIMIT 200`,
    [user.id]
  );
  const items: DuplicateDismissal[] = rows.map((row) => {
    let repoIds: string[] = [];
    try {
      const parsed = JSON.parse(row.repo_ids ?? '[]');
      if (Array.isArray(parsed)) {
        repoIds = parsed.filter((item): item is string => typeof item === 'string');
      }
    } catch {
      repoIds = [];
    }
    return {
      clusterId: row.cluster_key,
      repoIds,
      reason: row.reason,
      createdAt: row.created_at,
    };
  });
  return c.json({ count: items.length, items });
});

duplicates.delete('/dismiss/:clusterId', async (c) => {
  const user = c.get('user');
  if (!user) return c.json({ error: 'unauthorized' }, 401);
  const clusterId = c.req.param('clusterId').trim();
  if (!clusterId || clusterId.length > 128) {
    return c.json({ error: 'invalid_cluster_id' }, 400);
  }
  const result = await run(
    c.env.DB,
    `DELETE FROM duplicate_dismissals WHERE user_id = ? AND cluster_key = ?`,
    [user.id, clusterId]
  );
  const changes = (result.meta as { changes?: number } | undefined)?.changes ?? 0;
  return c.json({ removed: changes > 0, clusterId });
});

export default duplicates;
