import assert from 'node:assert/strict';
import test from 'node:test';

import { Hono } from 'hono';
import internalVectors from '../src/routes/internal-vectors.ts';

function makeApp(vectorize) {
  const app = new Hono();
  app.route('/api/internal/vectors', internalVectors);
  return {
    app,
    env: { INTERNAL_TOKEN: 'test-token', VECTORIZE: vectorize },
  };
}

function post(app, env, path, body, token = 'test-token') {
  return app.request(
    `/api/internal/vectors${path}`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Internal-Token': token },
      body: JSON.stringify(body),
    },
    env
  );
}

test('未配置 INTERNAL_TOKEN 时返回 503', async () => {
  const { app } = makeApp({});
  const res = await app.request('/api/internal/vectors/stats', {}, { VECTORIZE: {} });
  assert.equal(res.status, 503);
});

test('令牌错误返回 401', async () => {
  const { app, env } = makeApp({});
  const res = await app.request('/api/internal/vectors/stats', {}, env);
  assert.equal(res.status, 401);
});

test('未绑定 Vectorize 返回 503', async () => {
  const app = new Hono();
  app.route('/api/internal/vectors', internalVectors);
  const res = await app.request(
    '/api/internal/vectors/stats',
    { headers: { 'X-Internal-Token': 'test-token' } },
    { INTERNAL_TOKEN: 'test-token' }
  );
  assert.equal(res.status, 503);
});

test('upsert 批量写入并返回 mutationId', async () => {
  let captured = [];
  const vectorize = {
    upsert: async (vectors) => {
      captured = vectors;
      return { mutationId: 'm-1' };
    },
  };
  const { app, env } = makeApp(vectorize);
  const res = await post(app, env, '/upsert', {
    items: [
      { id: 'v1_a', values: [0.1, 0.2], metadata: { source: 'my', repo_id: 'a/b', dim: 2 } },
      { id: 'v1_b', values: [0.3, 0.4], metadata: { source: 'trending', repo_id: 'c/d', dim: 2 } },
    ],
  });
  assert.equal(res.status, 200);
  const body = await res.json();
  assert.equal(body.upserted, 2);
  assert.equal(body.mutationId, 'm-1');
  assert.equal(captured.length, 2);
  assert.deepEqual(captured[0].metadata, { source: 'my', repo_id: 'a/b', dim: 2 });
});

test('upsert 跳过非法向量并保持同维度', async () => {
  const vectorize = { upsert: async (vectors) => ({ mutationId: `m-${vectors.length}` }) };
  const { app, env } = makeApp(vectorize);
  const res = await post(app, env, '/upsert', {
    items: [
      { id: 'v1_a', values: [0.1, 0.2] },
      { id: 'v1_b', values: [0.1] },
      { id: '', values: [0.1, 0.2] },
      { id: 'v1_c', values: ['x', 0.2] },
    ],
  });
  assert.equal(res.status, 200);
  const body = await res.json();
  assert.equal(body.upserted, 1);
  assert.equal(body.skipped, 3);
});

test('check 返回 found / missing', async () => {
  const vectorize = {
    getByIds: async (ids) => ids.filter((id) => id === 'v1_a').map((id) => ({ id, values: [0.1] })),
  };
  const { app, env } = makeApp(vectorize);
  const res = await post(app, env, '/check', { ids: ['v1_a', 'v1_b'] });
  assert.equal(res.status, 200);
  const body = await res.json();
  assert.deepEqual(body.found, ['v1_a']);
  assert.deepEqual(body.missing, ['v1_b']);
});

test('delete 调用 deleteByIds', async () => {
  let captured = [];
  const vectorize = {
    deleteByIds: async (ids) => {
      captured = ids;
      return { mutationId: 'm-del' };
    },
  };
  const { app, env } = makeApp(vectorize);
  const res = await post(app, env, '/delete', { ids: ['v1_a', 'v1_b'] });
  assert.equal(res.status, 200);
  const body = await res.json();
  assert.equal(body.deleted, 2);
  assert.deepEqual(captured, ['v1_a', 'v1_b']);
});

test('stats 返回索引维度与向量数', async () => {
  const vectorize = {
    describe: async () => ({
      vectorCount: 42,
      dimensions: 1024,
      processedUpToDatetime: 123,
      processedUpToMutation: 'm-1',
    }),
  };
  const { app, env } = makeApp(vectorize);
  const res = await app.request(
    '/api/internal/vectors/stats',
    { headers: { 'X-Internal-Token': 'test-token' } },
    env
  );
  assert.equal(res.status, 200);
  const body = await res.json();
  assert.equal(body.vectorCount, 42);
  assert.equal(body.dimensions, 1024);
});

test('Vectorize 持续失败时返回 502', async () => {
  const vectorize = { upsert: async () => { throw new Error('boom'); } };
  const { app, env } = makeApp(vectorize);
  const res = await post(app, env, '/upsert', { items: [{ id: 'v1_a', values: [0.1, 0.2] }] });
  assert.equal(res.status, 502);
  const body = await res.json();
  assert.equal(body.error, 'vectorize_upsert_failed');
});
