/**
 * 外部收藏导入路由（M9-03 / REQ-202610-0980）
 *
 * POST /api/import/preview   解析文件并给出新增 / 更新 / 冲突 / 无效统计（不写库）
 * POST /api/import/execute   执行导入：写 my_repositories / categories / tags / repo_tags 与 import_runs
 * GET  /api/import/history   当前用户最近导入记录
 *
 * 所有查询与写入都带 user_id；他人已收藏的仓库按冲突跳过。
 */
import { Hono } from 'hono';
import type { Context } from 'hono';
import type { Env, ImportRunRow, Variables } from '../types';
import { all, first, run } from '../db';
import {
  MAX_CONTENT_LENGTH,
  buildImportPlan,
  normalizeImportFormat,
  parseImportContent,
  previewItems,
  type ImportEntry,
  type ImportPlan,
  type ImportPlanItem,
  type ImportStatus,
} from '../import/parse';

const importRoutes = new Hono<{ Bindings: Env; Variables: Variables }>();

type AppContext = Context<{ Bindings: Env; Variables: Variables }>;

interface ImportBody {
  content?: unknown;
  format?: unknown;
  useFolders?: unknown;
  createCategories?: unknown;
}

interface ImportPreviewResponse {
  format: string;
  total: number;
  new: number;
  update: number;
  conflict: number;
  invalid: number;
  duplicates: number;
  truncated: boolean;
  sample: ReturnType<typeof previewItems>;
  issues: Array<{ row: number; reason: string; value: string }>;
}

interface CategoryRef {
  id: string;
  name: string;
}

function parseBody(body: ImportBody): {
  content: string;
  format: string | null;
  useFolders: boolean;
  createCategories: boolean;
} | null {
  if (typeof body.content !== 'string') return null;
  const content = body.content;
  const format = typeof body.format === 'string' ? body.format.trim().toLowerCase() : null;
  return {
    content,
    format,
    useFolders: body.useFolders !== false,
    createCategories: body.createCategories !== false,
  };
}

function validateFormat(format: string | null): boolean {
  if (!format || format === 'auto') return true;
  return format === 'json' || format === 'csv' || format === 'html';
}

async function loadExisting(db: D1Database): Promise<Array<{ id: string; user_id: string | null }>> {
  return all<{ id: string; user_id: string | null }>(db, 'SELECT id, user_id FROM my_repositories');
}

async function buildPlan(
  c: AppContext,
  content: string,
  format: string | null,
  useFolders: boolean
): Promise<ImportPlan> {
  const user = c.get('user');
  if (!user) throw new Error('unauthorized');
  const parsed = parseImportContent(content, { format, useFolders });
  const existing = await loadExisting(c.env.DB);
  return buildImportPlan(parsed, existing, user.id);
}

/** 名称大小写不敏感地查找分类；create=true 时创建顶级分类。 */
function makeCategoryResolver(
  db: D1Database,
  create: boolean
): { resolve: (name: string | null) => Promise<string | null>; created: () => number } {
  let loaded: CategoryRef[] | null = null;
  let createdCount = 0;

  async function load(): Promise<CategoryRef[]> {
    if (!loaded) {
      loaded = await all<CategoryRef>(db, 'SELECT id, name FROM categories');
    }
    return loaded;
  }

  return {
    async resolve(name) {
      const value = name?.trim();
      if (!value) return null;
      const rows = await load();
      const existing = rows.find((row) => row.name.toLowerCase() === value.toLowerCase());
      if (existing) return existing.id;
      if (!create) return null;
      const id = crypto.randomUUID();
      const sortOrder = rows.length;
      try {
        await run(
          db,
          'INSERT INTO categories (id, name, parent_id, description, sort_order) VALUES (?, ?, NULL, NULL, ?)',
          [id, value, sortOrder]
        );
        rows.push({ id, name: value });
        createdCount += 1;
        return id;
      } catch {
        // 并发创建同名分类：回查一次
        const again = await all<CategoryRef>(
          db,
          'SELECT id, name FROM categories WHERE lower(name) = lower(?) LIMIT 1',
          [value]
        );
        return again[0]?.id ?? null;
      }
    },
    created: () => createdCount,
  };
}

/** 确保标签存在，返回 tag id 与是否新建。 */
async function ensureTag(
  db: D1Database,
  name: string
): Promise<{ id: number; created: boolean }> {
  const existing = await first<{ id: number }>(
    db,
    'SELECT id FROM tags WHERE lower(name) = lower(?) LIMIT 1',
    [name]
  );
  if (existing) return { id: existing.id, created: false };
  try {
    const inserted = await run(db, 'INSERT INTO tags (name, count) VALUES (?, 0)', [name]);
    return { id: Number(inserted.meta.last_row_id ?? 0), created: true };
  } catch {
    const again = await first<{ id: number }>(
      db,
      'SELECT id FROM tags WHERE lower(name) = lower(?) LIMIT 1',
      [name]
    );
    return { id: again?.id ?? 0, created: false };
  }
}

async function applyEntry(
  db: D1Database,
  userId: string,
  entry: ImportPlanItem,
  categoryId: string | null
): Promise<{ changes: number; tagsCreated: number; tagsLinked: number }> {
  const result = await run(
    db,
    `INSERT INTO my_repositories
       (id, platform, name, description, html_url, stars, language, readme_summary,
        category_id, user_id, owner, forks, created_at, updated_at, synced_at)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
     ON CONFLICT(id) DO UPDATE SET
       platform = excluded.platform,
       name = excluded.name,
       description = COALESCE(my_repositories.description, excluded.description),
       html_url = excluded.html_url,
       stars = MAX(COALESCE(my_repositories.stars, 0), excluded.stars),
       language = COALESCE(my_repositories.language, excluded.language),
       readme_summary = COALESCE(my_repositories.readme_summary, excluded.readme_summary),
       category_id = COALESCE(my_repositories.category_id, excluded.category_id),
       user_id = COALESCE(my_repositories.user_id, excluded.user_id),
       owner = excluded.owner,
       forks = MAX(COALESCE(my_repositories.forks, 0), excluded.forks),
       updated_at = CURRENT_TIMESTAMP,
       synced_at = CURRENT_TIMESTAMP
     WHERE my_repositories.user_id IS NULL OR my_repositories.user_id = excluded.user_id`,
    [
      entry.id,
      entry.platform,
      entry.name,
      entry.description,
      entry.url,
      entry.stars,
      entry.language,
      entry.summary,
      categoryId,
      userId,
      entry.owner,
      entry.forks,
    ]
  );

  let tagsCreated = 0;
  let tagsLinked = 0;
  for (const tagName of entry.tags) {
    const tag = await ensureTag(db, tagName);
    if (!tag.id) continue;
    if (tag.created) tagsCreated += 1;
    const linked = await first<{ tag_id: number }>(
      db,
      'SELECT tag_id FROM repo_tags WHERE repo_id = ? AND tag_id = ?',
      [entry.id, tag.id]
    );
    if (linked) continue;
    await run(db, 'INSERT INTO repo_tags (repo_id, tag_id) VALUES (?, ?)', [entry.id, tag.id]);
    await run(db, 'UPDATE tags SET count = COALESCE(count, 0) + 1 WHERE id = ?', [tag.id]);
    tagsLinked += 1;
  }

  return { changes: Number(result.meta.changes ?? 0), tagsCreated, tagsLinked };
}

function runId(): string {
  const random = crypto.randomUUID().replace(/-/g, '').slice(0, 12);
  return `imp_${Date.now().toString(36)}_${random}`;
}

function toRunDto(row: ImportRunRow) {
  return {
    id: row.id,
    format: row.source_format,
    status: row.status,
    total: row.total,
    imported: row.imported,
    updated: row.updated,
    skipped: row.skipped,
    conflicts: row.conflicts,
    invalid: row.invalid,
    categoriesCreated: row.categories_created,
    tagsCreated: row.tags_created,
    createdAt: row.created_at,
  };
}

// ── 预览 ───────────────────────────────────────────────────────

importRoutes.post('/preview', async (c) => {
  const user = c.get('user');
  if (!user) return c.json({ error: 'unauthorized' }, 401);

  let body: ImportBody;
  try {
    body = (await c.req.json<ImportBody>()) ?? {};
  } catch {
    return c.json({ error: 'invalid_json' }, 400);
  }
  const parsedBody = parseBody(body);
  if (!parsedBody) return c.json({ error: 'invalid_body' }, 400);
  if (!validateFormat(parsedBody.format)) {
    return c.json({ error: 'unsupported_format' }, 400);
  }
  const content = parsedBody.content.replace(/^﻿/, '');
  if (!content.trim()) return c.json({ error: 'content_required' }, 400);
  if (content.length > MAX_CONTENT_LENGTH) {
    return c.json({ error: 'content_too_large', limit: MAX_CONTENT_LENGTH }, 413);
  }

  const plan = await buildPlan(c, content, parsedBody.format, parsedBody.useFolders);
  const response: ImportPreviewResponse = {
    format: plan.format,
    total: plan.counts.total,
    new: plan.counts.new,
    update: plan.counts.update,
    conflict: plan.counts.conflict,
    invalid: plan.counts.invalid,
    duplicates: plan.counts.duplicates,
    truncated: plan.truncated,
    sample: previewItems(plan),
    issues: plan.issues,
  };
  return c.json(response);
});

// ── 执行 ───────────────────────────────────────────────────────

importRoutes.post('/execute', async (c) => {
  const user = c.get('user');
  if (!user) return c.json({ error: 'unauthorized' }, 401);

  let body: ImportBody;
  try {
    body = (await c.req.json<ImportBody>()) ?? {};
  } catch {
    return c.json({ error: 'invalid_json' }, 400);
  }
  const parsedBody = parseBody(body);
  if (!parsedBody) return c.json({ error: 'invalid_body' }, 400);
  if (!validateFormat(parsedBody.format)) {
    return c.json({ error: 'unsupported_format' }, 400);
  }
  const content = parsedBody.content.replace(/^﻿/, '');
  if (!content.trim()) return c.json({ error: 'content_required' }, 400);
  if (content.length > MAX_CONTENT_LENGTH) {
    return c.json({ error: 'content_too_large', limit: MAX_CONTENT_LENGTH }, 413);
  }

  const plan = await buildPlan(c, content, parsedBody.format, parsedBody.useFolders);
  const categories = makeCategoryResolver(c.env.DB, parsedBody.createCategories);

  let imported = 0;
  let updated = 0;
  let conflicts = plan.counts.conflict;
  let skipped = plan.counts.conflict;
  let tagsCreated = 0;
  let tagsLinked = 0;

  for (const entry of plan.items) {
    if (entry.status === 'conflict') continue;
    const categoryId = await categories.resolve(entry.category);
    const result = await applyEntry(c.env.DB, user.id, entry, categoryId);
    tagsCreated += result.tagsCreated;
    tagsLinked += result.tagsLinked;
    if (result.changes > 0) {
      if (entry.status === 'new') imported += 1;
      else updated += 1;
    } else {
      conflicts += 1;
      skipped += 1;
    }
  }

  const invalid = plan.counts.invalid;
  const skippedTotal = skipped + invalid;
  const id = runId();

  await run(
    c.env.DB,
    `INSERT INTO import_runs
       (id, user_id, source_format, status, total, imported, updated, skipped, conflicts,
        invalid, categories_created, tags_created, created_at)
     VALUES (?, ?, ?, 'completed', ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)`,
    [
      id,
      user.id,
      plan.format,
      plan.counts.total,
      imported,
      updated,
      skippedTotal,
      conflicts,
      invalid,
      categories.created(),
      tagsCreated,
    ]
  );

  return c.json({
    runId: id,
    format: plan.format,
    total: plan.counts.total,
    imported,
    updated,
    skipped: skippedTotal,
    conflicts,
    invalid,
    duplicates: plan.counts.duplicates,
    categoriesCreated: categories.created(),
    tagsCreated,
    tagsLinked,
    truncated: plan.truncated,
  });
});

// ── 历史 ───────────────────────────────────────────────────────

importRoutes.get('/history', async (c) => {
  const user = c.get('user');
  if (!user) return c.json({ error: 'unauthorized' }, 401);

  const raw = Number(c.req.query('limit'));
  const limit = Number.isFinite(raw) ? Math.max(1, Math.min(50, Math.trunc(raw))) : 10;
  const rows = await all<ImportRunRow>(
    c.env.DB,
    `SELECT * FROM import_runs WHERE user_id = ? ORDER BY created_at DESC, id DESC LIMIT ?`,
    [user.id, limit]
  );
  return c.json({ items: rows.map(toRunDto) });
});

export default importRoutes;
export type { ImportStatus, ImportEntry };
