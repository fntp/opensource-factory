/**
 * 我的仓库路由
 * GET /api/repos?q=&categoryId=  当前会话用户的仓库列表（RepoItem[]）
 */
import { Hono } from 'hono';
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
    tags,
    updatedAt: row.updated_at ?? row.synced_at ?? row.created_at ?? null,
    url: row.html_url,
  };
}

repos.get('/', async (c) => {
  const user = c.get('user');
  if (!user) return c.json({ error: 'unauthorized' }, 401);

  const q = c.req.query('q')?.trim() ?? '';
  const categoryId = c.req.query('categoryId')?.trim() ?? '';

  const where: string[] = ['r.user_id = ?'];
  const params: Array<string | number | null> = [user.id];

  if (q) {
    where.push('(r.name LIKE ? OR r.id LIKE ? OR r.description LIKE ?)');
    const like = `%${q}%`;
    params.push(like, like, like);
  }
  if (categoryId) {
    where.push('r.category_id = ?');
    params.push(categoryId);
  }

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
      ORDER BY r.stars DESC, r.updated_at DESC`,
    params
  );

  return c.json(rows.map(toRepoItem));
});

export default repos;
