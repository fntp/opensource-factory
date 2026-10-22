/**
 * 精选报告路由（M7-03）。
 *
 * 登录态接口：
 *   GET  /api/reports?kind=all|weekly|monthly&limit=24&ensure=1
 *   GET  /api/reports/:id
 *   GET  /api/reports/:id/markdown
 *   POST /api/reports/generate           { kind: 'weekly' | 'monthly' }
 *
 * 内部接口（X-Internal-Token）：
 *   POST /api/internal/reports/generate  { kind?, userId?, mode? }
 *
 * 报告数据全部来自当前用户可见的 D1 数据（收藏 / 标签 / 推荐 / 热榜快照），
 * 生成结果写入 curated_reports，同一用户 + 周期唯一（幂等 upsert）。
 */
import { Hono } from 'hono';
import type { Context } from 'hono';
import type {
  CuratedReport,
  CuratedReportRow,
  Env,
  ReportKind,
  ReportSection,
  ReportStats,
  ReportSummary,
  Variables,
} from '../types';
import { all, first, run } from '../db';
import { requireInternalToken } from '../security/internal-token';
import {
  buildReport,
  resolveReportPeriod,
  type ReportSourceData,
} from '../reports/generate';

type AppEnv = { Bindings: Env; Variables: Variables };
type AppContext = Context<AppEnv>;

const reports = new Hono<AppEnv>();
export const internalReports = new Hono<AppEnv>();

const DEFAULT_LIMIT = 24;
const MAX_LIMIT = 100;
const MAX_BATCH_USERS = 500;

const INSERT_REPORT_SQL = `INSERT INTO curated_reports
  (id, user_id, kind, period_start, period_end, title, summary,
   stats, sections, markdown, status, generated_at)
  VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
  ON CONFLICT(user_id, kind, period_start) DO UPDATE SET
    period_end = excluded.period_end,
    title = excluded.title,
    summary = excluded.summary,
    stats = excluded.stats,
    sections = excluded.sections,
    markdown = excluded.markdown,
    status = excluded.status,
    generated_at = excluded.generated_at`;

const EMPTY_STATS: ReportStats = {
  totalRepos: 0,
  newRepos: 0,
  totalStars: 0,
  newStars: 0,
  categoryCount: 0,
  languageCount: 0,
  recommendationCount: 0,
  trendingCount: 0,
  topLanguage: null,
  topCategory: null,
};

function normalizeKind(value: unknown, fallback: ReportKind = 'weekly'): ReportKind | null {
  if (value === undefined || value === null || value === '') return fallback;
  const text = String(value).trim().toLowerCase();
  if (text === 'weekly' || text === 'monthly') return text;
  return null;
}

async function readBody(c: AppContext): Promise<Record<string, unknown> | null> {
  try {
    const body = await c.req.json();
    return body && typeof body === 'object' && !Array.isArray(body)
      ? (body as Record<string, unknown>)
      : null;
  } catch {
    return null;
  }
}

function parseJson<T>(value: string | null | undefined, fallback: T): T {
  if (!value) return fallback;
  try {
    const parsed = JSON.parse(value);
    return parsed ?? fallback;
  } catch {
    return fallback;
  }
}

function toReportSummary(row: CuratedReportRow): ReportSummary {
  return {
    id: row.id,
    kind: row.kind === 'monthly' ? 'monthly' : 'weekly',
    title: row.title,
    periodStart: row.period_start,
    periodEnd: row.period_end,
    status: row.status === 'empty' ? 'empty' : 'ready',
    summary: row.summary,
    stats: parseJson<ReportStats>(row.stats, EMPTY_STATS),
    generatedAt: row.generated_at,
  };
}

function toCuratedReport(row: CuratedReportRow): CuratedReport {
  return {
    ...toReportSummary(row),
    sections: parseJson<ReportSection[]>(row.sections, []),
    markdown: row.markdown,
  };
}

/** 读取生成一份报告所需的全部 D1 数据（均按用户隔离）。 */
async function loadReportData(
  db: D1Database,
  userId: string,
  periodStart: string,
  periodEnd: string
): Promise<ReportSourceData> {
  const repos = await all<ReportSourceData['repos'][number]>(
    db,
    `SELECT id, name, description, html_url, stars, language, category_id, created_at, owner
       FROM my_repositories
      WHERE user_id = ?
      ORDER BY stars DESC, created_at DESC
      LIMIT 500`,
    [userId]
  );

  const categories = await all<ReportSourceData['categories'][number]>(
    db,
    'SELECT id, name FROM categories ORDER BY sort_order ASC, name ASC LIMIT 500',
    []
  );

  const recommendations = await all<ReportSourceData['recommendations'][number]>(
    db,
    `SELECT id, user_id, repo_id, owner, name, description, language, stars,
            score, reason, url, status, created_at
       FROM recommendations
      WHERE (user_id = ? OR user_id IS NULL)
      ORDER BY created_at DESC, score DESC
      LIMIT 200`,
    [userId]
  );

  const trending = await all<ReportSourceData['trending'][number]>(
    db,
    `SELECT snapshot_date, repo_id, owner, name, html_url, description,
            language, stars, star_delta, rank
       FROM trending_snapshots
      WHERE snapshot_date >= ? AND snapshot_date <= ?
      ORDER BY snapshot_date DESC, star_delta DESC
      LIMIT 500`,
    [periodStart, periodEnd]
  );

  const tags = await all<{ repo_id: string; name: string }>(
    db,
    `SELECT rt.repo_id AS repo_id, t.name AS name
       FROM repo_tags rt
       JOIN tags t ON t.id = rt.tag_id
      WHERE rt.repo_id IN (SELECT id FROM my_repositories WHERE user_id = ?)
      LIMIT 2000`,
    [userId]
  );

  return { repos, categories, recommendations, trending, tags };
}

/** 生成并持久化一份报告（同一用户 + 周期幂等）。 */
export async function generateReportForUser(
  db: D1Database,
  userId: string,
  kind: ReportKind,
  now: Date = new Date(),
  mode: 'current' | 'previous' = 'current'
): Promise<CuratedReportRow> {
  const period = resolveReportPeriod(kind, now, mode);
  const data = await loadReportData(db, userId, period.start, period.end);
  const report = buildReport({ userId, kind, period, data, generatedAt: now });

  const row: CuratedReportRow = {
    id: report.id,
    user_id: userId,
    kind: report.kind,
    period_start: report.periodStart,
    period_end: report.periodEnd,
    title: report.title,
    summary: report.summary,
    stats: JSON.stringify(report.stats),
    sections: JSON.stringify(report.sections),
    markdown: report.markdown,
    status: report.status,
    generated_at: report.generatedAt,
  };

  await run(db, INSERT_REPORT_SQL, [
    row.id,
    row.user_id,
    row.kind,
    row.period_start,
    row.period_end,
    row.title,
    row.summary,
    row.stats,
    row.sections,
    row.markdown,
    row.status,
    row.generated_at,
  ]);

  return row;
}

/** 报告不存在时才生成（页面首次访问的惰性补齐）。 */
export async function ensureReport(
  db: D1Database,
  userId: string,
  kind: ReportKind,
  now: Date = new Date()
): Promise<CuratedReportRow> {
  const period = resolveReportPeriod(kind, now, 'current');
  const existing = await first<CuratedReportRow>(
    db,
    'SELECT * FROM curated_reports WHERE user_id = ? AND kind = ? AND period_start = ?',
    [userId, kind, period.start]
  );
  if (existing) return existing;
  return generateReportForUser(db, userId, kind, now, 'current');
}

/** 定时任务 / 运维批量生成；单用户失败不影响其他用户。 */
export async function generateReportsForAllUsers(
  db: D1Database,
  kind: ReportKind,
  mode: 'current' | 'previous' = 'previous',
  now: Date = new Date(),
  limit: number = MAX_BATCH_USERS
): Promise<{ users: number; count: number; failed: number }> {
  const users = await all<{ id: string }>(
    db,
    'SELECT id FROM users ORDER BY created_at ASC LIMIT ?',
    [Math.min(Math.max(limit, 1), MAX_BATCH_USERS)]
  );
  let count = 0;
  let failed = 0;
  for (const user of users) {
    try {
      await generateReportForUser(db, user.id, kind, now, mode);
      count += 1;
    } catch (err) {
      failed += 1;
      console.error(`report generation failed (user=${user.id}, kind=${kind}):`, err);
    }
  }
  return { users: users.length, count, failed };
}

// ── 登录态接口 ──────────────────────────────────────────────────

reports.get('/', async (c) => {
  const user = c.get('user');
  if (!user) return c.json({ error: 'unauthorized' }, 401);

  const rawKind = c.req.query('kind') ?? 'all';
  if (!['all', 'weekly', 'monthly'].includes(rawKind)) {
    return c.json({ error: 'invalid_kind' }, 400);
  }

  const rawLimit = Number.parseInt(c.req.query('limit') ?? '', 10);
  const limit = Number.isFinite(rawLimit) && rawLimit > 0 ? Math.min(rawLimit, MAX_LIMIT) : DEFAULT_LIMIT;
  const ensure = c.req.query('ensure') !== '0';

  if (ensure) {
    const kinds: ReportKind[] = rawKind === 'all' ? ['weekly', 'monthly'] : [rawKind as ReportKind];
    for (const kind of kinds) {
      await ensureReport(c.env.DB, user.id, kind);
    }
  }

  const params: Array<string | number> = [user.id];
  let kindSql = '';
  if (rawKind !== 'all') {
    kindSql = ' AND kind = ?';
    params.push(rawKind);
  }
  params.push(limit);

  const rows = await all<CuratedReportRow>(
    c.env.DB,
    `SELECT * FROM curated_reports
      WHERE user_id = ?${kindSql}
      ORDER BY period_start DESC, generated_at DESC
      LIMIT ?`,
    params
  );

  return c.json({ items: rows.map(toReportSummary), total: rows.length });
});

reports.get('/:id/markdown', async (c) => {
  const user = c.get('user');
  if (!user) return c.json({ error: 'unauthorized' }, 401);

  const row = await first<CuratedReportRow>(
    c.env.DB,
    'SELECT * FROM curated_reports WHERE id = ? AND user_id = ?',
    [c.req.param('id'), user.id]
  );
  if (!row) return c.json({ error: 'not_found' }, 404);

  const filename = `openfactory-${row.kind}-${row.period_start}.md`;
  return c.body(row.markdown, 200, {
    'Content-Type': 'text/markdown; charset=utf-8',
    'Content-Disposition': `attachment; filename="${filename}"`,
  });
});

reports.get('/:id', async (c) => {
  const user = c.get('user');
  if (!user) return c.json({ error: 'unauthorized' }, 401);

  const row = await first<CuratedReportRow>(
    c.env.DB,
    'SELECT * FROM curated_reports WHERE id = ? AND user_id = ?',
    [c.req.param('id'), user.id]
  );
  if (!row) return c.json({ error: 'not_found' }, 404);

  return c.json(toCuratedReport(row));
});

reports.post('/generate', async (c) => {
  const user = c.get('user');
  if (!user) return c.json({ error: 'unauthorized' }, 401);

  const body = await readBody(c);
  const kind = normalizeKind(body?.kind);
  if (!kind) return c.json({ error: 'invalid_kind' }, 400);

  const row = await generateReportForUser(c.env.DB, user.id, kind);
  return c.json({ report: toCuratedReport(row) });
});

// ── 内部接口 ────────────────────────────────────────────────────

internalReports.post('/generate', async (c) => {
  const denied = await requireInternalToken(c);
  if (denied) return denied;

  const body = (await readBody(c)) ?? {};
  const kind = normalizeKind(body.kind);
  if (!kind) return c.json({ error: 'invalid_kind' }, 400);
  const mode = body.mode === 'current' ? 'current' : 'previous';

  const userId = typeof body.userId === 'string' ? body.userId.trim() : '';
  if (userId) {
    const row = await generateReportForUser(c.env.DB, userId, kind, new Date(), mode);
    return c.json({ count: 1, failed: 0, reports: [toReportSummary(row)] });
  }

  const result = await generateReportsForAllUsers(c.env.DB, kind, mode);
  return c.json(result);
});

export default reports;
