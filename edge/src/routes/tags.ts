/**
 * 标签体系 CRUD
 *
 * GET    /api/tags?q=&sort=name|count&order=asc|desc  标签列表（实时引用计数）
 * POST   /api/tags                                    新建标签 { name }
 * PATCH  /api/tags/:id                                重命名 { name }
 * DELETE /api/tags/:id                                删除标签并解除仓库关联
 * POST   /api/tags/:id/merge                          合并到目标标签 { targetId }
 * POST   /api/tags/recount                            全量重算冗余计数
 *
 * 计数维护：repo_tags 的增删由迁移中的触发器自动重算 tags.count；
 * 写接口在合并 / 删除后再次校准，recount 用于存量修复。
 */
import { Hono } from 'hono';
import type { Env, TagItem, TagRow, Variables } from '../types';
import { all, count, first, run } from '../db';
import {
  escapeLikePattern,
  parseTagId,
  parseTagListQuery,
  validateTagName,
} from '../tags/logic';

const tags = new Hono<{ Bindings: Env; Variables: Variables }>();

function toTagItem(row: TagRow): TagItem {
  return {
    id: Number(row.id),
    name: row.name,
    count: Number(row.count ?? 0),
  };
}

/** 读取单个标签并附带实时引用数 */
async function findTag(db: D1Database, id: number): Promise<TagRow | null> {
  return first<TagRow>(
    db,
    `SELECT t.id, t.name,
            (SELECT COUNT(*) FROM repo_tags rt WHERE rt.tag_id = t.id) AS count
       FROM tags t
      WHERE t.id = ?`,
    [id]
  );
}

/** 按名称大小写不敏感查找（用于唯一性校验） */
async function findTagByName(
  db: D1Database,
  name: string,
  excludeId?: number
): Promise<TagRow | null> {
  const sql = excludeId
    ? `SELECT id, name, count FROM tags WHERE name = ? COLLATE NOCASE AND id <> ?`
    : `SELECT id, name, count FROM tags WHERE name = ? COLLATE NOCASE`;
  const params = excludeId ? [name, excludeId] : [name];
  return first<TagRow>(db, sql, params);
}

/** 统一解析 JSON 请求体 */
async function readJson(c: {
  req: { json: () => Promise<unknown> };
}): Promise<Record<string, unknown> | null> {
  try {
    const body = await c.req.json();
    return body && typeof body === 'object' ? (body as Record<string, unknown>) : null;
  } catch {
    return null;
  }
}

// ── 列表 ────────────────────────────────────────────────────────
tags.get('/', async (c) => {
  if (!c.get('user')) return c.json({ error: 'unauthorized' }, 401);

  const { q, sort, order } = parseTagListQuery(
    c.req.query('q'),
    c.req.query('sort'),
    c.req.query('order')
  );

  const params: Array<string | number | null> = [];
  let where = '';
  if (q) {
    where = `WHERE t.name LIKE ? ESCAPE '\\'`;
    params.push(`%${escapeLikePattern(q)}%`);
  }

  const direction = order === 'asc' ? 'ASC' : 'DESC';
  const orderBy =
    sort === 'name'
      ? `t.name COLLATE NOCASE ${direction}`
      : `count ${direction}, t.name COLLATE NOCASE ASC`;

  const rows = await all<TagRow>(
    c.env.DB,
    `SELECT t.id, t.name,
            (SELECT COUNT(*) FROM repo_tags rt WHERE rt.tag_id = t.id) AS count
       FROM tags t
       ${where}
      ORDER BY ${orderBy}`,
    params
  );

  return c.json({ items: rows.map(toTagItem), total: rows.length });
});

// ── 新建 ────────────────────────────────────────────────────────
tags.post('/', async (c) => {
  if (!c.get('user')) return c.json({ error: 'unauthorized' }, 401);

  const body = await readJson(c);
  if (!body) return c.json({ error: 'invalid_json' }, 400);

  const validation = validateTagName(body.name);
  if (!validation.ok) return c.json({ error: validation.error }, 400);

  const existing = await findTagByName(c.env.DB, validation.name);
  if (existing) {
    return c.json({ error: 'tag_name_exists', existingId: existing.id }, 409);
  }

  const result = await run(c.env.DB, 'INSERT INTO tags (name, count) VALUES (?, 0)', [
    validation.name,
  ]);
  const id = Number(result.meta.last_row_id);

  return c.json({ id, name: validation.name, count: 0 } satisfies TagItem, 201);
});

// ── 全量重算（放在 /:id 之前，避免路径歧义）──────────────────────
tags.post('/recount', async (c) => {
  if (!c.get('user')) return c.json({ error: 'unauthorized' }, 401);

  const total = await count(c.env.DB, 'SELECT COUNT(*) AS n FROM tags');
  const mismatched = await count(
    c.env.DB,
    `SELECT COUNT(*) AS n
       FROM tags t
      WHERE t.count <> (SELECT COUNT(*) FROM repo_tags rt WHERE rt.tag_id = t.id)`
  );
  await run(
    c.env.DB,
    `UPDATE tags
        SET count = (SELECT COUNT(*) FROM repo_tags rt WHERE rt.tag_id = tags.id)`
  );

  return c.json({ total, mismatched });
});

// ── 重命名 ──────────────────────────────────────────────────────
tags.patch('/:id', async (c) => {
  if (!c.get('user')) return c.json({ error: 'unauthorized' }, 401);

  const id = parseTagId(c.req.param('id'));
  if (id === null) return c.json({ error: 'invalid_tag_id' }, 400);

  const body = await readJson(c);
  if (!body) return c.json({ error: 'invalid_json' }, 400);

  const validation = validateTagName(body.name);
  if (!validation.ok) return c.json({ error: validation.error }, 400);

  const current = await findTag(c.env.DB, id);
  if (!current) return c.json({ error: 'tag_not_found' }, 404);

  const conflict = await findTagByName(c.env.DB, validation.name, id);
  if (conflict) {
    return c.json({ error: 'tag_name_exists', existingId: conflict.id }, 409);
  }

  await run(c.env.DB, 'UPDATE tags SET name = ? WHERE id = ?', [validation.name, id]);
  const updated = await findTag(c.env.DB, id);
  return c.json(toTagItem(updated ?? { ...current, name: validation.name }));
});

// ── 删除（解除仓库关联）─────────────────────────────────────────
tags.delete('/:id', async (c) => {
  if (!c.get('user')) return c.json({ error: 'unauthorized' }, 401);

  const id = parseTagId(c.req.param('id'));
  if (id === null) return c.json({ error: 'invalid_tag_id' }, 400);

  const current = await findTag(c.env.DB, id);
  if (!current) return c.json({ error: 'tag_not_found' }, 404);

  const detached = await count(
    c.env.DB,
    'SELECT COUNT(*) AS n FROM repo_tags WHERE tag_id = ?',
    [id]
  );

  await c.env.DB.batch([
    c.env.DB.prepare('DELETE FROM repo_tags WHERE tag_id = ?').bind(id),
    c.env.DB.prepare('DELETE FROM tags WHERE id = ?').bind(id),
  ]);

  return c.json({ deleted: true, id, detached });
});

// ── 合并 ────────────────────────────────────────────────────────
tags.post('/:id/merge', async (c) => {
  if (!c.get('user')) return c.json({ error: 'unauthorized' }, 401);

  const sourceId = parseTagId(c.req.param('id'));
  if (sourceId === null) return c.json({ error: 'invalid_tag_id' }, 400);

  const body = await readJson(c);
  if (!body) return c.json({ error: 'invalid_json' }, 400);

  const targetId = parseTagId(
    typeof body.targetId === 'number' ? String(body.targetId) : String(body.targetId ?? '')
  );
  if (targetId === null) return c.json({ error: 'invalid_merge_target' }, 400);
  if (targetId === sourceId) return c.json({ error: 'invalid_merge_target' }, 400);

  const source = await findTag(c.env.DB, sourceId);
  const target = await findTag(c.env.DB, targetId);
  if (!source || !target) return c.json({ error: 'tag_not_found' }, 404);

  const moved = await count(
    c.env.DB,
    'SELECT COUNT(*) AS n FROM repo_tags WHERE tag_id = ?',
    [sourceId]
  );
  // 两个标签同时挂在同一个仓库上的关联在迁移时会被去重
  const deduplicated = await count(
    c.env.DB,
    `SELECT COUNT(*) AS n
       FROM repo_tags src
       JOIN repo_tags tgt ON tgt.repo_id = src.repo_id
      WHERE src.tag_id = ? AND tgt.tag_id = ?`,
    [sourceId, targetId]
  );

  await c.env.DB.batch([
    c.env.DB.prepare(
      `INSERT OR IGNORE INTO repo_tags (repo_id, tag_id)
       SELECT repo_id, ? FROM repo_tags WHERE tag_id = ?`
    ).bind(targetId, sourceId),
    c.env.DB.prepare('DELETE FROM repo_tags WHERE tag_id = ?').bind(sourceId),
    c.env.DB.prepare('DELETE FROM tags WHERE id = ?').bind(sourceId),
    c.env.DB.prepare(
      `UPDATE tags
          SET count = (SELECT COUNT(*) FROM repo_tags WHERE tag_id = ?)
        WHERE id = ?`
    ).bind(targetId, targetId),
  ]);

  const merged = await findTag(c.env.DB, targetId);

  return c.json({
    sourceId,
    target: toTagItem(merged ?? target),
    moved,
    deduplicated,
  });
});

export default tags;
