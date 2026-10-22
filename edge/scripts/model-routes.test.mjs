import assert from 'node:assert/strict';
import test from 'node:test';

import { Hono } from 'hono';
import modelRoutes from '../src/routes/model-routes.ts';

const originalFetch = globalThis.fetch;

test.afterEach(() => {
  globalThis.fetch = originalFetch;
});

function makeApp(user = { id: 'u1', login: 'tester' }) {
  const app = new Hono();
  app.use('*', async (c, next) => {
    if (user) c.set('user', user);
    await next();
  });
  app.route('/api/model-routes', modelRoutes);
  return app;
}

const env = {
  VPS_NODE_URL: 'https://vps.example',
  INTERNAL_TOKEN: 'internal-secret',
};

function captureFetch(body = {}, status = 200) {
  const calls = [];
  globalThis.fetch = async (url, init) => {
    calls.push({ url: String(url), init });
    return new Response(JSON.stringify(body), {
      status,
      headers: { 'content-type': 'application/json' },
    });
  };
  return calls;
}

test('未登录访问模型路由返回 401，且不请求 VPS', async () => {
  const calls = captureFetch();
  const app = makeApp(null);
  const res = await app.request('/api/model-routes', {}, env);
  assert.equal(res.status, 401);
  assert.equal(calls.length, 0);
});

test('VPS 未配置时返回 503', async () => {
  const app = makeApp();
  const res = await app.request('/api/model-routes', {}, { INTERNAL_TOKEN: 'x' });
  assert.equal(res.status, 503);
  const body = await res.json();
  assert.equal(body.error, 'vps_node_not_configured');
});

test('GET 代理总览并透传内部令牌', async () => {
  const calls = captureFetch({ budgetMb: 2048, tasks: [] });
  const app = makeApp();
  const res = await app.request('/api/model-routes', {}, env);

  assert.equal(res.status, 200);
  assert.equal((await res.json()).budgetMb, 2048);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, 'https://vps.example/api/model-routes');
  assert.equal(calls[0].init.headers['X-Internal-Token'], 'internal-secret');
});

test('PUT / DELETE 转发任务路径与 JSON 请求体', async () => {
  const calls = captureFetch({ task: 'summary', modelId: 'qwen2.5-1.5b-q4' });
  const app = makeApp();

  const put = await app.request(
    '/api/model-routes/summary',
    {
      method: 'PUT',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ strategy: 'manual', modelId: 'qwen2.5-1.5b-q4' }),
    },
    env
  );
  assert.equal(put.status, 200);
  assert.equal(calls[0].url, 'https://vps.example/api/model-routes/summary');
  assert.equal(calls[0].init.method, 'PUT');
  assert.deepEqual(JSON.parse(calls[0].init.body), {
    strategy: 'manual',
    modelId: 'qwen2.5-1.5b-q4',
  });

  const del = await app.request('/api/model-routes/summary', { method: 'DELETE' }, env);
  assert.equal(del.status, 200);
  assert.equal(calls[1].url, 'https://vps.example/api/model-routes/summary');
  assert.equal(calls[1].init.method, 'DELETE');
});

test('reset / upgrade / health 代理到对应 VPS 端点', async () => {
  const calls = captureFetch({ ok: true });
  const app = makeApp();

  assert.equal((await app.request('/api/model-routes/reset', { method: 'POST' }, env)).status, 200);
  assert.equal((await app.request('/api/model-routes/health', {}, env)).status, 200);
  assert.equal(
    (
      await app.request(
        '/api/model-routes/upgrade',
        {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ task: 'summary' }),
        },
        env
      )
    ).status,
    200
  );

  assert.deepEqual(
    calls.map((call) => call.url),
    [
      'https://vps.example/api/model-routes/reset',
      'https://vps.example/api/model-routes/health',
      'https://vps.example/api/model-routes/upgrade',
    ]
  );
});

test('VPS 400 / 404 映射为同状态码并保留 detail', async () => {
  captureFetch({ detail: '模型超出预算' }, 400);
  const app = makeApp();
  const bad = await app.request(
    '/api/model-routes/summary',
    {
      method: 'PUT',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ strategy: 'manual', modelId: 'qwen2.5-7b-q4' }),
    },
    env
  );
  assert.equal(bad.status, 400);
  assert.equal((await bad.json()).detail, '模型超出预算');

  captureFetch({ detail: '未知任务' }, 404);
  const missing = await app.request('/api/model-routes/nope', { method: 'DELETE' }, env);
  assert.equal(missing.status, 404);
  assert.equal((await missing.json()).detail, '未知任务');
});

test('VPS 不可达时返回 502', async () => {
  globalThis.fetch = async () => {
    throw new Error('network down');
  };
  const app = makeApp();
  const res = await app.request('/api/model-routes/health', {}, env);
  assert.equal(res.status, 502);
  assert.equal((await res.json()).error, 'vps_node_unreachable');
});

test('非法 JSON 请求体返回 400，不请求 VPS', async () => {
  const calls = captureFetch();
  const app = makeApp();
  const res = await app.request(
    '/api/model-routes/summary',
    { method: 'PUT', headers: { 'content-type': 'application/json' }, body: '{' },
    env
  );
  assert.equal(res.status, 400);
  assert.equal((await res.json()).error, 'invalid_json');
  assert.equal(calls.length, 0);
});
