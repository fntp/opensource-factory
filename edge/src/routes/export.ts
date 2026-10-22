/**
 * 知识库导出路由（M6-08）
 * GET /api/export/knowledge/summary  当前用户导出统计（登录态）
 * GET /api/export/knowledge          按 format 生成 Markdown / JSON / Obsidian 附件
 *
 * 只读聚合：不新增表、不写 D1；SQL 一律按 user_id 隔离。
 */
import { Hono } from 'hono';
import type { Context } from 'hono';
import type { Env, Variables } from '../types';
import { all } from '../db';
import {
  buildExport,
  buildKnowledgeExport,
  normalizeExportOptions,
  type ExportRepoRow,
} from '../export/build';

const exportRoutes = new Hono<{ Bindings: Env; Variables: Variables }>();

async function loadRows(
  c: Context<{ Bindings: Env; Variables: Variables }>
): Promise<ExportRepoRow[]> {
  const user = c.get('user');
  if (!user) return [];
  return all<ExportRepoRow>(
    c.env.DB,
    `SELECT r.*,
            cat.name AS category_name,
            (SELECT GROUP_CONCAT(t.name, ',')
               FROM repo_tags rt JOIN tags t ON t.id = rt.tag_id
              WHERE rt.repo_id = r.id) AS tag_names
       FROM my_repositories r
       LEFT JOIN categories cat ON cat.id = r.category_id
      WHERE r.user_id = ?
      ORDER BY r.stars DESC, r.id ASC`,
    [user.id]
  );
}

exportRoutes.get('/knowledge/summary', async (c) => {
  const user = c.get('user');
  if (!user) return c.json({ error: 'unauthorized' }, 401);

  const generatedAt = new Date().toISOString();
  const data = buildKnowledgeExport(await loadRows(c), user, generatedAt);

  return c.json({
    totalRepos: data.stats.totalRepos,
    withSummary: data.stats.withSummary,
    categoryCount: data.stats.categories,
    tagCount: data.stats.tags,
    totalStars: data.stats.totalStars,
    generatedAt,
  });
});

exportRoutes.get('/knowledge', async (c) => {
  const user = c.get('user');
  if (!user) return c.json({ error: 'unauthorized' }, 401);

  const options = normalizeExportOptions({
    format: c.req.query('format'),
    includeSummary: c.req.query('includeSummary'),
    groupBy: c.req.query('groupBy'),
  });
  const now = new Date();
  const data = buildKnowledgeExport(await loadRows(c), user, now.toISOString());
  const built = buildExport(data, options, now);

  return new Response(built.body as unknown as BodyInit, {
    status: 200,
    headers: {
      'Content-Type': built.contentType,
      'Content-Disposition': `attachment; filename="${built.fileName}"`,
      'Cache-Control': 'no-store',
      'X-Content-Type-Options': 'nosniff',
    },
  });
});

export default exportRoutes;
