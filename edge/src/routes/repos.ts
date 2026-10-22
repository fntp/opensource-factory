/**
 * 我的仓库路由
 * GET  /api/repos?q=&categoryId=  当前会话用户的仓库列表（RepoItem[]，含健康度）
 * POST /api/repos/summaries       VPS 摘要批量回写（X-Internal-Token）
 * GET  /api/repos/health          健康度列表与汇总（登录）
 * POST /api/repos/health          VPS 健康度批量回写（X-Internal-Token，M6-05）
 * POST /api/repos/health/refresh  触发 VPS 刷新健康度（登录，M6-05）
 */
import { Hono } from 'hono';
import type { Env, HealthStatus, RepoItem, RepoRow, Variables } from '../types';
import { all, run } from '../db';
import { healthFromRow, summarizeRepoHealth } from '../repos/health';

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
    health: healthFromRow(row),
  };
}

const HEALTH_STATUSES: HealthStatus[] = ['active', 'attention', 'stale', 'archived', 'unknown'];

interface HealthWriteItem {
  repoId?: unknown;
  status?: unknown;
  score?: unknown;
  lastPushAt?: unknown;
  openIssues?: unknown;
  archived?: unknown;
  checkedAt?: unknown;
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

/**
 * GET /api/repos/health
 * 当前用户的仓库健康度列表与汇总，支持 ?status=active|attention|stale|archived|unknown 过滤。
 */
repos.get('/health', async (c) => {
  const user = c.get('user');
  if (!user) return c.json({ error: 'unauthorized' }, 401);

  const statusQuery = (c.req.query('status') ?? '').trim();
  if (statusQuery && !HEALTH_STATUSES.includes(statusQuery as HealthStatus)) {
    return c.json({ error: 'invalid_status' }, 400);
  }

  const rows = await all<RepoRow>(
    c.env.DB,
    'SELECT * FROM my_repositories WHERE user_id = ? ORDER BY stars DESC, updated_at DESC',
    [user.id]
  );
  const items = rows.map((row) => {
    const owner = row.owner ?? row.id.split('/')[0] ?? '';
    return {
      repoId: row.id,
      name: row.name,
      fullName: owner && row.name ? `${owner}/${row.name}` : row.id,
      htmlUrl: row.html_url,
      language: row.language ?? null,
      stars: row.stars ?? 0,
      ...healthFromRow(row),
    };
  });
  const filtered = statusQuery
    ? items.filter((item) => item.status === statusQuery)
    : items;
  return c.json({ summary: summarizeRepoHealth(items), items: filtered });
});

/**
 * POST /api/repos/health
 * VPS 健康度任务批量回写：更新元数据与健康度快照。
 * 仅限内部调用（配置 INTERNAL_TOKEN 时校验 X-Internal-Token）。
 */
repos.post('/health', async (c) => {
  const expected = (c.env.INTERNAL_TOKEN ?? '').trim();
  if (expected) {
    const provided = c.req.header('X-Internal-Token') ?? '';
    if (provided !== expected) {
      return c.json({ error: 'unauthorized' }, 401);
    }
  }

  let body: { items?: HealthWriteItem[] } | null = null;
  try {
    body = await c.req.json<{ items?: HealthWriteItem[] }>();
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
    const rawStatus = typeof item.status === 'string' ? item.status.trim().toLowerCase() : '';
    if (!repoId || !HEALTH_STATUSES.includes(rawStatus as HealthStatus)) {
      skipped += 1;
      continue;
    }
    const status = rawStatus as HealthStatus;
    const score = Number.isFinite(Number(item.score)) ? Math.max(0, Math.min(100, Math.round(Number(item.score)))) : 0;
    const lastPushAt = typeof item.lastPushAt === 'string' ? item.lastPushAt : null;
    const openIssues = Number.isFinite(Number(item.openIssues))
      ? Math.max(0, Math.trunc(Number(item.openIssues)))
      : null;
    const archived = typeof item.archived === 'boolean' ? (item.archived ? 1 : 0) : null;
    const checkedAt =
      typeof item.checkedAt === 'string' && item.checkedAt ? item.checkedAt : new Date().toISOString();

    const result = await run(
      c.env.DB,
      `UPDATE my_repositories
          SET health_status = ?, health_score = ?, health_checked_at = ?,
              open_issues_count = COALESCE(?, open_issues_count),
              archived = COALESCE(?, archived),
              pushed_at = COALESCE(?, pushed_at)
        WHERE id = ?`,
      [status, score, checkedAt, openIssues, archived, lastPushAt, repoId]
    );
    if ((result.meta.changes ?? 0) > 0) {
      updated += 1;
    } else {
      skipped += 1;
    }
  }

  return c.json({ total: items.length, updated, skipped });
});

/**
 * POST /api/repos/health/refresh
 * 触发 VPS 刷新仓库元数据并重算健康度；VPS 未配置时接受请求并给出提示。
 */
repos.post('/health/refresh', async (c) => {
  const user = c.get('user');
  if (!user) return c.json({ error: 'unauthorized' }, 401);

  let body: { repoIds?: unknown; limit?: unknown } = {};
  try {
    body = (await c.req.json<{ repoIds?: unknown; limit?: unknown }>()) ?? {};
  } catch {
    // 允许空 body
  }
  const repoIds = Array.isArray(body.repoIds)
    ? body.repoIds
        .filter((item): item is string => typeof item === 'string' && item.trim().length > 0)
        .map((item) => item.trim())
        .slice(0, 200)
    : [];
  const rawLimit = Number(body.limit);
  const limit = Number.isFinite(rawLimit) ? Math.max(1, Math.min(1000, Math.trunc(rawLimit))) : 100;

  // 只允许刷新当前用户自己的仓库：未指定时取全部（最多 200 个），指定时取交集
  const ownedRows = await all<{ id: string }>(
    c.env.DB,
    'SELECT id FROM my_repositories WHERE user_id = ? ORDER BY stars DESC LIMIT 200',
    [user.id]
  );
  const owned = new Set(ownedRows.map((row) => row.id));
  const requestedIds = repoIds.length
    ? repoIds.filter((repoId) => owned.has(repoId))
    : ownedRows.map((row) => row.id);
  if (requestedIds.length === 0) {
    return c.json({ status: 'accepted', note: 'no repositories to refresh' }, 202);
  }

  const base = c.env.VPS_NODE_URL?.trim();
  if (!base) {
    return c.json({ status: 'accepted', note: 'vps node not configured' }, 202);
  }

  try {
    const res = await fetch(`${base.replace(/\/+$/, '')}/api/repos/health/refresh`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Internal-Token': c.env.INTERNAL_TOKEN ?? '',
      },
      body: JSON.stringify({ repoIds: requestedIds, limit }),
    });
    if (!res.ok) {
      return c.json({ error: 'vps_node_error', upstreamStatus: res.status }, 502);
    }
    const payload = (await res.json().catch(() => ({}))) as { taskId?: string };
    return c.json({ status: 'queued', taskId: payload.taskId ?? null }, 202);
  } catch (err) {
    console.error('repo health refresh forward failed:', err);
    return c.json({ error: 'vps_node_unreachable' }, 502);
  }
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
