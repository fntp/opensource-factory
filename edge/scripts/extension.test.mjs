import assert from 'node:assert/strict';
import test from 'node:test';

import { Hono } from 'hono';
import extensionRoutes from '../src/routes/extension.ts';
import {
  generateExtensionToken,
  isExtensionTokenFormat,
  normalizeBookmarkPayload,
  normalizeTokenLabel,
  parseRepoFullName,
  parseRepoUrl,
  tokenHint,
} from '../src/extension/helpers.ts';

function repoRow(overrides = {}) {
  return {
    id: 'acme/demo',
    platform: 'github',
    name: 'demo',
    description: '示例项目',
    html_url: 'https://github.com/acme/demo',
    stars: 12,
    language: 'TypeScript',
    readme_summary: null,
    category_id: null,
    created_at: null,
    user_id: 'u1',
    owner: 'acme',
    forks: 3,
    updated_at: null,
    synced_at: null,
    ...overrides,
  };
}

function fakeDb({ tokenRow = null, userRow = null, repo = null, count = 0, changes = 1 } = {}) {
  const calls = [];
  return {
    calls,
    prepare(sql) {
      return {
        bind(...params) {
          calls.push({ sql, params });
          return {
            async first() {
              if (sql.includes('COUNT(*)')) return { n: count };
              if (sql.includes('FROM extension_tokens WHERE token_hash')) return tokenRow;
              if (sql.includes('FROM users WHERE id')) return userRow;
              if (sql.includes('FROM my_repositories WHERE id')) return repo;
              return null;
            },
            async all() {
              if (sql.includes('FROM extension_tokens')) return { results: tokenRow ? [tokenRow] : [] };
              return { results: [] };
            },
            async run() {
              return { meta: { changes } };
            },
          };
        },
      };
    },
  };
}

function makeApp(db, user = { id: 'u1', login: 'tester', name: 'Tester', avatar_url: null }) {
  const app = new Hono();
  app.use('*', async (c, next) => {
    if (user) c.set('user', user);
    await next();
  });
  app.route('/api/extension', extensionRoutes);
  return app;
}

// ── 纯函数 ──────────────────────────────────────────────────────

test('parseRepoUrl：GitHub 仓库页 / 子页面 / .git / www 均可解析', () => {
  const base = parseRepoUrl('https://github.com/acme/demo');
  assert.deepEqual(base, {
    platform: 'github',
    owner: 'acme',
    name: 'demo',
    fullName: 'acme/demo',
    url: 'https://github.com/acme/demo',
  });
  assert.equal(parseRepoUrl('https://github.com/acme/demo/tree/main/src').fullName, 'acme/demo');
  assert.equal(parseRepoUrl('https://www.github.com/acme/demo.git').fullName, 'acme/demo');
  assert.equal(parseRepoUrl('https://github.com/acme/demo?tab=readme').fullName, 'acme/demo');
});

test('parseRepoUrl：Gitee 可解析，非仓库页 / 保留路径 / 其他站点返回 null', () => {
  assert.equal(parseRepoUrl('https://gitee.com/acme/demo').platform, 'gitee');
  assert.equal(parseRepoUrl('https://github.com/topics/ai'), null);
  assert.equal(parseRepoUrl('https://github.com/settings/profile'), null);
  assert.equal(parseRepoUrl('https://github.com/acme'), null);
  assert.equal(parseRepoUrl('https://gitlab.com/acme/demo'), null);
  assert.equal(parseRepoUrl('not-a-url'), null);
  assert.equal(parseRepoUrl('ftp://github.com/acme/demo'), null);
});

test('parseRepoFullName：合法 owner/repo，拒绝保留名与多段路径', () => {
  assert.deepEqual(parseRepoFullName(' acme/demo.git '), {
    owner: 'acme',
    name: 'demo',
    fullName: 'acme/demo',
  });
  assert.equal(parseRepoFullName('acme/demo/tree'), null);
  assert.equal(parseRepoFullName('marketplace/x'), null);
  assert.equal(parseRepoFullName('/'), null);
});

test('normalizeBookmarkPayload：URL 与 fullName 一致时归一化并截断元数据', () => {
  const result = normalizeBookmarkPayload({
    repo: {
      platform: 'github',
      fullName: 'acme/demo',
      url: 'https://github.com/acme/demo/tree/main',
      description: '  一个   示例\n项目  ',
      language: 'TypeScript',
      stars: '1,234',
      forks: 8,
    },
  });
  assert.equal(result.ok, true);
  assert.equal(result.repo.id, 'acme/demo');
  assert.equal(result.repo.description, '一个 示例 项目');
  assert.equal(result.repo.stars, 1234);
  assert.equal(result.repo.url, 'https://github.com/acme/demo');
});

test('normalizeBookmarkPayload：仅 URL 时推断平台；URL 与 fullName 不一致报错', () => {
  const fromUrl = normalizeBookmarkPayload({
    repo: { url: 'https://gitee.com/acme/demo', description: 'Gitee 项目' },
  });
  assert.equal(fromUrl.ok, true);
  assert.equal(fromUrl.repo.platform, 'gitee');

  const mismatch = normalizeBookmarkPayload({
    repo: { platform: 'github', fullName: 'acme/other', url: 'https://github.com/acme/demo' },
  });
  assert.deepEqual(mismatch, { ok: false, error: 'repo_url_mismatch' });

  const platformMismatch = normalizeBookmarkPayload({
    repo: { platform: 'gitee', url: 'https://github.com/acme/demo' },
  });
  assert.deepEqual(platformMismatch, { ok: false, error: 'platform_url_mismatch' });
});

test('normalizeBookmarkPayload：缺少仓库信息 / 非法平台返回错误', () => {
  assert.deepEqual(normalizeBookmarkPayload(null), { ok: false, error: 'invalid_body' });
  assert.deepEqual(normalizeBookmarkPayload({}), { ok: false, error: 'invalid_repo' });
  assert.deepEqual(normalizeBookmarkPayload({ repo: { fullName: 'acme/demo', platform: 'gitlab' } }), {
    ok: false,
    error: 'invalid_platform',
  });
});

test('令牌工具：格式、尾号提示与备注默认值', () => {
  const token = generateExtensionToken();
  assert.match(token, /^ofx_[0-9a-f]{64}$/);
  assert.equal(isExtensionTokenFormat(token), true);
  assert.equal(isExtensionTokenFormat('bwotp_x'), false);
  assert.equal(tokenHint(token), `ofx_…${token.slice(-4)}`);
  assert.equal(normalizeTokenLabel('  工作电脑 Chrome  '), '工作电脑 Chrome');
  assert.equal(normalizeTokenLabel(''), '浏览器扩展');
});

// ── 路由 ────────────────────────────────────────────────────────

test('令牌列表：未登录 401', async () => {
  const res = await makeApp(fakeDb(), null).request('/api/extension/tokens');
  assert.equal(res.status, 401);
});

test('创建令牌：返回明文一次，落库为 sha-256 摘要与尾号', async () => {
  const db = fakeDb();
  const res = await makeApp(db).request(
    '/api/extension/tokens',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ label: '工作电脑' }),
    },
    { DB: db }
  );
  assert.equal(res.status, 201);
  const body = await res.json();
  assert.match(body.token, /^ofx_[0-9a-f]{64}$/);
  assert.equal(body.item.label, '工作电脑');
  assert.equal(body.item.status, 'active');
  assert.equal(body.item.hint, tokenHint(body.token));

  const insert = db.calls.find((call) => call.sql.includes('INSERT INTO extension_tokens'));
  assert.ok(insert);
  assert.notEqual(insert.params[3], body.token);
  assert.match(insert.params[3], /^[0-9a-f]{64}$/);
  assert.equal(JSON.stringify(insert.params).includes(body.token), false);
});

test('创建令牌：超过 20 个有效令牌时拒绝', async () => {
  const db = fakeDb({ count: 20 });
  const res = await makeApp(db).request(
    '/api/extension/tokens',
    { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' },
    { DB: db }
  );
  assert.equal(res.status, 400);
  assert.equal((await res.json()).error, 'too_many_tokens');
});

test('撤销令牌：不存在或非本人返回 404', async () => {
  const db = fakeDb({ changes: 0 });
  const res = await makeApp(db).request(
    '/api/extension/tokens/tok_x',
    { method: 'DELETE' },
    { DB: db }
  );
  assert.equal(res.status, 404);
});

test('Bearer me：无 Authorization 返回 401；有效令牌返回用户与令牌信息', async () => {
  const unauthorized = await makeApp(fakeDb()).request('/api/extension/me');
  assert.equal(unauthorized.status, 401);

  const token = generateExtensionToken();
  const tokenRow = {
    id: 'tok_1',
    user_id: 'u1',
    label: 'Chrome',
    token_hash: 'hash',
    hint: tokenHint(token),
    created_at: '2026-10-22T10:00:00Z',
    last_used_at: null,
    revoked_at: null,
  };
  const userRow = { id: 'u1', login: 'tester', name: 'Tester', email: null, avatar_url: null, created_at: '' };
  const db = fakeDb({ tokenRow, userRow });
  const res = await makeApp(db).request(
    '/api/extension/me',
    { headers: { Authorization: `Bearer ${token}` } },
    { DB: db }
  );
  assert.equal(res.status, 200);
  const body = await res.json();
  assert.equal(body.user.login, 'tester');
  assert.equal(body.token.hint, tokenHint(token));
});

test('check：已收藏返回 saved=true 与仓库摘要', async () => {
  const token = generateExtensionToken();
  const tokenRow = {
    id: 'tok_1',
    user_id: 'u1',
    label: null,
    token_hash: 'hash',
    hint: tokenHint(token),
    created_at: '2026-10-22T10:00:00Z',
    last_used_at: null,
    revoked_at: null,
  };
  const userRow = { id: 'u1', login: 'tester', name: null, email: null, avatar_url: null, created_at: '' };
  const db = fakeDb({ tokenRow, userRow, repo: repoRow() });
  const res = await makeApp(db).request(
    '/api/extension/check?id=acme/demo',
    { headers: { Authorization: `Bearer ${token}` } },
    { DB: db }
  );
  assert.equal(res.status, 200);
  const body = await res.json();
  assert.equal(body.saved, true);
  assert.equal(body.repo.fullName, 'acme/demo');
});

test('bookmark：新收藏写入当前用户并返回 created=true', async () => {
  const token = generateExtensionToken();
  const tokenRow = {
    id: 'tok_1',
    user_id: 'u1',
    label: null,
    token_hash: 'hash',
    hint: tokenHint(token),
    created_at: '2026-10-22T10:00:00Z',
    last_used_at: null,
    revoked_at: null,
  };
  const userRow = { id: 'u1', login: 'tester', name: null, email: null, avatar_url: null, created_at: '' };
  const db = fakeDb({ tokenRow, userRow, repo: null });
  const res = await makeApp(db).request(
    '/api/extension/bookmark',
    {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({
        repo: {
          platform: 'github',
          fullName: 'acme/demo',
          url: 'https://github.com/acme/demo',
          description: '示例项目',
          language: 'TypeScript',
          stars: 12,
          forks: 3,
        },
      }),
    },
    { DB: db }
  );
  assert.equal(res.status, 200);
  const body = await res.json();
  assert.equal(body.created, true);
  assert.equal(body.repo.fullName, 'acme/demo');
  const insert = db.calls.find((call) => call.sql.includes('INSERT INTO my_repositories'));
  assert.ok(insert);
  assert.equal(insert.params[0], 'acme/demo');
  assert.equal(insert.params[7], 'u1');
});

test('bookmark：仓库属于其他用户时返回 409，不转移归属', async () => {
  const token = generateExtensionToken();
  const tokenRow = {
    id: 'tok_1',
    user_id: 'u1',
    label: null,
    token_hash: 'hash',
    hint: tokenHint(token),
    created_at: '2026-10-22T10:00:00Z',
    last_used_at: null,
    revoked_at: null,
  };
  const userRow = { id: 'u1', login: 'tester', name: null, email: null, avatar_url: null, created_at: '' };
  const db = fakeDb({ tokenRow, userRow, repo: { user_id: 'u2' } });
  const res = await makeApp(db).request(
    '/api/extension/bookmark',
    {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({ repo: { url: 'https://github.com/acme/demo' } }),
    },
    { DB: db }
  );
  assert.equal(res.status, 409);
  assert.equal((await res.json()).error, 'repo_owned_by_other_user');
});
