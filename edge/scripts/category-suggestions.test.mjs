import assert from 'node:assert/strict';
import test from 'node:test';

import { Hono } from 'hono';
import categorySuggestionsRoutes from '../src/routes/category-suggestions.ts';
import {
  clampLimit,
  clampMinScore,
  clampOffset,
  clampPerRepo,
  mergeSuggestions,
  normalizeCategoryName,
  normalizeStatus,
  splitTags,
  stableSuggestionId,
} from '../src/category-suggestions/helpers.ts';
import { suggestCategoriesLocally } from '../src/category-suggestions/rules.ts';

function repoRow(id, name, description, extra = {}) {
  return {
    id,
    name,
    description,
    language: 'Go',
    readme_summary: '',
    tag_names: null,
    category_name: null,
    html_url: `https://github.com/${id}`,
    stars: 10,
    ...extra,
  };
}

function suggestionRow(overrides = {}) {
  return {
    id: 'cs_1',
    user_id: 'u1',
    repo_id: 'acme/pay',
    category_name: '金融 / 支付',
    business_line: 'fintech',
    score: 0.85,
    reason: '名称命中「payment」',
    evidence: 'payment gateway',
    status: 'pending',
    created_at: '2026-10-22 00:00:00',
    updated_at: '2026-10-22 00:00:00',
    ...overrides,
  };
}

function fakeDb({ repos = [], suggestions = [], categories = [] } = {}) {
  const calls = [];
  return {
    calls,
    prepare(sql) {
      return {
        bind(...params) {
          calls.push({ sql, params });
          return {
            async all() {
              if (sql.includes('FROM my_repositories r')) return { results: repos };
              if (sql.includes('FROM category_suggestions s')) {
                return {
                  results: suggestions.map((row) => ({
                    ...row,
                    repo_name: row.repo_id,
                    repo_url: `https://github.com/${row.repo_id}`,
                    summary: '',
                    current_category: null,
                  })),
                };
              }
              if (sql.includes('SELECT status, COUNT(*)')) {
                const counts = new Map();
                for (const row of suggestions) {
                  counts.set(row.status, (counts.get(row.status) ?? 0) + 1);
                }
                return {
                  results: [...counts].map(([status, n]) => ({ status, n })),
                };
              }
              if (sql.includes('SELECT id, name FROM categories')) return { results: categories };
              if (sql.includes('SELECT * FROM category_suggestions')) {
                const ids = params.slice(1);
                return {
                  results: suggestions.filter(
                    (row) => ids.includes(row.id) && row.status === 'pending'
                  ),
                };
              }
              return { results: [] };
            },
            async first() {
              if (sql.includes('COUNT(DISTINCT repo_id)')) {
                return { n: new Set(suggestions.map((row) => row.repo_id)).size };
              }
              if (sql.includes('AVG(score)')) {
                const pending = suggestions.filter((row) => row.status === 'pending');
                return {
                  avg: pending.length
                    ? pending.reduce((sum, row) => sum + row.score, 0) / pending.length
                    : null,
                };
              }
              if (sql.includes('SELECT status FROM category_suggestions')) {
                const [userId, repoId, categoryName] = params;
                return (
                  suggestions.find(
                    (row) =>
                      row.user_id === userId &&
                      row.repo_id === repoId &&
                      row.category_name === categoryName
                  ) ?? null
                );
              }
              if (sql.includes('SELECT id FROM categories')) {
                const name = String(params[0]).toLowerCase();
                return categories.find((row) => row.name.toLowerCase() === name) ?? null;
              }
              if (sql.includes('MAX(sort_order)')) return { max: 10 };
              return null;
            },
            async run() {
              if (sql.includes('UPDATE my_repositories')) return { meta: { changes: 1 } };
              return { meta: { changes: 1 } };
            },
          };
        },
      };
    },
  };
}

function makeApp(db, { user = { id: 'u1', login: 'tester' } } = {}) {
  const app = new Hono();
  app.use('*', async (c, next) => {
    c.set('user', user);
    await next();
  });
  app.route('/api/category-suggestions', categorySuggestionsRoutes);
  return app;
}

test('helpers：参数收敛与状态归一化', () => {
  assert.equal(normalizeStatus(undefined), 'pending');
  assert.equal(normalizeStatus('all'), 'all');
  assert.equal(normalizeStatus('bogus'), null);
  assert.equal(clampLimit('999'), 200);
  assert.equal(clampLimit(0), 1);
  assert.equal(clampPerRepo(99), 5);
  assert.equal(clampMinScore(-1), 0);
  assert.equal(clampOffset(-5), 0);
  assert.equal(normalizeCategoryName('  金融 /   支付 '), '金融 / 支付');
  assert.deepEqual(splitTags('a, b,a'), ['a', 'b']);
});

test('helpers：合并建议去重取高分并降序', () => {
  const merged = mergeSuggestions(
    [{ categoryName: 'A', score: 0.6 }],
    [
      { categoryName: 'a', score: 0.8 },
      { categoryName: 'B', score: 0.7 },
    ]
  );
  assert.equal(merged.length, 2);
  assert.equal(merged[0].categoryName, 'a');
  assert.equal(merged[1].categoryName, 'B');
});

test('helpers：稳定建议 id 与大小写无关', async () => {
  const first = await stableSuggestionId('u1', 'acme/pay', '金融 / 支付');
  const second = await stableSuggestionId('u1', 'acme/pay', ' 金融 / 支付 ');
  assert.equal(first, second);
  assert.match(first, /^cs_[0-9a-f]{32}$/);
  assert.notEqual(first, await stableSuggestionId('u2', 'acme/pay', '金融 / 支付'));
});

test('本地规则：支付仓库首选金融 / 支付', () => {
  const suggestions = suggestCategoriesLocally({
    repoId: 'acme/pay',
    name: 'pay-gateway',
    description: '多渠道 payment gateway，支持支付与对账',
    language: 'Go',
    summary: '',
    tags: ['支付'],
  });
  assert.ok(suggestions.length > 0);
  assert.equal(suggestions[0].categoryName, '金融 / 支付');
  assert.equal(suggestions[0].businessLine, 'fintech');
});

test('GET /api/category-suggestions：返回列表与汇总', async () => {
  const db = fakeDb({
    suggestions: [suggestionRow(), suggestionRow({ id: 'cs_2', status: 'accepted' })],
    categories: [{ id: 'cat_1', name: '金融 / 支付' }],
  });
  const res = await makeApp(db).request('/api/category-suggestions?status=all', {}, { DB: db });
  assert.equal(res.status, 200);
  const body = await res.json();
  assert.equal(body.items.length, 2);
  assert.equal(body.items[0].repoId, 'acme/pay');
  assert.equal(body.summary.total, 2);
  assert.equal(body.summary.pending, 1);
  assert.equal(body.summary.accepted, 1);
  assert.deepEqual(body.categories, [{ id: 'cat_1', name: '金融 / 支付' }]);
});

test('GET /api/category-suggestions：非法状态 400 / 未登录 401', async () => {
  const db = fakeDb();
  const bad = await makeApp(db).request('/api/category-suggestions?status=x', {}, { DB: db });
  assert.equal(bad.status, 400);

  const anonymous = await makeApp(db, { user: null }).request('/api/category-suggestions', {}, { DB: db });
  assert.equal(anonymous.status, 401);
});

test('POST /generate：无 VPS 时本地兜底并写入建议', async () => {
  const db = fakeDb({
    repos: [repoRow('acme/pay', 'pay-gateway', '多渠道 payment gateway，支持支付与对账')],
  });
  const res = await makeApp(db).request(
    '/api/category-suggestions/generate',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ limit: 10 }),
    },
    { DB: db, VPS_NODE_URL: '' }
  );
  assert.equal(res.status, 200);
  const body = await res.json();
  assert.equal(body.scanned, 1);
  assert.equal(body.source, 'local');
  assert.ok(body.suggested >= 1);
  const insert = db.calls.find((call) => call.sql.includes('INSERT INTO category_suggestions'));
  assert.ok(insert);
  assert.equal(insert.params[2], 'acme/pay');
  assert.equal(insert.params[3], '金融 / 支付');
});

test('POST /generate：已忽略的建议不被覆盖', async () => {
  const db = fakeDb({
    repos: [repoRow('acme/pay', 'pay-service', 'payment 支付 对账')],
    suggestions: [suggestionRow({ status: 'dismissed' })],
  });
  const res = await makeApp(db).request(
    '/api/category-suggestions/generate',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ limit: 10 }),
    },
    { DB: db, VPS_NODE_URL: '' }
  );
  assert.equal(res.status, 200);
  const body = await res.json();
  assert.equal(body.suggested, 0);
  assert.equal(
    db.calls.some((call) => call.sql.includes('INSERT INTO category_suggestions')),
    false
  );
});

test('POST /accept：自动建分类并写回仓库分类', async () => {
  const db = fakeDb({ suggestions: [suggestionRow()] });
  const res = await makeApp(db).request(
    '/api/category-suggestions/accept',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ids: ['cs_1'] }),
    },
    { DB: db }
  );
  assert.equal(res.status, 200);
  const body = await res.json();
  assert.equal(body.accepted, 1);
  assert.equal(body.categoriesCreated, 1);
  assert.match(body.items[0].categoryId, /^cat_/);
  assert.ok(
    db.calls.some(
      (call) =>
        call.sql.includes('INSERT INTO categories') && call.params[1] === '金融 / 支付'
    )
  );
  assert.ok(
    db.calls.some(
      (call) =>
        call.sql.includes('UPDATE my_repositories SET category_id') &&
        call.params[1] === 'acme/pay'
    )
  );
  assert.ok(
    db.calls.some(
      (call) =>
        call.sql.includes("SET status = 'accepted'") && call.params[0] === 'cs_1'
    )
  );
});

test('POST /accept：缺少参数 400', async () => {
  const db = fakeDb();
  const res = await makeApp(db).request(
    '/api/category-suggestions/accept',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({}),
    },
    { DB: db }
  );
  assert.equal(res.status, 400);
});

test('POST /dismiss：忽略待确认建议', async () => {
  const db = fakeDb({ suggestions: [suggestionRow()] });
  const res = await makeApp(db).request(
    '/api/category-suggestions/dismiss',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ids: ['cs_1'] }),
    },
    { DB: db }
  );
  assert.equal(res.status, 200);
  const body = await res.json();
  assert.equal(body.dismissed, 1);
  assert.ok(
    db.calls.some(
      (call) =>
        call.sql.includes("SET status = 'dismissed'") && call.params[0] === 'u1'
    )
  );
});

test('POST /dismiss：空 ids 400', async () => {
  const db = fakeDb();
  const res = await makeApp(db).request(
    '/api/category-suggestions/dismiss',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ids: [] }),
    },
    { DB: db }
  );
  assert.equal(res.status, 400);
});
