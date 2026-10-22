/**
 * 内部一致性快照接口测试（node:test，无额外依赖）。
 * 运行：npm run test:consistency
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { Hono } from 'hono';
import consistency from '../src/routes/consistency.ts';

function makeDb(rowsByTable) {
  return {
    prepare(sql) {
      let params = [];
      const statement = {
        bind(...args) {
          params = args;
          return statement;
        },
        async first() {
          const table = /FROM\s+(\w+)/.exec(sql)?.[1] ?? '';
          return { n: (rowsByTable[table] ?? []).length };
        },
        async all() {
          const table = /FROM\s+(\w+)/.exec(sql)?.[1] ?? '';
          const [limit, offset] = params;
          return { results: (rowsByTable[table] ?? []).slice(offset, offset + limit) };
        },
      };
      return statement;
    },
  };
}

function makeApp(rowsByTable = {}) {
  const app = new Hono();
  app.route('/api/internal/consistency', consistency);
  return { app, env: { DB: makeDb(rowsByTable), INTERNAL_TOKEN: 'secret-token' } };
}

test('未配置 INTERNAL_TOKEN 时返回 503', async () => {
  const { app, env } = makeApp();
  const res = await app.request(
    'http://local/api/internal/consistency/snapshot?table=my_repositories',
    {},
    { ...env, INTERNAL_TOKEN: '' }
  );
  assert.equal(res.status, 503);
  assert.equal((await res.json()).error, 'not_configured');
});

test('令牌错误时返回 401', async () => {
  const { app, env } = makeApp();
  const res = await app.request(
    'http://local/api/internal/consistency/snapshot?table=my_repositories',
    { headers: { 'X-Internal-Token': 'wrong' } },
    env
  );
  assert.equal(res.status, 401);
});

test('未知表返回 400 并列出白名单', async () => {
  const { app, env } = makeApp();
  const res = await app.request(
    'http://local/api/internal/consistency/snapshot?table=sessions',
    { headers: { 'X-Internal-Token': 'secret-token' } },
    env
  );
  assert.equal(res.status, 400);
  const body = await res.json();
  assert.equal(body.error, 'unknown_table');
  assert.ok(body.allowed.includes('my_repositories'));
  assert.ok(!body.allowed.includes('sessions'));
});

test('合法请求分页返回行与 hasMore', async () => {
  const rows = [{ id: 'a' }, { id: 'b' }, { id: 'c' }];
  const { app, env } = makeApp({ my_repositories: rows });
  const first = await app.request(
    'http://local/api/internal/consistency/snapshot?table=my_repositories&limit=2&offset=0',
    { headers: { 'X-Internal-Token': 'secret-token' } },
    env
  );
  assert.equal(first.status, 200);
  const firstBody = await first.json();
  assert.equal(firstBody.total, 3);
  assert.equal(firstBody.rows.length, 2);
  assert.equal(firstBody.hasMore, true);
  assert.deepEqual(firstBody.columns.slice(0, 2), ['id', 'platform']);

  const second = await app.request(
    'http://local/api/internal/consistency/snapshot?table=my_repositories&limit=2&offset=2',
    { headers: { 'X-Internal-Token': 'secret-token' } },
    env
  );
  const secondBody = await second.json();
  assert.deepEqual(secondBody.rows, [{ id: 'c' }]);
  assert.equal(secondBody.hasMore, false);
});

test('非法 limit 返回 400', async () => {
  const { app, env } = makeApp();
  const res = await app.request(
    'http://local/api/internal/consistency/snapshot?table=my_repositories&limit=0',
    { headers: { 'X-Internal-Token': 'secret-token' } },
    env
  );
  assert.equal(res.status, 400);
  assert.equal((await res.json()).error, 'invalid_limit');
});
