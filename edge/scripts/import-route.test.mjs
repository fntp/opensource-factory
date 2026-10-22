import assert from 'node:assert/strict';
import test from 'node:test';

import { Hono } from 'hono';
import importRoutes from '../src/routes/import.ts';

function fakeDb({ repos = [], categories = [], tags = [], links = [], runs = [] } = {}) {
  const state = { repos, categories, tags, links, runs };
  const calls = [];
  let nextTagId = Math.max(0, ...tags.map((tag) => tag.id)) + 1;

  return {
    state,
    calls,
    prepare(sql) {
      return {
        bind(...params) {
          calls.push({ sql, params });
          return {
            async all() {
              if (sql.includes('FROM my_repositories')) return { results: state.repos };
              if (sql.includes('FROM categories')) {
                if (sql.includes('lower(name)')) {
                  return {
                    results: state.categories.filter(
                      (row) => row.name.toLowerCase() === String(params[0]).toLowerCase()
                    ),
                  };
                }
                return { results: state.categories };
              }
              if (sql.includes('FROM import_runs')) {
                const rows = state.runs
                  .filter((row) => row.user_id === params[0])
                  .sort((a, b) => String(b.created_at).localeCompare(String(a.created_at)));
                return { results: rows.slice(0, Number(params[1]) || 10) };
              }
              return { results: [] };
            },
            async first() {
              if (sql.includes('FROM tags')) {
                const name = String(params[0]).toLowerCase();
                return state.tags.find((tag) => tag.name.toLowerCase() === name) ?? null;
              }
              if (sql.includes('FROM repo_tags')) {
                return (
                  state.links.find(
                    (link) => link.repo_id === params[0] && link.tag_id === params[1]
                  ) ?? null
                );
              }
              return null;
            },
            async run() {
              if (sql.includes('INSERT INTO categories')) {
                state.categories.push({
                  id: params[0],
                  name: params[1],
                  parent_id: null,
                  description: null,
                  sort_order: params[2],
                });
                return { meta: { changes: 1 } };
              }
              if (sql.includes('INSERT INTO tags')) {
                const row = { id: nextTagId, name: params[0], count: 0 };
                nextTagId += 1;
                state.tags.push(row);
                return { meta: { changes: 1, last_row_id: row.id } };
              }
              if (sql.includes('INSERT INTO repo_tags')) {
                state.links.push({ repo_id: params[0], tag_id: params[1] });
                return { meta: { changes: 1 } };
              }
              if (sql.includes('UPDATE tags')) {
                const tag = state.tags.find((item) => item.id === params[0]);
                if (tag) tag.count += 1;
                return { meta: { changes: 1 } };
              }
              if (sql.includes('INSERT INTO my_repositories')) {
                const row = {
                  id: params[0],
                  platform: params[1],
                  name: params[2],
                  description: params[3],
                  html_url: params[4],
                  stars: params[5],
                  language: params[6],
                  readme_summary: params[7],
                  category_id: params[8],
                  user_id: params[9],
                  owner: params[10],
                  forks: params[11],
                };
                const index = state.repos.findIndex((item) => item.id === row.id);
                if (index >= 0) state.repos[index] = { ...state.repos[index], ...row };
                else state.repos.push(row);
                return { meta: { changes: 1 } };
              }
              if (sql.includes('INSERT INTO import_runs')) {
                state.runs.push({
                  id: params[0],
                  user_id: params[1],
                  source_format: params[2],
                  status: 'completed',
                  total: params[3],
                  imported: params[4],
                  updated: params[5],
                  skipped: params[6],
                  conflicts: params[7],
                  invalid: params[8],
                  categories_created: params[9],
                  tags_created: params[10],
                  created_at: '2026-10-22 14:00:00',
                });
                return { meta: { changes: 1 } };
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
  app.route('/api/import', importRoutes);
  const request = app.request.bind(app);
  app.request = (input, init) => request(input, init, { DB: db });
  return app;
}

const JSON_CONTENT = JSON.stringify({
  schema: 'openfactory.knowledge.v1',
  repositories: [
    {
      fullName: 'fresh/one',
      url: 'https://github.com/fresh/one',
      description: '新项目',
      category: 'AI/LLM',
      tags: ['Go', '推理'],
    },
    {
      fullName: 'old/two',
      url: 'https://github.com/old/two',
      category: '工具',
      tags: ['前端'],
    },
    {
      fullName: 'other/three',
      url: 'https://github.com/other/three',
    },
    {
      fullName: 'bad-url',
      url: 'https://example.com/not-a-repo',
    },
  ],
});

function baseDb() {
  return fakeDb({
    repos: [
      { id: 'old/two', user_id: 'u1' },
      { id: 'other/three', user_id: 'u2' },
    ],
    categories: [{ id: 'c-ai', name: 'AI/LLM' }],
    tags: [{ id: 1, name: 'Go', count: 0 }],
    runs: [],
  });
}

test('预览：未登录 401', async () => {
  const app = new Hono();
  app.route('/api/import', importRoutes);
  const res = await app.request('/api/import/preview', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ content: JSON_CONTENT }),
  });
  assert.equal(res.status, 401);
});

test('预览：非法 body / 空内容 / 超大内容 / 非法格式', async () => {
  const app = makeApp(baseDb());
  const invalid = await app.request('/api/import/preview', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ format: 'json' }),
  });
  assert.equal(invalid.status, 400);
  assert.equal((await invalid.json()).error, 'invalid_body');

  const empty = await app.request('/api/import/preview', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ content: '   ' }),
  });
  assert.equal(empty.status, 400);
  assert.equal((await empty.json()).error, 'content_required');

  const huge = await app.request('/api/import/preview', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ content: 'x'.repeat(2_000_001) }),
  });
  assert.equal(huge.status, 413);
  assert.equal((await huge.json()).error, 'content_too_large');

  const badFormat = await app.request('/api/import/preview', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ content: JSON_CONTENT, format: 'xml' }),
  });
  assert.equal(badFormat.status, 400);
  assert.equal((await badFormat.json()).error, 'unsupported_format');
});

test('预览：返回新增 / 更新 / 冲突 / 无效统计与样例', async () => {
  const app = makeApp(baseDb());
  const res = await app.request('/api/import/preview', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ content: JSON_CONTENT }),
  });
  assert.equal(res.status, 200);
  const body = await res.json();
  assert.equal(body.format, 'json');
  assert.equal(body.total, 3);
  assert.equal(body.new, 1);
  assert.equal(body.update, 1);
  assert.equal(body.conflict, 1);
  assert.equal(body.invalid, 1);
  assert.equal(body.sample.length, 3);
  assert.equal(body.sample[0].status, 'new');
  assert.equal(body.sample[1].status, 'update');
  assert.equal(body.sample[2].status, 'conflict');
  assert.equal(body.issues[0].reason, 'invalid_repo');
});

test('执行：写入仓库 / 分类 / 标签并记录历史', async () => {
  const db = baseDb();
  const app = makeApp(db);
  const res = await app.request('/api/import/execute', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ content: JSON_CONTENT, createCategories: true }),
  });
  assert.equal(res.status, 200);
  const body = await res.json();
  assert.equal(body.total, 3);
  assert.equal(body.imported, 1);
  assert.equal(body.updated, 1);
  assert.equal(body.conflicts, 1);
  assert.equal(body.invalid, 1);
  assert.equal(body.skipped, 2);
  assert.equal(body.categoriesCreated, 1);
  assert.equal(body.tagsCreated, 2);
  assert.ok(body.runId.startsWith('imp_'));

  const newRepo = db.state.repos.find((row) => row.id === 'fresh/one');
  assert.equal(newRepo.user_id, 'u1');
  assert.equal(newRepo.category_id, 'c-ai');
  assert.equal(db.state.categories.find((row) => row.name === '工具')?.id !== undefined, true);
  assert.equal(db.state.tags.find((tag) => tag.name === '前端')?.id !== undefined, true);
  assert.equal(db.state.links.filter((link) => link.repo_id === 'fresh/one').length, 2);
  assert.equal(db.state.runs.length, 1);
  assert.equal(db.state.runs[0].user_id, 'u1');
  assert.equal(db.state.runs[0].imported, 1);
});

test('执行两次幂等：不重复建仓库 / 标签 / 关联', async () => {
  const db = baseDb();
  const app = makeApp(db);
  const payload = JSON.stringify({ content: JSON_CONTENT, createCategories: true });
  const first = await app.request('/api/import/execute', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: payload,
  });
  assert.equal(first.status, 200);
  const second = await app.request('/api/import/execute', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: payload,
  });
  assert.equal(second.status, 200);
  const body = await second.json();
  assert.equal(body.imported, 0);
  assert.equal(body.updated, 2);
  assert.equal(body.categoriesCreated, 0);
  assert.equal(body.tagsCreated, 0);
  assert.equal(db.state.repos.filter((row) => row.id === 'fresh/one').length, 1);
  assert.equal(db.state.tags.filter((tag) => tag.name === '前端').length, 1);
  assert.equal(
    db.state.links.filter((link) => link.repo_id === 'fresh/one').length,
    2
  );
  assert.equal(db.state.runs.length, 2);
});

test('执行：createCategories=false 时不新建分类', async () => {
  const db = baseDb();
  const app = makeApp(db);
  const res = await app.request('/api/import/execute', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ content: JSON_CONTENT, createCategories: false }),
  });
  assert.equal(res.status, 200);
  assert.equal(db.state.categories.find((row) => row.name === '工具'), undefined);
  // 已存在的分类仍可复用，只是不新建分类
  const newRepo = db.state.repos.find((row) => row.id === 'fresh/one');
  assert.equal(newRepo.category_id, 'c-ai');
  const oldRepo = db.state.repos.find((row) => row.id === 'old/two');
  assert.equal(oldRepo.category_id, null);
});

test('历史：只返回当前用户记录并支持 limit', async () => {
  const db = baseDb();
  db.state.runs.push(
    {
      id: 'imp_1',
      user_id: 'u1',
      source_format: 'json',
      status: 'completed',
      total: 1,
      imported: 1,
      updated: 0,
      skipped: 0,
      conflicts: 0,
      invalid: 0,
      categories_created: 0,
      tags_created: 0,
      created_at: '2026-10-22 10:00:00',
    },
    {
      id: 'imp_2',
      user_id: 'u2',
      source_format: 'csv',
      status: 'completed',
      total: 2,
      imported: 2,
      updated: 0,
      skipped: 0,
      conflicts: 0,
      invalid: 0,
      categories_created: 0,
      tags_created: 0,
      created_at: '2026-10-22 11:00:00',
    }
  );
  const app = makeApp(db);
  const res = await app.request('/api/import/history?limit=5');
  assert.equal(res.status, 200);
  const body = await res.json();
  assert.equal(body.items.length, 1);
  assert.equal(body.items[0].id, 'imp_1');
  assert.equal(body.items[0].format, 'json');
});
