/**
 * 自动打标建议路由（REQ-202610-0960 / M7-01）
 *
 * GET  /api/tag-suggestions           当前用户的建议列表（按状态 / 仓库过滤）
 * POST /api/tag-suggestions/generate  基于摘要生成建议（VPS 优先，本地规则兜底）
 * POST /api/tag-suggestions/accept    采纳建议：写 tags / repo_tags
 * POST /api/tag-suggestions/dismiss   忽略建议（重复生成不覆盖状态）
 *
 * 所有 SQL 都带 user_id 条件；采纳时再次校验仓库归属。
 */
import { Hono } from 'hono';
import type { Env, RepoRow, TagSuggestionRow, Variables } from '../types';
import { all, count, first, run } from '../db';
import {
  buildLocalGenerateResult,
  clampLimit,
  clampOffset,
  clampPerRepo,
  hashSuggestionId,
  mergeGeneratedTags,
  normalizeGeneratedResult,
  normalizeSuggestionStatus,
  normalizeTagKey,
  toTagSuggestionDto,
  type GenerateResult,
} from '../tag-suggestions/helpers';

const tagSuggestions = new Hono<{ Bindings: Env; Variables: Variables }>();

function placeholders(size: number): string {
  return Array.from({ length: size }, () => '?').join(', ');
}

function stringList(value: unknown, max: number): string[] {
  if (!Array.isArray(value)) return [];
  const result: string[] = [];
  for (const item of value) {
    if (typeof item !== 'string') continue;
    const trimmed = item.trim();
    if (trimmed && !result.includes(trimmed)) result.push(trimmed);
    if (result.length >= max) break;
  }
  return result;
}

/** VPS 生成接口（不可达 / 非 2xx / 形状异常均返回 null，由调用方兜底）。 */
async function fetchVpsSuggestions(
  env: Env,
  body: { repoIds: string[]; limit: number; perRepo: number }
): Promise<GenerateResult | null> {
  const base = env.VPS_NODE_URL?.trim();
  if (!base) return null;
  try {
    const response = await fetch(`${base.replace(/\/+$/, '')}/api/tag-suggestions/generate`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Internal-Token': env.INTERNAL_TOKEN ?? '',
      },
      body: JSON.stringify(body),
    });
    if (!response.ok) return null;
    const raw = (await response.json()) as unknown;
    return normalizeGeneratedResult(raw, body.repoIds, body.perRepo);
  } catch (err) {
    console.error('vps tag-suggestions generate failed:', err);
    return null;
  }
}

/** 采纳时确保标签存在，返回 tag id。 */
async function ensureTag(db: D1Database, name: string): Promise<number> {
  const existing = await first<{ id: number }>(
    db,
    'SELECT id FROM tags WHERE lower(name) = lower(?) LIMIT 1',
    [name]
  );
  if (existing) return existing.id;
  try {
    const inserted = await run(db, 'INSERT INTO tags (name, count) VALUES (?, 0)', [name]);
    return Number(inserted.meta.last_row_id ?? 0);
  } catch {
    // 并发插入撞唯一约束：回查一次
    const again = await first<{ id: number }>(
      db,
      'SELECT id FROM tags WHERE lower(name) = lower(?) LIMIT 1',
      [name]
    );
    return again?.id ?? 0;
  }
}

tagSuggestions.get('/', async (c) => {
  const user = c.get('user');
  if (!user) return c.json({ error: 'unauthorized' }, 401);

  const status = normalizeSuggestionStatus(c.req.query('status'));
  const repoId = c.req.query('repoId')?.trim() ?? '';
  const limit = clampLimit(c.req.query('limit'));
  const offset = clampOffset(c.req.query('offset'));

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
  const whereSql = where.join(' AND ');

  const [rows, total, statusRows, overview] = await Promise.all([
    all<TagSuggestionRow>(
      c.env.DB,
      `SELECT s.*, r.name AS repo_name, r.html_url AS repo_url, r.readme_summary AS readme_summary
         FROM tag_suggestions s
         LEFT JOIN my_repositories r ON r.id = s.repo_id AND r.user_id = s.user_id
        WHERE ${whereSql}
        ORDER BY s.updated_at DESC, s.score DESC, s.id ASC
        LIMIT ? OFFSET ?`,
      [...params, limit, offset]
    ),
    count(c.env.DB, `SELECT COUNT(*) AS n FROM tag_suggestions s WHERE ${whereSql}`, params),
    all<{ status: string; n: number }>(
      c.env.DB,
      'SELECT status, COUNT(*) AS n FROM tag_suggestions WHERE user_id = ? GROUP BY status',
      [user.id]
    ),
    first<{ repos: number; avgScore: number | null }>(
      c.env.DB,
      `SELECT COUNT(DISTINCT repo_id) AS repos, AVG(score) AS avgScore
         FROM tag_suggestions WHERE user_id = ? AND status = 'pending'`,
      [user.id]
    ),
  ]);

  const summary = { pending: 0, accepted: 0, dismissed: 0 };
  for (const row of statusRows) {
    if (row.status === 'pending' || row.status === 'accepted' || row.status === 'dismissed') {
      summary[row.status] = row.n ?? 0;
    }
  }

  return c.json({
    items: rows.map(toTagSuggestionDto),
    total,
    summary: {
      ...summary,
      repos: overview?.repos ?? 0,
      avgScore: overview?.avgScore ?? null,
    },
  });
});

tagSuggestions.post('/generate', async (c) => {
  const user = c.get('user');
  if (!user) return c.json({ error: 'unauthorized' }, 401);

  let body: { repoIds?: unknown; limit?: unknown; perRepo?: unknown } | null = null;
  try {
    body = await c.req.json();
  } catch {
    return c.json({ error: 'invalid_json' }, 400);
  }
  if (!body || typeof body !== 'object') {
    return c.json({ error: 'invalid_body' }, 400);
  }

  const requestedIds = stringList(body.repoIds, 200);
  const limit = clampLimit(body.limit, 200);
  const perRepo = clampPerRepo(body.perRepo);

  const repos = await all<Pick<RepoRow, 'id' | 'language' | 'readme_summary'>>(
    c.env.DB,
    `SELECT id, language, readme_summary
       FROM my_repositories
      WHERE user_id = ? AND TRIM(COALESCE(readme_summary, '')) != ''
      ORDER BY stars DESC, id ASC
      LIMIT 500`,
    [user.id]
  );

  const requested = new Set(requestedIds);
  const selected = (requested.size > 0 ? repos.filter((repo) => requested.has(repo.id)) : repos).slice(
    0,
    limit
  );
  const selectedIds = selected.map((repo) => repo.id);

  if (selected.length === 0) {
    return c.json({
      generatedAt: new Date().toISOString(),
      scanned: 0,
      suggested: 0,
      skipped: 0,
      items: [],
      source: 'local',
      saved: 0,
    });
  }

  const vpsResult = await fetchVpsSuggestions(c.env, {
    repoIds: selectedIds,
    limit,
    perRepo,
  });
  const result =
    vpsResult ??
    buildLocalGenerateResult(
      selected.map((repo) => ({
        id: repo.id,
        language: repo.language,
        summary: repo.readme_summary,
      })),
      perRepo
    );

  let saved = 0;
  for (const item of result.items) {
    for (const tag of mergeGeneratedTags(item.tags)) {
      const normalized = normalizeTagKey(tag.name);
      if (!normalized) continue;
      const id = hashSuggestionId(user.id, item.repoId, tag.name);
      const upsert = await run(
        c.env.DB,
        `INSERT INTO tag_suggestions
           (id, user_id, repo_id, tag_name, normalized_name, category, score, reason, evidence, status, created_at, updated_at)
         VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
         ON CONFLICT(user_id, repo_id, normalized_name) DO UPDATE SET
           tag_name = excluded.tag_name,
           category = excluded.category,
           score = excluded.score,
           reason = excluded.reason,
           evidence = excluded.evidence,
           updated_at = CURRENT_TIMESTAMP
         WHERE tag_suggestions.status = 'pending'`,
        [
          id,
          user.id,
          item.repoId,
          tag.name,
          normalized,
          tag.category,
          tag.score,
          tag.reason,
          tag.evidence,
        ]
      );
      saved += upsert.meta.changes ?? 0;
    }
  }

  return c.json({
    ...result,
    scanned: selected.length,
    suggested: result.items.length,
    skipped: Math.max(0, selected.length - result.items.length),
    source: result.source ?? 'vps',
    saved,
  });
});

tagSuggestions.post('/accept', async (c) => {
  const user = c.get('user');
  if (!user) return c.json({ error: 'unauthorized' }, 401);

  let body: { ids?: unknown; repoId?: unknown; tags?: unknown } | null = null;
  try {
    body = await c.req.json();
  } catch {
    return c.json({ error: 'invalid_json' }, 400);
  }
  if (!body || typeof body !== 'object') {
    return c.json({ error: 'invalid_body' }, 400);
  }

  const ids = stringList(body.ids, 100);
  const repoId = typeof body.repoId === 'string' ? body.repoId.trim() : '';
  const tagNames = stringList(body.tags, 20);

  let suggestions: TagSuggestionRow[] = [];
  if (ids.length > 0) {
    suggestions = await all<TagSuggestionRow>(
      c.env.DB,
      `SELECT * FROM tag_suggestions
        WHERE user_id = ? AND status = 'pending' AND id IN (${placeholders(ids.length)})`,
      [user.id, ...ids]
    );
  } else if (repoId && tagNames.length > 0) {
    const normalized = tagNames.map(normalizeTagKey).filter(Boolean);
    if (normalized.length === 0) {
      return c.json({ error: 'invalid_body', message: 'tags 不能为空' }, 400);
    }
    suggestions = await all<TagSuggestionRow>(
      c.env.DB,
      `SELECT * FROM tag_suggestions
        WHERE user_id = ? AND status = 'pending' AND repo_id = ?
          AND normalized_name IN (${placeholders(normalized.length)})`,
      [user.id, repoId, ...normalized]
    );
  } else {
    return c.json({ error: 'invalid_body', message: '需要 ids 或 repoId + tags' }, 400);
  }

  const owned = new Map<string, boolean>();
  let accepted = 0;
  let tagsApplied = 0;
  let skipped = 0;

  for (const suggestion of suggestions) {
    if (!owned.has(suggestion.repo_id)) {
      const repo = await first<{ id: string }>(
        c.env.DB,
        'SELECT id FROM my_repositories WHERE id = ? AND user_id = ?',
        [suggestion.repo_id, user.id]
      );
      owned.set(suggestion.repo_id, Boolean(repo));
    }
    if (!owned.get(suggestion.repo_id)) {
      skipped += 1;
      continue;
    }

    const tagId = await ensureTag(c.env.DB, suggestion.tag_name);
    if (!tagId) {
      skipped += 1;
      continue;
    }
    const linked = await first<{ tag_id: number }>(
      c.env.DB,
      'SELECT tag_id FROM repo_tags WHERE repo_id = ? AND tag_id = ?',
      [suggestion.repo_id, tagId]
    );
    if (!linked) {
      await run(c.env.DB, 'INSERT INTO repo_tags (repo_id, tag_id) VALUES (?, ?)', [
        suggestion.repo_id,
        tagId,
      ]);
      await run(c.env.DB, 'UPDATE tags SET count = COALESCE(count, 0) + 1 WHERE id = ?', [tagId]);
      tagsApplied += 1;
    } else {
      skipped += 1;
    }

    await run(
      c.env.DB,
      `UPDATE tag_suggestions SET status = 'accepted', updated_at = CURRENT_TIMESTAMP
        WHERE id = ? AND user_id = ? AND status = 'pending'`,
      [suggestion.id, user.id]
    );
    accepted += 1;
  }

  return c.json({ accepted, tagsApplied, skipped, total: suggestions.length });
});

tagSuggestions.post('/dismiss', async (c) => {
  const user = c.get('user');
  if (!user) return c.json({ error: 'unauthorized' }, 401);

  let body: { ids?: unknown } | null = null;
  try {
    body = await c.req.json();
  } catch {
    return c.json({ error: 'invalid_json' }, 400);
  }
  if (!body || typeof body !== 'object') {
    return c.json({ error: 'invalid_body' }, 400);
  }

  const ids = stringList(body.ids, 100);
  if (ids.length === 0) {
    return c.json({ error: 'invalid_body', message: 'ids 不能为空' }, 400);
  }

  const result = await run(
    c.env.DB,
    `UPDATE tag_suggestions SET status = 'dismissed', updated_at = CURRENT_TIMESTAMP
      WHERE user_id = ? AND status = 'pending' AND id IN (${placeholders(ids.length)})`,
    [user.id, ...ids]
  );

  return c.json({ dismissed: result.meta.changes ?? 0 });
});

export default tagSuggestions;
