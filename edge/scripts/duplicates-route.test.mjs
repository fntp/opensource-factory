import assert from 'node:assert/strict';
import test from 'node:test';

import { Hono } from 'hono';
import duplicatesRoutes from '../src/routes/duplicates.ts';

function repoRow(id, name, description, stars) {
  return {
    id,
    platform: 'github',
    name,
    description,
    html_url: `https://github.com/${id}`,
    stars,
    language: 'TypeScript',
    readme_summary: '',
    category_id: '',
    created_at: null,
    user_id: 'u1',
    owner: id.split('/')[0],
    forks: 0,
    updated_at: null,
    synced_at: null,
  };
}

function fakeDb({ myRows = [], trendingRows = [], dismissRows = [] } = {}) {
  const calls = [];
  return {
    calls,
    prepare(sql) {
      return {
        bind(...params) {
          calls.push({ sql, params });
          return {
            async all() {
              if (sql.includes('FROM my_repositories')) return { results: myRows };
              if (sql.includes('FROM trending_repositories')) return { results: trendingRows };
              if (sql.includes('FROM duplicate_dismissals')) return { results: dismissRows };
              return { results: [] };
            },
            async first() {
              return null;
            },
            async run() {
              return { meta: { changes: 1 } };
            },
          };
        },
      };
    },
  };
}

function makeApp(db) {
  const app = new Hono();
  app.use('*', async (c, next) => {
    c.set('user', { id: 'u1', login: 'tester' });
    await next();
  });
  app.route('/api/duplicates', duplicatesRoutes);
  return app;
}

test('scan 本地兜底：两个同名仓库返回一个簇并水合 D1 字段', async () => {
  const db = fakeDb({
    myRows: [
      repoRow('acme/tenant-admin', 'tenant-admin', '多租户后台', 10),
      repoRow('acme/tenant_admin', 'tenant_admin', '多租户后台模板', 8),
    ],
  });
  const app = makeApp(db);
  const res = await app.request(
    '/api/duplicates/scan',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ scope: 'my' }),
    },
    { DB: db }
  );
  assert.equal(res.status, 200);
  const body = await res.json();
  assert.equal(body.mode, 'local');
  assert.equal(body.scope, 'my');
  assert.equal(body.scanned, 2);
  assert.equal(body.clusters.length, 1);
  assert.match(body.clusters[0].id, /^dup_/);
  assert.equal(body.clusters[0].members[0].source, 'my');
  assert.equal(body.clusters[0].suggestion.keep.source, 'my');
});

test('scan 过滤当前用户已忽略的簇', async () => {
  const myRows = [
    repoRow('acme/tenant-admin', 'tenant-admin', '多租户后台', 10),
    repoRow('acme/tenant_admin', 'tenant_admin', '多租户后台模板', 8),
  ];
  const first = fakeDb({ myRows });
  const firstRes = await makeApp(first).request(
    '/api/duplicates/scan',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ scope: 'my' }),
    },
    { DB: first }
  );
  const firstBody = await firstRes.json();
  const clusterId = firstBody.clusters[0].id;

  const db = fakeDb({
    myRows,
    dismissRows: [{ cluster_key: clusterId }],
  });
  const res = await makeApp(db).request(
    '/api/duplicates/scan',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ scope: 'my' }),
    },
    { DB: db }
  );
  const body = await res.json();
  assert.equal(body.clusters.length, 0);
  assert.equal(body.dismissedCount, 1);
});

test('scan 把 minScore 透传给 VPS，并优先使用 VPS 结果', async () => {
  const db = fakeDb({
    myRows: [repoRow('acme/a', 'a', '项目 A', 10)],
  });
  const originalFetch = globalThis.fetch;
  let captured = null;
  globalThis.fetch = async (url, init) => {
    captured = JSON.parse(init.body);
    return new Response(
      JSON.stringify({
        scanId: 'dup_vps',
        scanned: 1,
        compared: 0,
        thresholds: {
          minScore: 0.9,
          nameThreshold: 0.86,
          descriptionThreshold: 0.75,
          vectorThreshold: 0.88,
          maxRepos: 500,
          maxClusters: 50,
        },
        clusters: [],
      }),
      { status: 200, headers: { 'Content-Type': 'application/json' } }
    );
  };
  try {
    const res = await makeApp(db).request(
      '/api/duplicates/scan',
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ scope: 'my', minScore: 0.9 }),
      },
      { DB: db, VPS_NODE_URL: 'https://vps.example', INTERNAL_TOKEN: 'test-token' }
    );
    assert.equal(res.status, 200);
    const body = await res.json();
    assert.equal(captured.minScore, 0.9);
    assert.equal(captured.myRepoIds[0], 'acme/a');
    assert.equal(body.mode, 'vps');
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('dismiss 写入按用户幂等记录，dismissed 解析 repoIds', async () => {
  const db = fakeDb({
    dismissRows: [
      {
        cluster_key: 'dup_x',
        repo_ids: '["my:acme/a","trending:acme/a"]',
        reason: '误报',
        created_at: '2026-10-22 10:00:00',
      },
    ],
  });
  const app = makeApp(db);
  const post = await app.request(
    '/api/duplicates/dismiss',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ clusterId: 'dup_x', repoIds: ['my:acme/a'], reason: '误报' }),
    },
    { DB: db }
  );
  assert.equal(post.status, 200);
  assert.deepEqual(await post.json(), { dismissed: true, clusterId: 'dup_x' });
  const insert = db.calls.find((call) => call.sql.includes('INSERT INTO duplicate_dismissals'));
  assert.ok(insert);
  assert.equal(insert.params[1], 'u1');
  assert.equal(insert.params[2], 'dup_x');

  const get = await app.request('/api/duplicates/dismissed', {}, { DB: db });
  const body = await get.json();
  assert.equal(body.count, 1);
  assert.deepEqual(body.items[0].repoIds, ['my:acme/a', 'trending:acme/a']);
});
