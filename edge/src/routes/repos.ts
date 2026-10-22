/**
 * 我的仓库路由
 * GET /api/repos?q=&categoryId=&limit=&offset=  当前会话用户的仓库列表（RepoItem[]）
 */
import { Hono } from 'hono';
import type { Env, RepoItem, RepoRow, Variables } from '../types';
import { all } from '../db';

const repos = new Hono<{ Bindings: Env; Variables: Variables }>();

/** 解析并夹取整数查询参数，非法值回退默认值 */
function intParam(value: string | undefined, fallback: number, min: number, max: number): number {
  const parsed = Number.parseInt(value ?? '', 10);
  if (!Number.isFinite(parsed)) return fallback;
  return Math.min(Math.max(parsed, min), max);
}

/** 转义 LIKE 通配符，配合 SQL 的 ESCAPE '\' 使用 */
function escapeLike(value: string): string {
  return value.replace(/[\\%_]/g, (ch) => `\\${ch}`);
}

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

  // 关键字截断，避免超长 LIKE 模式拖慢查询
  const q = (c.req.query('q') ?? '').trim().slice(0, 100);
  const categoryId = c.req.query('categoryId')?.trim() ?? '';
  const limit = intParam(c.req.query('limit'), 100, 1, 200);
  const offset = intParam(c.req.query('offset'), 0, 0, Number.MAX_SAFE_INTEGER);

  const where: string[] = ['r.user_id = ?'];
  const params: Array<string | number | null> = [user.id];

  if (q) {
    where.push("(r.name LIKE ? ESCAPE '\\' OR r.id LIKE ? ESCAPE '\\' OR r.description LIKE ? ESCAPE '\\')");
    const like = `%${escapeLike(q)}%`;
    params.push(like, like, like);
  }
  if (categoryId) {
    where.push('r.category_id = ?');
    params.push(categoryId);
  }

  // 只取前端契约需要的列：description 在 SQL 内合并 readme_summary，
  // 避免把大字段 readme_summary 原样回传到 Worker。
  const rows = await all<RepoRow>(
    c.env.DB,
    `SELECT r.id,
            r.platform,
            r.name,
            COALESCE(r.description, r.readme_summary) AS description,
            r.html_url,
            r.stars,
            r.language,
            r.category_id,
            r.created_at,
            r.user_id,
            r.owner,
            r.forks,
            r.updated_at,
            r.synced_at,
            cat.name AS category_name,
            (SELECT GROUP_CONCAT(t.name, ',')
               FROM repo_tags rt JOIN tags t ON t.id = rt.tag_id
              WHERE rt.repo_id = r.id) AS tag_names
       FROM my_repositories r
       LEFT JOIN categories cat ON cat.id = r.category_id
      WHERE ${where.join(' AND ')}
      ORDER BY r.stars DESC, r.updated_at DESC
      LIMIT ? OFFSET ?`,
    [...params, limit, offset]
  );

  return c.json(rows.map(toRepoItem));
});

export default repos;
