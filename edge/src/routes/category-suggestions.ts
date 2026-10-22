/**
 * 自动分类建议路由（M7-02「按业务线」）
 *
 * GET  /api/category-suggestions            当前用户的分类建议（含汇总 / 分类列表）
 * POST /api/category-suggestions/generate   批量生成（VPS 规则引擎，失败时本地兜底）
 * POST /api/category-suggestions/accept     采纳：确保分类存在 → 写 my_repositories.category_id
 * POST /api/category-suggestions/dismiss    忽略
 *
 * 所有接口都要求登录；SQL 一律带 `user_id = ?`，采纳时再次校验仓库归属。
 */
import { Hono } from 'hono';
import type {
  CategorySuggestionListItem,
  CategorySuggestionListResponse,
  CategorySuggestionRow,
  Env,
  Variables,
} from '../types';
import { all, first, run } from '../db';
import {
  categoryIdForName,
  clampLimit,
  clampMinScore,
  clampOffset,
  clampPerRepo,
  normalizeCategoryName,
  normalizeStatus,
  splitTags,
  stableSuggestionId,
} from '../category-suggestions/helpers';
import {
  businessLineDescription,
  suggestCategoriesLocally,
  type CategorySuggestionRepo,
  type LocalCategorySuggestion,
} from '../category-suggestions/rules';

const categorySuggestions = new Hono<{ Bindings: Env; Variables: Variables }>();

interface RepoSnapshotRow {
  id: string;
  name: string;
  description: string | null;
  language: string | null;
  readme_summary: string | null;
  tag_names: string | null;
  category_name: string | null;
}

interface VpsSuggestionPayload {
  categoryName?: unknown;
  businessLine?: unknown;
  score?: unknown;
  reason?: unknown;
  evidence?: unknown;
}

interface VpsRepoPayload {
  repoId?: unknown;
  suggestions?: VpsSuggestionPayload[];
}

interface VpsGenerateResponse {
  items?: VpsRepoPayload[];
}

interface GenerateBody {
  repoIds?: unknown;
  limit?: unknown;
  perRepo?: unknown;
  minScore?: unknown;
}

interface AcceptBody {
  ids?: unknown;
  repoId?: unknown;
  categoryName?: unknown;
}

interface DismissBody {
  ids?: unknown;
  reason?: unknown;
}

async function readJson<T>(c: { req: { json: () => Promise<unknown> } }): Promise<T | null> {
  try {
    const body = await c.req.json();
    if (!body || typeof body !== 'object' || Array.isArray(body)) return null;
    return body as T;
  } catch {
    return null;
  }
}

function parseStringArray(value: unknown, max = 100): string[] {
  if (!Array.isArray(value)) return [];
  return value
    .filter((item): item is string => typeof item === 'string')
    .map((item) => item.trim())
    .filter(Boolean)
    .slice(0, max);
}

function toRepoSnapshot(row: RepoSnapshotRow): CategorySuggestionRepo {
  return {
    repoId: row.id,
    name: row.name ?? '',
    description: row.description ?? '',
    language: row.language ?? '',
    summary: row.readme_summary ?? '',
    tags: splitTags(row.tag_names),
  };
}

/** 读取当前用户仓库；repoIds 为空时按 Star 降序取 limit 条。 */
async function loadRepos(
  db: D1Database,
  userId: string,
  repoIds: string[],
  limit: number
): Promise<RepoSnapshotRow[]> {
  const where = ['r.user_id = ?'];
  const params: Array<string | number | null> = [userId];
  if (repoIds.length > 0) {
    where.push(`r.id IN (${repoIds.map(() => '?').join(',')})`);
    params.push(...repoIds);
  }
  const rows = await all<RepoSnapshotRow>(
    db,
    `SELECT r.id, r.name, r.description, r.language, r.readme_summary,
            cat.name AS category_name,
            (SELECT GROUP_CONCAT(t.name, ',')
               FROM repo_tags rt JOIN tags t ON t.id = rt.tag_id
              WHERE rt.repo_id = r.id) AS tag_names
       FROM my_repositories r
       LEFT JOIN categories cat ON cat.id = r.category_id
      WHERE ${where.join(' AND ')}
      ORDER BY r.stars DESC, r.updated_at DESC
      LIMIT ?`,
    [...params, limit]
  );
  return rows;
}

async function postVps(
  env: Env,
  path: string,
  body: unknown
): Promise<VpsGenerateResponse | null> {
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
    return (await res.json()) as VpsGenerateResponse;
  } catch (err) {
    console.error(`vps ${path} failed:`, err);
    return null;
  }
}

function parseVpsSuggestions(payload: VpsGenerateResponse | null): Map<string, LocalCategorySuggestion[]> {
  const result = new Map<string, LocalCategorySuggestion[]>();
  for (const item of payload?.items ?? []) {
    if (typeof item.repoId !== 'string' || !Array.isArray(item.suggestions)) continue;
    const suggestions: LocalCategorySuggestion[] = [];
    for (const suggestion of item.suggestions) {
      if (
        typeof suggestion.categoryName !== 'string' ||
        typeof suggestion.businessLine !== 'string' ||
        typeof suggestion.score !== 'number'
      ) {
        continue;
      }
      suggestions.push({
        categoryName: normalizeCategoryName(suggestion.categoryName),
        businessLine: suggestion.businessLine,
        score: suggestion.score,
        reason: typeof suggestion.reason === 'string' ? suggestion.reason : '',
        evidence: typeof suggestion.evidence === 'string' ? suggestion.evidence : '',
      });
    }
    result.set(item.repoId, suggestions);
  }
  return result;
}

// ── 列表 ────────────────────────────────────────────────────────

categorySuggestions.get('/', async (c) => {
  const user = c.get('user');
  if (!user) return c.json({ error: 'unauthorized' }, 401);

  const status = normalizeStatus(c.req.query('status'));
  if (status === null) return c.json({ error: 'invalid_status' }, 400);
  const limit = clampLimit(c.req.query('limit'));
  const offset = clampOffset(c.req.query('offset'));
  const repoId = c.req.query('repoId')?.trim() ?? '';

  const where = ['s.user_id = ?'];
  const params: Array<string | number> = [user.id];
  if (status !== 'all') {
    where.push('s.status = ?');
    params.push(status);
  }
  if (repoId) {
    where.push('s.repo_id = ?');
    params.push(repoId);
  }

  const rows = await all<
    CategorySuggestionRow & {
      repo_name: string | null;
      repo_url: string | null;
      summary: string | null;
      current_category: string | null;
    }
  >(
    c.env.DB,
    `SELECT s.*, r.name AS repo_name, r.html_url AS repo_url,
            r.readme_summary AS summary, cat.name AS current_category
       FROM category_suggestions s
       LEFT JOIN my_repositories r ON r.id = s.repo_id AND r.user_id = s.user_id
       LEFT JOIN categories cat ON cat.id = r.category_id
      WHERE ${where.join(' AND ')}
      ORDER BY s.score DESC, s.updated_at DESC
      LIMIT ? OFFSET ?`,
    [...params, limit, offset]
  );

  const statusRows = await all<{ status: string; n: number }>(
    c.env.DB,
    `SELECT status, COUNT(*) AS n FROM category_suggestions WHERE user_id = ? GROUP BY status`,
    [user.id]
  );
  const counts: Record<string, number> = { pending: 0, accepted: 0, dismissed: 0 };
  for (const row of statusRows) counts[row.status] = Number(row.n ?? 0);
  const pending = counts.pending ?? 0;
  const accepted = counts.accepted ?? 0;
  const dismissed = counts.dismissed ?? 0;
  const repoRow = await first<{ n: number }>(
    c.env.DB,
    `SELECT COUNT(DISTINCT repo_id) AS n FROM category_suggestions WHERE user_id = ?`,
    [user.id]
  );
  const avgRow = await first<{ avg: number | null }>(
    c.env.DB,
    `SELECT AVG(score) AS avg FROM category_suggestions WHERE user_id = ? AND status = 'pending'`,
    [user.id]
  );

  const summary = {
    total: pending + accepted + dismissed,
    pending,
    accepted,
    dismissed,
    repos: Number(repoRow?.n ?? 0),
    avgScore: Number(avgRow?.avg ?? 0),
  };

  const categories = await all<{ id: string; name: string }>(
    c.env.DB,
    `SELECT id, name FROM categories ORDER BY sort_order ASC, name ASC`
  );

  const items: CategorySuggestionListItem[] = rows.map((row) => ({
    id: row.id,
    repoId: row.repo_id,
    repoName: row.repo_name ?? row.repo_id,
    repoUrl: row.repo_url ?? `https://github.com/${row.repo_id}`,
    summary: row.summary,
    categoryName: row.category_name,
    businessLine: row.business_line,
    score: Number(row.score ?? 0),
    reason: row.reason,
    evidence: row.evidence,
    status: row.status,
    currentCategory: row.current_category,
    updatedAt: row.updated_at,
  }));

  const payload: CategorySuggestionListResponse = { items, summary, categories };
  return c.json(payload);
});

// ── 生成 ────────────────────────────────────────────────────────

categorySuggestions.post('/generate', async (c) => {
  const user = c.get('user');
  if (!user) return c.json({ error: 'unauthorized' }, 401);

  const body = (await readJson<GenerateBody>(c)) ?? {};
  const limit = clampLimit(body.limit, 200, 500);
  const perRepo = clampPerRepo(body.perRepo);
  const minScore = clampMinScore(body.minScore);
  const repoIds = parseStringArray(body.repoIds, 500);

  const rows = await loadRepos(c.env.DB, user.id, repoIds, limit);
  if (rows.length === 0) {
    return c.json({
      generatedAt: new Date().toISOString(),
      scanned: 0,
      suggested: 0,
      skipped: 0,
      source: 'local',
    });
  }

  const snapshots = rows.map(toRepoSnapshot);
  const vpsPayload = await postVps(c.env, '/api/category-suggestions/generate', {
    repos: snapshots,
    perRepo,
    minScore,
  });
  const vpsMap = parseVpsSuggestions(vpsPayload);

  let source: 'vps' | 'local' | 'mixed' = vpsPayload ? 'vps' : 'local';
  let suggested = 0;
  let skipped = 0;

  for (const row of rows) {
    const snapshot = toRepoSnapshot(row);
    let suggestions = vpsMap.get(row.id) ?? [];
    if (suggestions.length === 0) {
      suggestions = suggestCategoriesLocally(snapshot, perRepo, minScore);
      if (vpsPayload && suggestions.length > 0) source = 'mixed';
    }
    const currentCategory = (row.category_name ?? '').toLowerCase();
    const filtered = suggestions.filter(
      (item) =>
        normalizeCategoryName(item.categoryName).toLowerCase() !== currentCategory &&
        item.score >= minScore
    );
    if (filtered.length === 0) {
      skipped += 1;
      continue;
    }

    let stored = 0;
    for (const suggestion of filtered) {
      const id = await stableSuggestionId(user.id, row.id, suggestion.categoryName);
      const existing = await first<{ status: string }>(
        c.env.DB,
        `SELECT status FROM category_suggestions
          WHERE user_id = ? AND repo_id = ? AND category_name = ?`,
        [user.id, row.id, suggestion.categoryName]
      );
      // 已采纳 / 已忽略的建议保持用户决策，不被重复生成覆盖
      if (existing && existing.status !== 'pending') continue;
      if (existing) {
        await run(
          c.env.DB,
          `UPDATE category_suggestions
              SET business_line = ?, score = ?, reason = ?, evidence = ?,
                  updated_at = CURRENT_TIMESTAMP
            WHERE user_id = ? AND repo_id = ? AND category_name = ?`,
          [
            suggestion.businessLine,
            suggestion.score,
            suggestion.reason,
            suggestion.evidence,
            user.id,
            row.id,
            suggestion.categoryName,
          ]
        );
      } else {
        await run(
          c.env.DB,
          `INSERT INTO category_suggestions
             (id, user_id, repo_id, category_name, business_line, score, reason, evidence, status)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending')`,
          [
            id,
            user.id,
            row.id,
            suggestion.categoryName,
            suggestion.businessLine,
            suggestion.score,
            suggestion.reason,
            suggestion.evidence,
          ]
        );
      }
      stored += 1;
    }
    if (stored === 0) skipped += 1;
    suggested += stored;
  }

  return c.json({
    generatedAt: new Date().toISOString(),
    scanned: rows.length,
    suggested,
    skipped,
    source,
  });
});

// ── 采纳 ────────────────────────────────────────────────────────

async function ensureCategory(
  db: D1Database,
  name: string,
  businessLine: string
): Promise<{ id: string; created: boolean }> {
  const normalized = normalizeCategoryName(name);
  const existing = await first<{ id: string }>(
    db,
    `SELECT id FROM categories WHERE lower(name) = lower(?) LIMIT 1`,
    [normalized]
  );
  if (existing) return { id: existing.id, created: false };

  const id = await categoryIdForName(normalized);
  const maxRow = await first<{ max: number | null }>(
    db,
    `SELECT MAX(sort_order) AS max FROM categories`
  );
  const sortOrder = Number(maxRow?.max ?? 0) + 10;
  await run(
    db,
    `INSERT INTO categories (id, name, parent_id, description, sort_order)
     VALUES (?, ?, NULL, ?, ?)`,
    [id, normalized, businessLineDescription(businessLine) || null, sortOrder]
  );
  return { id, created: true };
}

categorySuggestions.post('/accept', async (c) => {
  const user = c.get('user');
  if (!user) return c.json({ error: 'unauthorized' }, 401);

  const body = await readJson<AcceptBody>(c);
  if (!body) return c.json({ error: 'invalid_body' }, 400);

  const ids = parseStringArray(body.ids);
  const repoId = typeof body.repoId === 'string' ? body.repoId.trim() : '';
  const categoryName =
    typeof body.categoryName === 'string' ? normalizeCategoryName(body.categoryName) : '';

  let rows: CategorySuggestionRow[] = [];
  if (ids.length > 0) {
    rows = await all<CategorySuggestionRow>(
      c.env.DB,
      `SELECT * FROM category_suggestions
        WHERE user_id = ? AND id IN (${ids.map(() => '?').join(',')}) AND status = 'pending'`,
      [user.id, ...ids]
    );
  } else if (repoId && categoryName) {
    rows = await all<CategorySuggestionRow>(
      c.env.DB,
      `SELECT * FROM category_suggestions
        WHERE user_id = ? AND repo_id = ? AND lower(category_name) = lower(?)
          AND status = 'pending'`,
      [user.id, repoId, categoryName]
    );
  } else {
    return c.json({ error: 'invalid_selection' }, 400);
  }

  let accepted = 0;
  let categoriesCreated = 0;
  const items: Array<{ repoId: string; categoryName: string; categoryId: string }> = [];

  for (const row of rows) {
    const category = await ensureCategory(c.env.DB, row.category_name, row.business_line);
    if (category.created) categoriesCreated += 1;

    const update = await run(
      c.env.DB,
      `UPDATE my_repositories SET category_id = ? WHERE id = ? AND user_id = ?`,
      [category.id, row.repo_id, user.id]
    );
    if ((update.meta.changes ?? 0) === 0) continue;

    await run(
      c.env.DB,
      `UPDATE category_suggestions SET status = 'accepted', updated_at = CURRENT_TIMESTAMP
        WHERE id = ? AND user_id = ?`,
      [row.id, user.id]
    );
    // 同一仓库已定分类后，其余待确认建议不再打扰
    await run(
      c.env.DB,
      `UPDATE category_suggestions SET status = 'dismissed', updated_at = CURRENT_TIMESTAMP
        WHERE user_id = ? AND repo_id = ? AND id != ? AND status = 'pending'`,
      [user.id, row.repo_id, row.id]
    );
    accepted += 1;
    items.push({
      repoId: row.repo_id,
      categoryName: row.category_name,
      categoryId: category.id,
    });
  }

  return c.json({ accepted, categoriesCreated, items });
});

// ── 忽略 ────────────────────────────────────────────────────────

categorySuggestions.post('/dismiss', async (c) => {
  const user = c.get('user');
  if (!user) return c.json({ error: 'unauthorized' }, 401);

  const body = await readJson<DismissBody>(c);
  if (!body) return c.json({ error: 'invalid_body' }, 400);
  const ids = parseStringArray(body.ids);
  if (ids.length === 0) return c.json({ error: 'invalid_ids' }, 400);

  const result = await run(
    c.env.DB,
    `UPDATE category_suggestions SET status = 'dismissed', updated_at = CURRENT_TIMESTAMP
      WHERE user_id = ? AND id IN (${ids.map(() => '?').join(',')}) AND status = 'pending'`,
    [user.id, ...ids]
  );

  return c.json({ dismissed: result.meta.changes ?? 0 });
});

export default categorySuggestions;
