/**
 * Agent 工作流路由（REQ-202610-0968 / M7-09）
 *
 * GET  /api/agent/templates            工作流模板与默认参数
 * GET  /api/agent/runs                 执行记录
 * POST /api/agent/runs                 创建并同步执行一次工作流
 * GET  /api/agent/runs/:id             执行详情（计划 / 结果 / 草稿）
 * GET  /api/agent/drafts               草稿列表
 * GET  /api/agent/drafts/:id           草稿详情
 * POST /api/agent/drafts/:id/status    标记草稿已采用 / 已丢弃
 *
 * 所有 SQL 带 user_id；VPS 只接收当前用户快照，不接收用户身份。
 */
import { Hono } from 'hono';
import type { Context } from 'hono';
import type {
  AgentAction,
  AgentDraft,
  AgentDraftRow,
  AgentMode,
  AgentPlanStep,
  AgentRunResult,
  AgentRunRow,
  AgentTemplate,
  Env,
  Variables,
} from '../types';
import { all, count, first, run } from '../db';
import { categoryIdForName } from '../category-suggestions/helpers';
import {
  AGENT_TEMPLATES,
  buildLocalDraft,
  buildLocalPlan,
  clampAgentThreshold,
  computeAgentStats,
  makeAgentDraftId,
  makeAgentRunId,
  normalizeAgentDraftStatus,
  normalizeAgentFocus,
  normalizeAgentMode,
  normalizeAgentRepoIds,
  normalizeAgentTemplate,
  toAgentDraft,
  toAgentRunDetail,
  toAgentRunSummary,
  type AgentRepoSnapshot,
} from '../agent/workflow';

type AppEnv = { Bindings: Env; Variables: Variables };
type AppContext = Context<AppEnv>;

const agent = new Hono<AppEnv>();

const MAX_REPOS = 200;
const MAX_ACTIONS = 200;

interface RepoSnapshotRow {
  id: string;
  name: string;
  description: string | null;
  language: string | null;
  stars: number;
  readme_summary: string | null;
  category_name: string | null;
  tag_names: string | null;
}

interface PendingTagRow {
  id: string;
  repo_id: string;
  tag_name: string;
  score: number;
  reason: string | null;
}

interface PendingCategoryRow {
  id: string;
  repo_id: string;
  category_name: string;
  business_line: string;
  score: number;
  reason: string | null;
}

interface VpsDraftResponse {
  plan?: unknown;
  draft?: { title?: unknown; markdown?: unknown; highlights?: unknown; stats?: unknown };
}

async function readBody(c: AppContext): Promise<Record<string, unknown> | null> {
  try {
    const body = await c.req.json();
    return body && typeof body === 'object' && !Array.isArray(body)
      ? (body as Record<string, unknown>)
      : null;
  } catch {
    return null;
  }
}

function placeholders(size: number): string {
  return Array.from({ length: size }, () => '?').join(', ');
}

function splitTags(value: string | null): string[] {
  return (value ?? '')
    .split(',')
    .map((tag) => tag.trim())
    .filter(Boolean);
}

function toRepoSnapshot(row: RepoSnapshotRow): AgentRepoSnapshot {
  return {
    repoId: row.id,
    name: row.name ?? '',
    description: row.description ?? '',
    language: row.language ?? '',
    stars: Number(row.stars ?? 0),
    category: row.category_name ?? '',
    tags: splitTags(row.tag_names),
    summary: row.readme_summary ?? '',
  };
}

async function loadRepos(
  db: D1Database,
  userId: string,
  repoIds: string[],
  limit = MAX_REPOS
): Promise<RepoSnapshotRow[]> {
  const where = ['r.user_id = ?'];
  const params: Array<string | number> = [userId];
  if (repoIds.length > 0) {
    where.push(`r.id IN (${placeholders(repoIds.length)})`);
    params.push(...repoIds);
  }
  return all<RepoSnapshotRow>(
    db,
    `SELECT r.id, r.name, r.description, r.language, r.stars, r.readme_summary,
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
}

async function loadPendingTags(
  db: D1Database,
  userId: string,
  threshold: number
): Promise<PendingTagRow[]> {
  return all<PendingTagRow>(
    db,
    `SELECT id, repo_id, tag_name, score, reason
       FROM tag_suggestions
      WHERE user_id = ? AND status = 'pending' AND score >= ?
      ORDER BY score DESC, updated_at DESC
      LIMIT ?`,
    [userId, threshold, MAX_ACTIONS]
  );
}

async function loadPendingCategories(
  db: D1Database,
  userId: string,
  threshold: number
): Promise<PendingCategoryRow[]> {
  return all<PendingCategoryRow>(
    db,
    `SELECT id, repo_id, category_name, business_line, score, reason
       FROM category_suggestions
      WHERE user_id = ? AND status = 'pending' AND score >= ?
      ORDER BY score DESC, updated_at DESC
      LIMIT ?`,
    [userId, threshold, MAX_ACTIONS]
  );
}

/** VPS 生成计划 + 草稿；不可达 / 形状异常返回 null。 */
async function fetchVpsDraft(
  env: Env,
  payload: Record<string, unknown>
): Promise<{ plan: AgentPlanStep[]; draft: ReturnType<typeof buildLocalDraft> } | null> {
  const base = env.VPS_NODE_URL?.trim();
  if (!base) return null;
  try {
    const response = await fetch(`${base.replace(/\/+$/, '')}/api/agent/draft`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Internal-Token': env.INTERNAL_TOKEN ?? '',
      },
      body: JSON.stringify(payload),
    });
    if (!response.ok) return null;
    const raw = (await response.json()) as VpsDraftResponse;
    if (!Array.isArray(raw.plan) || !raw.draft || typeof raw.draft.markdown !== 'string') {
      return null;
    }
    const plan: AgentPlanStep[] = [];
    for (const step of raw.plan) {
      if (!step || typeof step !== 'object') continue;
      const item = step as Record<string, unknown>;
      if (typeof item.key !== 'string' || typeof item.title !== 'string') continue;
      plan.push({
        key: item.key,
        title: item.title,
        detail: typeof item.detail === 'string' ? item.detail : '',
        count: Number(item.count ?? 0),
        status: item.status === 'skipped' ? 'skipped' : 'ready',
      });
    }
    const stats =
      raw.draft.stats && typeof raw.draft.stats === 'object'
        ? (raw.draft.stats as ReturnType<typeof computeAgentStats>)
        : undefined;
    return {
      plan,
      draft: {
        title: typeof raw.draft.title === 'string' ? raw.draft.title : '收藏精选草稿',
        markdown: raw.draft.markdown,
        highlights: Array.isArray(raw.draft.highlights)
          ? raw.draft.highlights.filter((item): item is string => typeof item === 'string')
          : [],
        stats: stats ?? computeAgentStats([]),
      },
    };
  } catch (err) {
    console.error('vps agent draft failed:', err);
    return null;
  }
}

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
    const again = await first<{ id: number }>(
      db,
      'SELECT id FROM tags WHERE lower(name) = lower(?) LIMIT 1',
      [name]
    );
    return again?.id ?? 0;
  }
}

async function ensureCategory(
  db: D1Database,
  name: string,
  businessLine: string
): Promise<string> {
  const existing = await first<{ id: string }>(
    db,
    'SELECT id FROM categories WHERE lower(name) = lower(?) LIMIT 1',
    [name]
  );
  if (existing) return existing.id;
  const id = await categoryIdForName(name);
  const maxRow = await first<{ max: number | null }>(db, 'SELECT MAX(sort_order) AS max FROM categories');
  const sortOrder = Number(maxRow?.max ?? 0) + 10;
  await run(
    db,
    `INSERT INTO categories (id, name, parent_id, description, sort_order)
     VALUES (?, ?, NULL, ?, ?)`,
    [id, name, businessLine ? `业务线：${businessLine}` : null, sortOrder]
  );
  return id;
}

async function applyTagActions(
  db: D1Database,
  userId: string,
  rows: PendingTagRow[],
  ownedRepoIds: Set<string>
): Promise<AgentAction[]> {
  const applied: AgentAction[] = [];
  for (const row of rows) {
    if (!ownedRepoIds.has(row.repo_id)) continue;
    const tagId = await ensureTag(db, row.tag_name);
    if (!tagId) continue;
    const linked = await first<{ tag_id: number }>(
      db,
      'SELECT tag_id FROM repo_tags WHERE repo_id = ? AND tag_id = ?',
      [row.repo_id, tagId]
    );
    if (!linked) {
      await run(db, 'INSERT INTO repo_tags (repo_id, tag_id) VALUES (?, ?)', [row.repo_id, tagId]);
      await run(db, 'UPDATE tags SET count = COALESCE(count, 0) + 1 WHERE id = ?', [tagId]);
    }
    await run(
      db,
      `UPDATE tag_suggestions SET status = 'accepted', updated_at = CURRENT_TIMESTAMP
        WHERE id = ? AND user_id = ? AND status = 'pending'`,
      [row.id, userId]
    );
    applied.push({
      kind: 'tag',
      repoId: row.repo_id,
      value: row.tag_name,
      score: Number(row.score ?? 0),
      reason: row.reason ?? '',
    });
  }
  return applied;
}

async function applyCategoryActions(
  db: D1Database,
  userId: string,
  rows: PendingCategoryRow[],
  ownedRepoIds: Set<string>
): Promise<AgentAction[]> {
  const applied: AgentAction[] = [];
  for (const row of rows) {
    if (!ownedRepoIds.has(row.repo_id)) continue;
    const categoryId = await ensureCategory(db, row.category_name, row.business_line);
    const update = await run(
      db,
      'UPDATE my_repositories SET category_id = ? WHERE id = ? AND user_id = ?',
      [categoryId, row.repo_id, userId]
    );
    if ((update.meta.changes ?? 0) === 0) continue;
    await run(
      db,
      `UPDATE category_suggestions SET status = 'accepted', updated_at = CURRENT_TIMESTAMP
        WHERE id = ? AND user_id = ?`,
      [row.id, userId]
    );
    await run(
      db,
      `UPDATE category_suggestions SET status = 'dismissed', updated_at = CURRENT_TIMESTAMP
        WHERE user_id = ? AND repo_id = ? AND id != ? AND status = 'pending'`,
      [userId, row.repo_id, row.id]
    );
    applied.push({
      kind: 'category',
      repoId: row.repo_id,
      value: row.category_name,
      score: Number(row.score ?? 0),
      reason: row.reason ?? '',
    });
  }
  return applied;
}

// ── 模板 ────────────────────────────────────────────────────────

agent.get('/templates', (c) => {
  const user = c.get('user');
  if (!user) return c.json({ error: 'unauthorized' }, 401);
  return c.json({
    items: AGENT_TEMPLATES,
    defaults: { mode: 'preview', threshold: 0.75, limit: MAX_REPOS },
  });
});

// ── 执行 ────────────────────────────────────────────────────────

agent.post('/runs', async (c) => {
  const user = c.get('user');
  if (!user) return c.json({ error: 'unauthorized' }, 401);

  const body = await readBody(c);
  if (!body) return c.json({ error: 'invalid_body' }, 400);

  const template = normalizeAgentTemplate(body.template);
  const mode = normalizeAgentMode(body.mode);
  const threshold = clampAgentThreshold(body.threshold);
  const focus = normalizeAgentFocus(body.focus);
  const repoIds = normalizeAgentRepoIds(body.repoIds);

  const now = new Date();
  const runId = makeAgentRunId(user.id, now);

  try {
    const repos = await loadRepos(c.env.DB, user.id, repoIds);
    const snapshots = repos.map(toRepoSnapshot);
    const ownedRepoIds = new Set(repos.map((repo) => repo.id));
    const pendingTagRows = await loadPendingTags(c.env.DB, user.id, threshold);
    const pendingCategoryRows = await loadPendingCategories(c.env.DB, user.id, threshold);
    const organize = template === 'organize' || template === 'full';
    const shouldApply = organize && mode === 'apply';

    const appliedTags = shouldApply
      ? await applyTagActions(c.env.DB, user.id, pendingTagRows, ownedRepoIds)
      : [];
    const appliedCategories = shouldApply
      ? await applyCategoryActions(c.env.DB, user.id, pendingCategoryRows, ownedRepoIds)
      : [];

    const stats = computeAgentStats(snapshots);
    const localDraft = buildLocalDraft({
      template,
      repos: snapshots,
      appliedTags,
      appliedCategories,
      focus,
      generatedAt: now,
    });

    const vps = await fetchVpsDraft(c.env, {
      template,
      mode,
      threshold,
      focus,
      repos: snapshots.map((repo) => ({
        repoId: repo.repoId,
        name: repo.name,
        description: repo.description,
        language: repo.language,
        stars: repo.stars,
        category: repo.category,
        tags: repo.tags,
        summary: repo.summary,
      })),
      pendingTags: pendingTagRows.map((row) => ({
        kind: 'tag',
        repoId: row.repo_id,
        value: row.tag_name,
        score: row.score,
        reason: row.reason ?? '',
      })),
      pendingCategories: pendingCategoryRows.map((row) => ({
        kind: 'category',
        repoId: row.repo_id,
        value: row.category_name,
        score: row.score,
        reason: row.reason ?? '',
      })),
      appliedTags,
      appliedCategories,
    });

    const plan = vps?.plan ?? buildLocalPlan({
      template,
      mode,
      threshold,
      repoCount: repos.length,
      pendingTags: pendingTagRows.length,
      pendingCategories: pendingCategoryRows.length,
    });
    const draftContent = vps?.draft ?? localDraft;

    const result: AgentRunResult = {
      appliedTags,
      appliedCategories,
      pendingTags: pendingTagRows.length,
      pendingCategories: pendingCategoryRows.length,
      stats,
      source: vps ? 'vps' : 'local',
    };

    const draftId = makeAgentDraftId(user.id, now);
    const metadata = {
      highlights: draftContent.highlights,
      stats,
      template,
      mode,
      focus,
    };
    await run(
      c.env.DB,
      `INSERT INTO agent_drafts
         (id, user_id, run_id, kind, title, content, status, metadata, created_at, updated_at)
       VALUES (?, ?, ?, 'collection_digest', ?, ?, 'draft', ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)`,
      [
        draftId,
        user.id,
        runId,
        draftContent.title,
        draftContent.markdown,
        JSON.stringify(metadata),
      ]
    );

    await run(
      c.env.DB,
      `INSERT INTO agent_runs
         (id, user_id, template, mode, status, threshold, repo_count, plan, result,
          draft_id, error, created_at, finished_at)
       VALUES (?, ?, ?, ?, 'completed', ?, ?, ?, ?, ?, NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)`,
      [
        runId,
        user.id,
        template,
        mode,
        threshold,
        repos.length,
        JSON.stringify(plan),
        JSON.stringify(result),
        draftId,
      ]
    );

    const runRow = await first<AgentRunRow>(c.env.DB, 'SELECT * FROM agent_runs WHERE id = ? AND user_id = ?', [
      runId,
      user.id,
    ]);
    const draftRow = await first<AgentDraftRow>(
      c.env.DB,
      'SELECT * FROM agent_drafts WHERE id = ? AND user_id = ?',
      [draftId, user.id]
    );
    return c.json(
      runRow ? toAgentRunDetail(runRow, draftRow ? toAgentDraft(draftRow) : null) : { id: runId },
      201
    );
  } catch (err) {
    const message = err instanceof Error ? err.message : 'agent run failed';
    await run(
      c.env.DB,
      `INSERT INTO agent_runs
         (id, user_id, template, mode, status, threshold, repo_count, plan, result,
          draft_id, error, created_at, finished_at)
       VALUES (?, ?, ?, ?, 'failed', ?, 0, '[]', '{}', NULL, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)`,
      [runId, user.id, template, mode, threshold, message.slice(0, 500)]
    ).catch(() => undefined);
    console.error('agent run failed:', err);
    return c.json({ error: 'agent_failed', runId, message: message.slice(0, 200) }, 500);
  }
});

// ── 执行记录 ────────────────────────────────────────────────────

agent.get('/runs', async (c) => {
  const user = c.get('user');
  if (!user) return c.json({ error: 'unauthorized' }, 401);

  const limit = Math.min(100, Math.max(1, Number.parseInt(c.req.query('limit') ?? '20', 10) || 20));
  const offset = Math.min(10000, Math.max(0, Number.parseInt(c.req.query('offset') ?? '0', 10) || 0));
  const status = c.req.query('status')?.trim() ?? '';

  const where = ['user_id = ?'];
  const params: Array<string | number> = [user.id];
  if (status === 'completed' || status === 'failed') {
    where.push('status = ?');
    params.push(status);
  }
  const whereSql = where.join(' AND ');

  const [rows, total] = await Promise.all([
    all<AgentRunRow>(
      c.env.DB,
      `SELECT * FROM agent_runs WHERE ${whereSql} ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?`,
      [...params, limit, offset]
    ),
    count(c.env.DB, `SELECT COUNT(*) AS n FROM agent_runs WHERE ${whereSql}`, params),
  ]);

  return c.json({ items: rows.map(toAgentRunSummary), total });
});

agent.get('/runs/:id', async (c) => {
  const user = c.get('user');
  if (!user) return c.json({ error: 'unauthorized' }, 401);

  const row = await first<AgentRunRow>(c.env.DB, 'SELECT * FROM agent_runs WHERE id = ? AND user_id = ?', [
    c.req.param('id'),
    user.id,
  ]);
  if (!row) return c.json({ error: 'not_found' }, 404);

  let draft: AgentDraft | null = null;
  if (row.draft_id) {
    const draftRow = await first<AgentDraftRow>(
      c.env.DB,
      'SELECT * FROM agent_drafts WHERE id = ? AND user_id = ?',
      [row.draft_id, user.id]
    );
    if (draftRow) draft = toAgentDraft(draftRow);
  }
  return c.json(toAgentRunDetail(row, draft));
});

// ── 草稿 ────────────────────────────────────────────────────────

agent.get('/drafts', async (c) => {
  const user = c.get('user');
  if (!user) return c.json({ error: 'unauthorized' }, 401);

  const limit = Math.min(100, Math.max(1, Number.parseInt(c.req.query('limit') ?? '20', 10) || 20));
  const offset = Math.min(10000, Math.max(0, Number.parseInt(c.req.query('offset') ?? '0', 10) || 0));
  const status = normalizeAgentDraftStatus(c.req.query('status'), 'draft');

  const where = ['user_id = ?'];
  const params: Array<string | number> = [user.id];
  if (status !== 'draft' || c.req.query('status')) {
    where.push('status = ?');
    params.push(status);
  }
  const whereSql = where.join(' AND ');

  const [rows, total] = await Promise.all([
    all<AgentDraftRow>(
      c.env.DB,
      `SELECT * FROM agent_drafts WHERE ${whereSql} ORDER BY updated_at DESC, id DESC LIMIT ? OFFSET ?`,
      [...params, limit, offset]
    ),
    count(c.env.DB, `SELECT COUNT(*) AS n FROM agent_drafts WHERE ${whereSql}`, params),
  ]);

  return c.json({ items: rows.map(toAgentDraft), total });
});

agent.get('/drafts/:id', async (c) => {
  const user = c.get('user');
  if (!user) return c.json({ error: 'unauthorized' }, 401);

  const row = await first<AgentDraftRow>(
    c.env.DB,
    'SELECT * FROM agent_drafts WHERE id = ? AND user_id = ?',
    [c.req.param('id'), user.id]
  );
  if (!row) return c.json({ error: 'not_found' }, 404);
  return c.json(toAgentDraft(row));
});

agent.post('/drafts/:id/status', async (c) => {
  const user = c.get('user');
  if (!user) return c.json({ error: 'unauthorized' }, 401);

  const body = await readBody(c);
  if (!body) return c.json({ error: 'invalid_body' }, 400);
  const status = normalizeAgentDraftStatus(body.status, 'draft');
  if (status !== 'applied' && status !== 'discarded') {
    return c.json({ error: 'invalid_status' }, 400);
  }

  const result = await run(
    c.env.DB,
    `UPDATE agent_drafts SET status = ?, updated_at = CURRENT_TIMESTAMP
      WHERE id = ? AND user_id = ?`,
    [status, c.req.param('id'), user.id]
  );
  if ((result.meta.changes ?? 0) === 0) return c.json({ error: 'not_found' }, 404);

  const row = await first<AgentDraftRow>(
    c.env.DB,
    'SELECT * FROM agent_drafts WHERE id = ? AND user_id = ?',
    [c.req.param('id'), user.id]
  );
  return c.json(row ? toAgentDraft(row) : { status });
});

export default agent;
