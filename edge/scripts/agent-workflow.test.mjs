import assert from 'node:assert/strict';
import test from 'node:test';

import { Hono } from 'hono';
import agentRoutes from '../src/routes/agent.ts';

function repoRow(overrides = {}) {
  return {
    id: 'acme/alpha',
    name: 'alpha',
    description: '一个用于测试的仓库',
    language: 'TypeScript',
    stars: 1200,
    readme_summary: 'Alpha 摘要',
    category_name: '开发工具',
    tag_names: 'cli,typescript',
    user_id: 'u1',
    ...overrides,
  };
}

function tagSuggestion(overrides = {}) {
  return {
    id: 'ts_1',
    user_id: 'u1',
    repo_id: 'acme/alpha',
    tag_name: 'ai',
    score: 0.9,
    reason: '描述命中 AI',
    status: 'pending',
    updated_at: '2026-10-01 00:00:00',
    ...overrides,
  };
}

function categorySuggestion(overrides = {}) {
  return {
    id: 'cs_1',
    user_id: 'u1',
    repo_id: 'acme/alpha',
    category_name: '人工智能',
    business_line: 'AI',
    score: 0.82,
    reason: '关键词命中',
    status: 'pending',
    updated_at: '2026-10-01 00:00:00',
    ...overrides,
  };
}

function fakeDb({
  repos = [],
  pendingTags = [],
  pendingCategories = [],
  tags = [{ id: 1, name: 'cli', count: 1 }],
  repoTags = [{ repo_id: 'acme/alpha', tag_id: 1 }],
  categories = [{ id: 'cat_dev', name: '开发工具', sort_order: 10 }],
} = {}) {
  const agentRuns = [];
  const agentDrafts = [];

  function prepare(sql) {
    const norm = sql.replace(/\s+/g, ' ');
    return {
      bind(...params) {
        return {
          async all() {
            if (norm.includes('FROM my_repositories')) {
              let rows = repos.filter((row) => row.user_id === params[0]);
              if (norm.includes('r.id IN (')) {
                const ids = params.slice(1, -1);
                rows = rows.filter((row) => ids.includes(row.id));
              }
              return { results: rows };
            }
            if (norm.includes('FROM tag_suggestions')) {
              const threshold = Number(params[1] ?? 0);
              return {
                results: pendingTags.filter(
                  (row) => row.user_id === params[0] && row.status === 'pending' && row.score >= threshold
                ),
              };
            }
            if (norm.includes('FROM category_suggestions')) {
              const threshold = Number(params[1] ?? 0);
              return {
                results: pendingCategories.filter(
                  (row) => row.user_id === params[0] && row.status === 'pending' && row.score >= threshold
                ),
              };
            }
            if (norm.includes('FROM agent_runs')) {
              const rows = agentRuns.filter((row) => row.user_id === params[0]);
              return { results: rows };
            }
            if (norm.includes('FROM agent_drafts')) {
              const rows = agentDrafts.filter((row) => row.user_id === params[0]);
              return { results: rows };
            }
            return { results: [] };
          },
          async first() {
            if (norm.includes('COUNT(*)')) {
              if (norm.includes('FROM agent_runs')) {
                return { n: agentRuns.filter((row) => row.user_id === params[0]).length };
              }
              if (norm.includes('FROM agent_drafts')) {
                return { n: agentDrafts.filter((row) => row.user_id === params[0]).length };
              }
              return { n: 0 };
            }
            if (norm.includes('FROM agent_runs')) {
              return agentRuns.find((row) => row.id === params[0] && row.user_id === params[1]) ?? null;
            }
            if (norm.includes('FROM agent_drafts')) {
              return agentDrafts.find((row) => row.id === params[0] && row.user_id === params[1]) ?? null;
            }
            if (norm.includes('FROM tags') && !norm.includes('tag_suggestions')) {
              return tags.find((tag) => tag.name.toLowerCase() === String(params[0]).toLowerCase()) ?? null;
            }
            if (norm.includes('FROM categories') && !norm.includes('category_suggestions')) {
              if (norm.includes('MAX(')) {
                return { max: categories.reduce((max, item) => Math.max(max, item.sort_order ?? 0), 0) };
              }
              return (
                categories.find((item) => item.name.toLowerCase() === String(params[0]).toLowerCase()) ??
                null
              );
            }
            if (norm.includes('FROM repo_tags')) {
              return (
                repoTags.find((row) => row.repo_id === params[0] && row.tag_id === params[1]) ?? null
              );
            }
            return null;
          },
          async run() {
            if (norm.includes('INSERT INTO tags')) {
              const id = tags.length + 1;
              tags.push({ id, name: params[0], count: 0 });
              return { meta: { last_row_id: id, changes: 1 } };
            }
            if (norm.includes('INSERT INTO repo_tags')) {
              repoTags.push({ repo_id: params[0], tag_id: params[1] });
              return { meta: { changes: 1 } };
            }
            if (norm.includes('UPDATE tags SET count')) {
              const tag = tags.find((item) => item.id === params[0]);
              if (tag) tag.count = (tag.count ?? 0) + 1;
              return { meta: { changes: 1 } };
            }
            if (norm.includes('INSERT INTO categories')) {
              categories.push({
                id: params[0],
                name: params[1],
                description: params[2],
                sort_order: params[3],
              });
              return { meta: { changes: 1 } };
            }
            if (norm.includes('UPDATE my_repositories')) {
              const repo = repos.find((row) => row.id === params[1] && row.user_id === params[2]);
              if (repo) repo.category_id = params[0];
              return { meta: { changes: repo ? 1 : 0 } };
            }
            if (norm.includes('UPDATE tag_suggestions') || norm.includes('UPDATE category_suggestions')) {
              return { meta: { changes: 1 } };
            }
            if (norm.includes('INSERT INTO agent_drafts')) {
              agentDrafts.push({
                id: params[0],
                user_id: params[1],
                run_id: params[2],
                kind: 'collection_digest',
                title: params[3],
                content: params[4],
                status: 'draft',
                metadata: params[5],
                created_at: '2026-10-22 00:00:00',
                updated_at: '2026-10-22 00:00:00',
              });
              return { meta: { changes: 1 } };
            }
            if (norm.includes('INSERT INTO agent_runs')) {
              agentRuns.push({
                id: params[0],
                user_id: params[1],
                template: params[2],
                mode: params[3],
                status: 'completed',
                threshold: params[4],
                repo_count: params[5],
                plan: params[6],
                result: params[7],
                draft_id: params[8],
                error: null,
                created_at: '2026-10-22 00:00:00',
                finished_at: '2026-10-22 00:00:00',
              });
              return { meta: { changes: 1 } };
            }
            if (norm.includes('UPDATE agent_drafts SET status')) {
              const draft = agentDrafts.find((row) => row.id === params[1] && row.user_id === params[2]);
              if (draft) draft.status = params[0];
              return { meta: { changes: draft ? 1 : 0 } };
            }
            return { meta: { changes: 1 } };
          },
        };
      },
    };
  }

  return { prepare, repos, agentRuns, agentDrafts, tags, repoTags, categories };
}

function makeApp(db, user = { id: 'u1', login: 'tester' }) {
  const app = new Hono();
  app.use('*', async (c, next) => {
    c.set('user', user);
    await next();
  });
  app.route('/api/agent', agentRoutes);
  return app;
}

function seededDb() {
  return fakeDb({
    repos: [repoRow()],
    pendingTags: [tagSuggestion(), tagSuggestion({ id: 'ts_2', tag_name: 'low', score: 0.6 })],
    pendingCategories: [categorySuggestion()],
  });
}

test('GET /api/agent/templates：返回三个模板与默认参数', async () => {
  const db = seededDb();
  const app = makeApp(db);
  const res = await app.request('/api/agent/templates', {}, { DB: db });
  assert.equal(res.status, 200);
  const body = await res.json();
  assert.deepEqual(
    body.items.map((item) => item.key),
    ['organize', 'draft', 'full']
  );
  assert.equal(body.defaults.mode, 'preview');
  assert.equal(body.defaults.threshold, 0.75);
});

test('POST /api/agent/runs：preview 模式只生成计划与草稿，不写入标签 / 分类', async () => {
  const db = seededDb();
  const app = makeApp(db);
  const res = await app.request(
    '/api/agent/runs',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ template: 'full', mode: 'preview', threshold: 0.75 }),
    },
    { DB: db }
  );
  assert.equal(res.status, 201);
  const body = await res.json();
  assert.equal(body.template, 'full');
  assert.equal(body.mode, 'preview');
  assert.equal(body.result.appliedTags.length, 0);
  assert.equal(body.result.appliedCategories.length, 0);
  assert.equal(body.result.pendingTags, 1);
  assert.equal(body.result.pendingCategories, 1);
  assert.equal(body.result.source, 'local');
  assert.deepEqual(
    body.plan.map((step) => step.key),
    ['inventory', 'tags', 'categories', 'draft']
  );
  assert.ok(body.draft.content.startsWith('# '));
  assert.match(body.draft.content, /## 概览/);
  assert.match(body.draft.content, /## 分类精选/);
  assert.match(body.draft.content, /本次未自动应用/);
  assert.equal(db.repoTags.length, 1);
  assert.equal(db.agentRuns.length, 1);
  assert.equal(db.agentDrafts.length, 1);
});

test('POST /api/agent/runs：apply 模式按阈值应用标签与分类建议', async () => {
  const db = seededDb();
  const app = makeApp(db);
  const res = await app.request(
    '/api/agent/runs',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ template: 'full', mode: 'apply', threshold: 0.75 }),
    },
    { DB: db }
  );
  assert.equal(res.status, 201);
  const body = await res.json();
  assert.equal(body.result.appliedTags.length, 1);
  assert.equal(body.result.appliedTags[0].value, 'ai');
  assert.equal(body.result.appliedCategories.length, 1);
  assert.equal(body.result.appliedCategories[0].value, '人工智能');
  assert.ok(db.repoTags.some((row) => row.tag_id === 2));
  const repo = db.repos[0];
  assert.ok(repo.category_id.startsWith('cat_'));
  assert.match(body.draft.content, /应用标签建议 1 条/);
  assert.match(body.draft.content, /应用分类建议 1 条/);
});

test('POST /api/agent/runs：阈值过滤掉低分建议', async () => {
  const db = seededDb();
  const app = makeApp(db);
  const res = await app.request(
    '/api/agent/runs',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ template: 'organize', mode: 'preview', threshold: 0.95 }),
    },
    { DB: db }
  );
  assert.equal(res.status, 201);
  const body = await res.json();
  assert.equal(body.result.pendingTags, 0);
  assert.equal(body.result.pendingCategories, 0);
  assert.equal(body.plan.find((step) => step.key === 'tags').status, 'skipped');
});

test('GET /api/agent/runs 与详情：按用户隔离并回放计划 / 草稿', async () => {
  const db = seededDb();
  const app = makeApp(db);
  const created = await app.request(
    '/api/agent/runs',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ template: 'draft', mode: 'preview' }),
    },
    { DB: db }
  );
  const run = await created.json();

  const list = await app.request('/api/agent/runs', {}, { DB: db });
  assert.equal(list.status, 200);
  const listBody = await list.json();
  assert.equal(listBody.total, 1);
  assert.equal(listBody.items[0].id, run.id);

  const detail = await app.request(`/api/agent/runs/${run.id}`, {}, { DB: db });
  assert.equal(detail.status, 200);
  const detailBody = await detail.json();
  assert.equal(detailBody.draft.id, run.draft.id);
  assert.match(detailBody.draft.content, /# 我的开源收藏精选/);

  const otherApp = makeApp(db, { id: 'u2', login: 'other' });
  const otherList = await otherApp.request('/api/agent/runs', {}, { DB: db });
  assert.equal((await otherList.json()).total, 0);
  const otherDetail = await otherApp.request(`/api/agent/runs/${run.id}`, {}, { DB: db });
  assert.equal(otherDetail.status, 404);
});

test('GET /api/agent/drafts 与状态流转：applied / discarded / 非法值', async () => {
  const db = seededDb();
  const app = makeApp(db);
  const created = await app.request(
    '/api/agent/runs',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ template: 'draft', mode: 'preview' }),
    },
    { DB: db }
  );
  const run = await created.json();
  const draftId = run.draft.id;

  const list = await app.request('/api/agent/drafts?status=draft', {}, { DB: db });
  assert.equal(list.status, 200);
  assert.equal((await list.json()).total, 1);

  const applied = await app.request(
    `/api/agent/drafts/${draftId}/status`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ status: 'applied' }),
    },
    { DB: db }
  );
  assert.equal(applied.status, 200);
  assert.equal((await applied.json()).status, 'applied');

  const invalid = await app.request(
    `/api/agent/drafts/${draftId}/status`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ status: 'published' }),
    },
    { DB: db }
  );
  assert.equal(invalid.status, 400);

  const missing = await app.request(
    '/api/agent/drafts/nope/status',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ status: 'discarded' }),
    },
    { DB: db }
  );
  assert.equal(missing.status, 404);
});

test('未登录访问 Agent 接口返回 401', async () => {
  const db = seededDb();
  const app = makeApp(db, null);
  const res = await app.request('/api/agent/templates', {}, { DB: db });
  assert.equal(res.status, 401);
  const run = await app.request(
    '/api/agent/runs',
    { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' },
    { DB: db }
  );
  assert.equal(run.status, 401);
});
