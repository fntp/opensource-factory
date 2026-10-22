/**
 * 分类 + 标签路由
 * GET /api/categories → {categories:[{id,name,count,description}], tags:[{name,count}]}
 */
import { Hono } from 'hono';
import type { CategoryWithCountRow, Env, TagCountRow, Variables } from '../types';
import { all } from '../db';

const categories = new Hono<{ Bindings: Env; Variables: Variables }>();

categories.get('/', async (c) => {
  const categoryRows = await all<CategoryWithCountRow>(
    c.env.DB,
    `SELECT c.*, COUNT(r.id) AS count
       FROM categories c
       LEFT JOIN my_repositories r ON r.category_id = c.id
      GROUP BY c.id
      ORDER BY c.sort_order ASC, c.name ASC`
  );

  const tagRows = await all<TagCountRow>(
    c.env.DB,
    `SELECT t.name,
            (SELECT COUNT(*) FROM repo_tags rt WHERE rt.tag_id = t.id) AS count
       FROM tags t
      ORDER BY count DESC, t.name ASC`
  );

  return c.json({
    categories: categoryRows.map((row) => ({
      id: row.id,
      name: row.name,
      count: row.count ?? 0,
      description: row.description ?? null,
    })),
    tags: tagRows.map((row) => ({
      name: row.name,
      count: row.count ?? 0,
    })),
  });
});

export default categories;
