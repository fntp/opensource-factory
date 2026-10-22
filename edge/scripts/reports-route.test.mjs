import assert from 'node:assert/strict';
import test from 'node:test';

import { Hono } from 'hono';
import reportsRoutes, { internalReports } from '../src/routes/reports.ts';
import { resolveReportPeriod } from '../src/reports/generate.ts';

const WEEK = resolveReportPeriod('weekly', new Date(), 'current');

function repoRow(overrides = {}) {
  return {
    id: 'acme/new-repo',
    name: 'new-repo',
    description: '本周新收藏的项目',
    html_url: 'https://github.com/acme/new-repo',
    stars: 120,
    language: 'TypeScript',
    category_id: 'c1',
    created_at: `${WEEK.start} 08:00:00`,
    owner: 'acme',
    ...overrides,
  };
}

function seedReport(overrides = {}) {
  return {
    id: 'rpt_weekly_20260101_abc123',
    user_id: 'u1',
    kind: 'weekly',
    period_start: '2026-01-01',
    period_end: '2026-01-07',
    title: '每周精选报告 · 01-01 ~ 01-07',
    summary: '历史报告',
    stats: JSON.stringify({
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
    }),
    sections: '[]',
    markdown: '# 历史报告',
    status: 'empty',
    generated_at: '2026-01-08T00:00:00.000Z',
    ...overrides,
  };
}

function fakeDb({
  repos = [],
  categories = [],
  recommendations = [],
  trending = [],
  tags = [],
  reports = [],
  users = [{ id: 'u1' }],
} = {}) {
  const calls = [];
  const reportRows = [...reports];

  return {
    calls,
    reportRows,
    prepare(sql) {
      return {
        bind(...params) {
          calls.push({ sql, params });
          return {
            async all() {
              if (sql.includes('FROM my_repositories')) return { results: repos };
              if (sql.includes('FROM categories')) return { results: categories };
              if (sql.includes('FROM recommendations')) return { results: recommendations };
              if (sql.includes('FROM trending_snapshots')) return { results: trending };
              if (sql.includes('FROM repo_tags')) return { results: tags };
              if (sql.includes('FROM users')) return { results: users };
              if (sql.includes('FROM curated_reports')) {
                let rows = reportRows.filter((row) => row.user_id === params[0]);
                if (sql.includes(' AND kind = ?')) {
                  rows = rows.filter((row) => row.kind === params[1]);
                }
                const limit = Number(params[params.length - 1]);
                return { results: rows.slice(0, Number.isFinite(limit) ? limit : rows.length) };
              }
              return { results: [] };
            },
            async first() {
              if (sql.includes('FROM curated_reports')) {
                if (sql.includes('period_start = ?')) {
                  return (
                    reportRows.find(
                      (row) =>
                        row.user_id === params[0] &&
                        row.kind === params[1] &&
                        row.period_start === params[2]
                    ) ?? null
                  );
                }
                return reportRows.find((row) => row.id === params[0] && row.user_id === params[1]) ?? null;
              }
              return null;
            },
            async run() {
              if (sql.includes('INSERT INTO curated_reports')) {
                const row = {
                  id: params[0],
                  user_id: params[1],
                  kind: params[2],
                  period_start: params[3],
                  period_end: params[4],
                  title: params[5],
                  summary: params[6],
                  stats: params[7],
                  sections: params[8],
                  markdown: params[9],
                  status: params[10],
                  generated_at: params[11],
                };
                const index = reportRows.findIndex(
                  (item) =>
                    item.user_id === row.user_id &&
                    item.kind === row.kind &&
                    item.period_start === row.period_start
                );
                if (index >= 0) reportRows[index] = row;
                else reportRows.push(row);
              }
              return { meta: { changes: 1 } };
            },
          };
        },
      };
    },
  };
}

function makeApp(db, user = { id: 'u1', login: 'tester' }) {
  const app = new Hono();
  app.use('*', async (c, next) => {
    c.set('user', user);
    await next();
  });
  app.route('/api/reports', reportsRoutes);
  app.route('/api/internal/reports', internalReports);
  return app;
}

function richDb() {
  return fakeDb({
    repos: [repoRow()],
    categories: [{ id: 'c1', name: 'AI' }],
    recommendations: [
      {
        id: 'rec-1',
        repo_id: 'other/good-repo',
        owner: 'other',
        name: 'good-repo',
        description: '值得关注',
        language: 'Go',
        stars: 900,
        score: 0.91,
        reason: '与你收藏的 AI 项目相似',
        url: 'https://github.com/other/good-repo',
        status: 'new',
        created_at: `${WEEK.start} 09:00:00`,
      },
    ],
    trending: [
      {
        snapshot_date: WEEK.start,
        repo_id: 'trend/two',
        owner: 'trend',
        name: 'two',
        html_url: 'https://github.com/trend/two',
        description: '热榜二',
        language: 'Zig',
        stars: 2000,
        star_delta: 500,
        rank: 1,
      },
    ],
    tags: [{ repo_id: 'acme/new-repo', name: 'ai' }],
  });
}

test('GET /api/reports：首次访问惰性生成当前周报，重复访问不重复落库', async () => {
  const db = richDb();
  const app = makeApp(db);

  const res = await app.request('/api/reports?kind=weekly', {}, { DB: db });
  assert.equal(res.status, 200);
  const body = await res.json();
  assert.equal(body.items.length, 1);
  assert.equal(body.items[0].kind, 'weekly');
  assert.equal(body.items[0].stats.newRepos, 1);
  assert.match(body.items[0].title, /^每周精选报告/);
  assert.equal(db.reportRows.length, 1);

  const again = await app.request('/api/reports?kind=weekly', {}, { DB: db });
  assert.equal(again.status, 200);
  const againBody = await again.json();
  assert.equal(againBody.items.length, 1);
  assert.equal(db.reportRows.length, 1);
});

test('GET /api/reports/:id 与 markdown：返回详情并支持下载', async () => {
  const db = richDb();
  const app = makeApp(db);
  const list = await app.request('/api/reports?kind=weekly', {}, { DB: db });
  const listBody = await list.json();
  const id = listBody.items[0].id;

  const detail = await app.request(`/api/reports/${id}`, {}, { DB: db });
  assert.equal(detail.status, 200);
  const report = await detail.json();
  assert.equal(report.sections.length, 4);
  assert.match(report.markdown, /## 数据概览/);

  const markdown = await app.request(`/api/reports/${id}/markdown`, {}, { DB: db });
  assert.equal(markdown.status, 200);
  assert.match(markdown.headers.get('content-type') ?? '', /text\/markdown/);
  assert.match(
    markdown.headers.get('content-disposition') ?? '',
    new RegExp(`openfactory-weekly-${WEEK.start.replace(/-/g, '\\-')}\\.md`)
  );
  assert.match(await markdown.text(), /^# 每周精选报告/);
});

test('报告按用户隔离：他人的报告返回 404', async () => {
  const db = fakeDb({ reports: [seedReport({ user_id: 'u2' })] });
  const app = makeApp(db);

  const detail = await app.request('/api/reports/rpt_weekly_20260101_abc123', {}, { DB: db });
  assert.equal(detail.status, 404);

  const markdown = await app.request(
    '/api/reports/rpt_weekly_20260101_abc123/markdown',
    {},
    { DB: db }
  );
  assert.equal(markdown.status, 404);
});

test('POST /api/reports/generate：按 kind 生成当前周期报告', async () => {
  const db = richDb();
  const app = makeApp(db);

  const res = await app.request(
    '/api/reports/generate',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ kind: 'monthly' }),
    },
    { DB: db }
  );
  assert.equal(res.status, 200);
  const body = await res.json();
  assert.equal(body.report.kind, 'monthly');
  assert.match(body.report.title, /^月度精选报告/);
  assert.equal(db.reportRows.length, 1);
  assert.equal(db.reportRows[0].kind, 'monthly');

  const invalid = await app.request(
    '/api/reports/generate',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ kind: 'daily' }),
    },
    { DB: db }
  );
  assert.equal(invalid.status, 400);
});

test('未登录访问报告接口返回 401', async () => {
  const db = richDb();
  const app = makeApp(db, null);

  const list = await app.request('/api/reports', {}, { DB: db });
  assert.equal(list.status, 401);

  const generate = await app.request(
    '/api/reports/generate',
    { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' },
    { DB: db }
  );
  assert.equal(generate.status, 401);
});

test('内部生成接口：未配置 503 / 令牌错误 401 / 正确令牌批量生成', async () => {
  const db = richDb();
  const app = makeApp(db);

  const notConfigured = await app.request(
    '/api/internal/reports/generate',
    { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{"kind":"weekly"}' },
    { DB: db }
  );
  assert.equal(notConfigured.status, 503);

  const wrong = await app.request(
    '/api/internal/reports/generate',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Internal-Token': 'wrong' },
      body: '{"kind":"weekly"}',
    },
    { DB: db, INTERNAL_TOKEN: 'secret' }
  );
  assert.equal(wrong.status, 401);

  const ok = await app.request(
    '/api/internal/reports/generate',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Internal-Token': 'secret' },
      body: '{"kind":"weekly","mode":"previous"}',
    },
    { DB: db, INTERNAL_TOKEN: 'secret' }
  );
  assert.equal(ok.status, 200);
  const body = await ok.json();
  assert.equal(body.users, 1);
  assert.equal(body.count, 1);
  assert.equal(body.failed, 0);
  assert.equal(db.reportRows.length, 1);
});
