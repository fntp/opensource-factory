/**
 * 分类 + 标签路由
 *
 * GET    /api/categories           分类列表（扁平，含 parentId / sortOrder / count）+ 标签
 * POST   /api/categories           新建分类
 * PATCH  /api/categories/:id       编辑分类（名称 / 描述 / 父级 / 排序）
 * DELETE /api/categories/:id       删除分类（有子分类或被仓库引用时拒绝）
 * POST   /api/categories/:id/move  移动分类（换父级 + 同级重排）
 *
 * 分类为全局数据；读接口公开，写接口要求登录会话。
 */
import { Hono } from 'hono';
import type { Context } from 'hono';
import type {
  CategoryItem,
  CategoryRow,
  Env,
  TagCountRow,
  Variables,
} from '../types';
import { all, first, run } from '../db';
import {
  assertValidParent,
  CategoryTreeError,
  planCategoryMove,
  sortCategories,
  type CategoryLike,
} from '../categories/tree';

const categories = new Hono<{ Bindings: Env; Variables: Variables }>();

type AppContext = Context<{ Bindings: Env; Variables: Variables }>;
type CategoryRowWithCount = CategoryRow & { count: number };

// ── 通用工具 ────────────────────────────────────────────────────

/** 分类行 → 前端 DTO */
function toItem(row: CategoryRowWithCount): CategoryItem {
  return {
    id: row.id,
    name: row.name,
    parentId: row.parent_id ?? null,
    description: row.description ?? null,
    sortOrder: row.sort_order ?? 0,
    count: Number(row.count ?? 0),
  };
}

/** 分类行 → 纯逻辑模块使用的 camelCase 结构 */
function toLike(row: CategoryRow): CategoryLike {
  return {
    id: row.id,
    name: row.name,
    parentId: row.parent_id ?? null,
    sortOrder: row.sort_order ?? null,
  };
}

/** 读取全部分类（含直接关联的仓库计数） */
async function loadCategoryRows(db: D1Database): Promise<CategoryRowWithCount[]> {
  return all<CategoryRowWithCount>(
    db,
    `SELECT c.*, COUNT(r.id) AS count
       FROM categories c
       LEFT JOIN my_repositories r ON r.category_id = c.id
      GROUP BY c.id`
  );
}

/** 安全解析 JSON 请求体 */
async function readBody(c: AppContext): Promise<Record<string, unknown> | null> {
  try {
    const body = (await c.req.json()) as unknown;
    if (!body || typeof body !== 'object' || Array.isArray(body)) return null;
    return body as Record<string, unknown>;
  } catch {
    return null;
  }
}

/** 名称：去空格后 1–100 字符 */
function parseName(value: unknown): string | null {
  if (typeof value !== 'string') return null;
  const name = value.trim();
  if (name.length < 1 || name.length > 100) return null;
  return name;
}

/** 描述：允许 null / 空串（存 null），最长 500 字符 */
function parseDescription(
  value: unknown
): { ok: true; value: string | null } | { ok: false } {
  if (value === null || value === undefined) return { ok: true, value: null };
  if (typeof value !== 'string') return { ok: false };
  const text = value.trim();
  if (text.length > 500) return { ok: false };
  return { ok: true, value: text.length > 0 ? text : null };
}

/** 父级：null / 空串表示顶级 */
function parseParentId(
  value: unknown
): { ok: true; value: string | null } | { ok: false } {
  if (value === null || value === undefined || value === '') {
    return { ok: true, value: null };
  }
  if (typeof value !== 'string') return { ok: false };
  const id = value.trim();
  if (id.length === 0 || id.length > 100) return { ok: false };
  return { ok: true, value: id };
}

/** 排序位置：0–100000 的整数 */
function parseSortOrder(value: unknown): { ok: true; value: number } | { ok: false } {
  if (typeof value !== 'number' || !Number.isInteger(value)) return { ok: false };
  if (value < 0 || value > 100000) return { ok: false };
  return { ok: true, value };
}

/** 同一父级下是否已有同名分类（大小写不敏感） */
async function hasSiblingName(
  db: D1Database,
  parentId: string | null,
  name: string,
  excludeId?: string
): Promise<boolean> {
  const params: Array<string | null> = [parentId, name];
  let sql = 'SELECT id FROM categories WHERE parent_id IS ? AND lower(name) = lower(?)';
  if (excludeId) {
    sql += ' AND id != ?';
    params.push(excludeId);
  }
  const row = await first<{ id: string }>(db, sql, params);
  return row !== null;
}

/** 树逻辑错误 → HTTP 响应 */
function treeError(c: AppContext, err: unknown) {
  if (err instanceof CategoryTreeError) {
    const status =
      err.code === 'category_not_found' ? 404 : err.code === 'category_cycle' ? 409 : 400;
    return c.json({ error: err.code }, status);
  }
  throw err;
}

// ── 列表 ────────────────────────────────────────────────────────

categories.get('/', async (c) => {
  const rows = await loadCategoryRows(c.env.DB);

  const tagRows = await all<TagCountRow>(
    c.env.DB,
    `SELECT name, count FROM tags ORDER BY count DESC, name ASC`
  );

  return c.json({
    categories: sortCategories(rows.map(toItem)),
    tags: tagRows.map((row) => ({
      name: row.name,
      count: row.count ?? 0,
    })),
  });
});

// ── 新建 ────────────────────────────────────────────────────────

categories.post('/', async (c) => {
  if (!c.get('user')) return c.json({ error: 'unauthorized' }, 401);

  const body = await readBody(c);
  if (!body) return c.json({ error: 'invalid_body' }, 400);

  const name = parseName(body.name);
  if (!name) return c.json({ error: 'invalid_name' }, 400);

  const parent = parseParentId(body.parentId);
  if (!parent.ok) return c.json({ error: 'invalid_parent' }, 400);

  const description = parseDescription(body.description);
  if (!description.ok) return c.json({ error: 'invalid_description' }, 400);

  const sortOrderInput =
    body.sortOrder === undefined ? null : parseSortOrder(body.sortOrder);
  if (sortOrderInput && !sortOrderInput.ok) {
    return c.json({ error: 'invalid_sort_order' }, 400);
  }

  const rows = await loadCategoryRows(c.env.DB);
  if (parent.value !== null && !rows.some((row) => row.id === parent.value)) {
    return c.json({ error: 'invalid_parent' }, 400);
  }
  if (await hasSiblingName(c.env.DB, parent.value, name)) {
    return c.json({ error: 'category_name_exists' }, 409);
  }

  const id = crypto.randomUUID();
  const statements: D1PreparedStatement[] = [];
  let sortOrder: number;

  if (sortOrderInput) {
    sortOrder = sortOrderInput.value;
    statements.push(
      c.env.DB.prepare(
        `UPDATE categories
            SET sort_order = COALESCE(sort_order, 0) + 1
          WHERE parent_id IS ? AND COALESCE(sort_order, 0) >= ?`
      ).bind(parent.value, sortOrder)
    );
  } else {
    const siblings = rows.filter((row) => (row.parent_id ?? null) === parent.value);
    sortOrder = siblings.length;
  }

  statements.push(
    c.env.DB.prepare(
      `INSERT INTO categories (id, name, parent_id, description, sort_order)
       VALUES (?, ?, ?, ?, ?)`
    ).bind(id, name, parent.value, description.value, sortOrder)
  );
  await c.env.DB.batch(statements);

  return c.json(
    toItem({
      id,
      name,
      parent_id: parent.value,
      description: description.value,
      sort_order: sortOrder,
      count: 0,
    }),
    201
  );
});

// ── 编辑 ────────────────────────────────────────────────────────

categories.patch('/:id', async (c) => {
  if (!c.get('user')) return c.json({ error: 'unauthorized' }, 401);

  const id = c.req.param('id');
  const body = await readBody(c);
  if (!body) return c.json({ error: 'invalid_body' }, 400);

  const rows = await loadCategoryRows(c.env.DB);
  const existing = rows.find((row) => row.id === id);
  if (!existing) return c.json({ error: 'category_not_found' }, 404);

  let name = existing.name;
  if ('name' in body) {
    const parsed = parseName(body.name);
    if (!parsed) return c.json({ error: 'invalid_name' }, 400);
    name = parsed;
  }

  let description = existing.description;
  if ('description' in body) {
    const parsed = parseDescription(body.description);
    if (!parsed.ok) return c.json({ error: 'invalid_description' }, 400);
    description = parsed.value;
  }

  let parentId = existing.parent_id ?? null;
  const parentProvided = 'parentId' in body;
  if (parentProvided) {
    const parsed = parseParentId(body.parentId);
    if (!parsed.ok) return c.json({ error: 'invalid_parent' }, 400);
    parentId = parsed.value;
  }

  let sortOrder: number | null = null;
  if ('sortOrder' in body) {
    const parsed = parseSortOrder(body.sortOrder);
    if (!parsed.ok) return c.json({ error: 'invalid_sort_order' }, 400);
    sortOrder = parsed.value;
  }

  try {
    assertValidParent(rows.map(toLike), id, parentId);
  } catch (err) {
    return treeError(c, err);
  }

  const siblingNameChanged = name !== existing.name || parentId !== (existing.parent_id ?? null);
  if (
    siblingNameChanged &&
    (await hasSiblingName(c.env.DB, parentId, name, id))
  ) {
    return c.json({ error: 'category_name_exists' }, 409);
  }

  // 仅当显式给了 sortOrder，或父级确实变化时才重排；
  // 前端编辑表单会带上未变化的 parentId，不能因此把分类挪到同级末尾。
  const reposition =
    sortOrder !== null || (parentProvided && parentId !== (existing.parent_id ?? null));
  if (!reposition) {
    await run(c.env.DB, 'UPDATE categories SET name = ?, description = ? WHERE id = ?', [
      name,
      description,
      id,
    ]);
    return c.json(toItem({ ...existing, name, description }));
  }

  // 目标组：同父级下除自己外的兄弟，按当前顺序排列
  const targetSiblings = sortCategories(
    rows
      .filter((row) => (row.parent_id ?? null) === parentId && row.id !== id)
      .map(toLike)
  );
  const insertAt =
    sortOrder === null ? targetSiblings.length : Math.min(sortOrder, targetSiblings.length);
  const targetOrder = [
    ...targetSiblings.slice(0, insertAt).map((row) => row.id),
    id,
    ...targetSiblings.slice(insertAt).map((row) => row.id),
  ];

  const statements: D1PreparedStatement[] = [
    c.env.DB.prepare(
      `UPDATE categories
          SET name = ?, description = ?, parent_id = ?, sort_order = ?
        WHERE id = ?`
    ).bind(name, description, parentId, targetOrder.indexOf(id), id),
  ];

  for (const [index, siblingId] of targetOrder.entries()) {
    if (siblingId === id) continue;
    statements.push(
      c.env.DB.prepare('UPDATE categories SET sort_order = ? WHERE id = ?').bind(index, siblingId)
    );
  }

  // 换父级时归一化原父级下的剩余兄弟
  if ((existing.parent_id ?? null) !== parentId) {
    const sourceOrder = sortCategories(
      rows
        .filter(
          (row) => (row.parent_id ?? null) === (existing.parent_id ?? null) && row.id !== id
        )
        .map(toLike)
    );
    sourceOrder.forEach((row, index) => {
      statements.push(
        c.env.DB.prepare('UPDATE categories SET sort_order = ? WHERE id = ?').bind(index, row.id)
      );
    });
  }

  await c.env.DB.batch(statements);

  return c.json(
    toItem({
      ...existing,
      name,
      description,
      parent_id: parentId,
      sort_order: targetOrder.indexOf(id),
    })
  );
});

// ── 删除 ────────────────────────────────────────────────────────

categories.delete('/:id', async (c) => {
  if (!c.get('user')) return c.json({ error: 'unauthorized' }, 401);

  const id = c.req.param('id');
  const rows = await loadCategoryRows(c.env.DB);
  const existing = rows.find((row) => row.id === id);
  if (!existing) return c.json({ error: 'category_not_found' }, 404);

  const childCount = rows.filter((row) => row.parent_id === id).length;
  if (childCount > 0) {
    return c.json({ error: 'category_has_children', children: childCount }, 409);
  }

  const repoCount = Number(existing.count ?? 0);
  if (repoCount > 0) {
    return c.json({ error: 'category_in_use', repos: repoCount }, 409);
  }

  const statements: D1PreparedStatement[] = [
    c.env.DB.prepare('DELETE FROM categories WHERE id = ?').bind(id),
  ];
  const remaining = sortCategories(
    rows
      .filter(
        (row) => (row.parent_id ?? null) === (existing.parent_id ?? null) && row.id !== id
      )
      .map(toLike)
  );
  remaining.forEach((row, index) => {
    statements.push(
      c.env.DB.prepare('UPDATE categories SET sort_order = ? WHERE id = ?').bind(index, row.id)
    );
  });
  await c.env.DB.batch(statements);

  return c.body(null, 204);
});

// ── 移动 / 重排 ─────────────────────────────────────────────────

categories.post('/:id/move', async (c) => {
  if (!c.get('user')) return c.json({ error: 'unauthorized' }, 401);

  const id = c.req.param('id');
  const body = await readBody(c);
  if (!body) return c.json({ error: 'invalid_body' }, 400);

  const rows = await loadCategoryRows(c.env.DB);
  const existing = rows.find((row) => row.id === id);
  if (!existing) return c.json({ error: 'category_not_found' }, 404);

  const parent = 'parentId' in body ? parseParentId(body.parentId) : { ok: true as const, value: existing.parent_id ?? null };
  if (!parent.ok) return c.json({ error: 'invalid_parent' }, 400);

  let beforeId: string | null = null;
  if ('beforeId' in body && body.beforeId !== null && body.beforeId !== '') {
    if (typeof body.beforeId !== 'string' || body.beforeId.length > 100) {
      return c.json({ error: 'invalid_before' }, 400);
    }
    beforeId = body.beforeId.trim();
  }

  let plan;
  try {
    plan = planCategoryMove(rows.map(toLike), id, parent.value, beforeId);
  } catch (err) {
    return treeError(c, err);
  }

  const statements: D1PreparedStatement[] = [
    c.env.DB.prepare('UPDATE categories SET parent_id = ?, sort_order = ? WHERE id = ?').bind(
      plan.parentId,
      plan.targetOrder.indexOf(id),
      id
    ),
  ];
  for (const [index, siblingId] of plan.targetOrder.entries()) {
    if (siblingId === id) continue;
    statements.push(
      c.env.DB.prepare('UPDATE categories SET sort_order = ? WHERE id = ?').bind(index, siblingId)
    );
  }
  if (plan.sourceParentId !== plan.parentId) {
    plan.sourceOrder.forEach((siblingId, index) => {
      statements.push(
        c.env.DB.prepare('UPDATE categories SET sort_order = ? WHERE id = ?').bind(index, siblingId)
      );
    });
  }

  await c.env.DB.batch(statements);

  return c.json(
    toItem({
      ...existing,
      parent_id: plan.parentId,
      sort_order: plan.targetOrder.indexOf(id),
    })
  );
});

export default categories;
