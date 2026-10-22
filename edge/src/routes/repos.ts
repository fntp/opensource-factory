/**
 * 我的仓库路由
 * GET  /api/repos?q=&categoryId=  当前会话用户的仓库列表（RepoItem[]）
 * POST /api/repos/summaries       VPS 摘要批量回写（X-Internal-Token）
 */
import { Hono } from 'hono';
import type { Env, RepoItem, RepoRow, Variables } from '../types';
import { all, run } from '../db';
import { licenseFromRow } from '../license/compliance';

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
    description: row.description ?? null,
    summary: row.readme_summary ?? null,
    language: row.language ?? null,
    stars: row.stars ?? 0,
    forks: row.forks ?? 0,
    category: row.category_name ?? row.category_id ?? null,
    tags,
    updatedAt: row.updated_at ?? row.synced_at ?? row.created_at ?? null,
    url: row.html_url,
    license: licenseFromRow(row),
  };
}

interface SummaryItem {
  repoId?: unknown;
  summary?: unknown;
}

/**
 * POST /api/repos/summaries
 * VPS 摘要任务批量回写：逐条更新 readme_summary。
 * 仅限内部调用（配置 INTERNAL_TOKEN 时校验 X-Internal-Token）。
 */
repos.post('/summaries', async (c) => {
  const expected = (c.env.INTERNAL_TOKEN ?? '').trim();
  if (expected) {
    const provided = c.req.header('X-Internal-Token') ?? '';
    if (provided !== expected) {
      return c.json({ error: 'unauthorized' }, 401);
    }
  }

  let body: { items?: SummaryItem[] } | null = null;
  try {
    body = await c.req.json<{ items?: SummaryItem[] }>();
  } catch {
    return c.json({ error: 'invalid_json' }, 400);
  }
  if (!body || !Array.isArray(body.items)) {
    return c.json({ error: 'invalid_body', message: 'items 必须是数组' }, 400);
  }

  const items = body.items.slice(0, 500);
  let updated = 0;
  let skipped = 0;
  for (const item of items) {
    const repoId = typeof item.repoId === 'string' ? item.repoId.trim() : '';
    const summary = typeof item.summary === 'string' ? item.summary.trim() : '';
    if (!repoId || !summary) {
      skipped += 1;
      continue;
    }
    const result = await run(
      c.env.DB,
      'UPDATE my_repositories SET readme_summary = ?, synced_at = CURRENT_TIMESTAMP WHERE id = ?',
      [summary.slice(0, 4000), repoId]
    );
    if ((result.meta.changes ?? 0) > 0) {
      updated += 1;
    } else {
      skipped += 1;
    }
  }

  return c.json({ total: items.length, updated, skipped });
});

repos.get('/', async (c) => {
  const user = c.get('user');
  if (!user) return c.json({ error: 'unauthorized' }, 401);

  const q = c.req.query('q')?.trim() ?? '';
  const categoryId = c.req.query('categoryId')?.trim() ?? '';

  const where: string[] = ['r.user_id = ?'];
  const params: Array<string | number | null> = [user.id];

  if (q) {
    where.push('(r.name LIKE ? OR r.id LIKE ? OR r.description LIKE ? OR r.readme_summary LIKE ?)');
    const like = `%${q}%`;
    params.push(like, like, like, like);
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
