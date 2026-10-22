/**
 * 我的仓库路由
 * GET /api/repos?q=&categoryId=&tags=&languages=&starsMin=&starsMax=&updatedAfter=&updatedBefore=&sort=&order=
 * 当前会话用户的仓库列表（RepoItem[]），支持组合筛选与排序。
 */
import { Hono } from 'hono';
import type { CategoryNode } from '../repos-query';
import { buildRepoOrderBy, buildRepoWhere, collectCategoryIds, parseRepoQuery } from '../repos-query';
import type { Env, RepoItem, RepoRow, Variables } from '../types';
import { all } from '../db';

const repos = new Hono<{ Bindings: Env; Variables: Variables }>();

/** 将 DB 行映射为前端 RepoItem 契约 */
export function toRepoItem(row: RepoRow): RepoItem {
  const owner = row.owner ?? row.id.split('/')[0] ?? '';
  const fullName = owner && row.name ? `${owner}/${row.name}` : row.id;
  let tags: string[] = [];
  if (row.tag_names) {
    tags = row.tag_names.split(',').map((t) => t.trim()).filter(Boolean);
  }
  return {
    id: row.id,
    fullName,
    description: row.description ?? row.readme_summary ?? null,
    language: row.language ?? null,
    stars: row.stars ?? 0,
    forks: row.forks ?? 0,
    category: row.category_name ?? row.category_id ?? null,
    categoryId: row.category_id ?? null,
    tags,
    updatedAt: row.updated_at ?? row.synced_at ?? row.created_at ?? null,
    createdAt: row.created_at ?? null,
    url: row.html_url,
  };
}

repos.get('/', async (c) => {
  const user = c.get('user');
  if (!user) return c.json({ error: 'unauthorized' }, 401);

  const parsed = parseRepoQuery(new URL(c.req.url).searchParams);
  if (!parsed.ok) {
    return c.json({ error: 'invalid_query', field: parsed.field, message: parsed.message }, 400);
  }
  const query = parsed.query;

  // 分类过滤默认覆盖全部子孙分类（无限级分类树）。
  let categoryIds: string[] = [];
  if (query.categoryId) {
    const categoryRows = await all<CategoryNode>(
      c.env.DB,
      'SELECT id, parent_id FROM categories'
    );
    categoryIds = collectCategoryIds(categoryRows, query.categoryId);
  }

  const { where, params } = buildRepoWhere(query, user.id, categoryIds);

  const rows = await all<RepoRow>(
    c.env.DB,
    `SELECT r.*,
            cat.name AS category_name,
            (SELECT GROUP_CONCAT(t.name, ',')
               FROM repo_tags rt JOIN tags t ON t.id = rt.tag_id
              WHERE rt.repo_id = r.id) AS tag_names
       FROM my_repositories r
       LEFT JOIN categories cat ON cat.id = r.category_id
      WHERE ${where.join(' AND ')}
      ORDER BY ${buildRepoOrderBy(query.sort, query.order)}`,
    params
  );

  return c.json(rows.map(toRepoItem));
});

export default repos;
