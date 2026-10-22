import assert from 'node:assert/strict';
import test from 'node:test';

import { Hono } from 'hono';
import telegramRoutes, { generateLinkCode } from '../src/routes/telegram.ts';
import { sha256Hex } from '../src/security/crypto.ts';
import {
  buildFavoritesMessage,
  buildHelpMessage,
  buildRecommendationsMessage,
  buildTrendingMessage,
  chunkTelegramMessage,
  escapeTelegramHtml,
  formatCompactNumber,
  formatPercent,
  parseTelegramCommand,
  truncateTelegramText,
} from '../src/telegram/bot.ts';

function makeApp(db, user = { id: 'u1', login: 'alice' }) {
  const app = new Hono();
  app.use('*', async (c, next) => {
    c.set('user', user);
    await next();
  });
  app.route('/api/telegram', telegramRoutes);
  return app;
}

function makeAnonymousApp(db) {
  const app = new Hono();
  app.use('*', async (c, next) => {
    c.set('user', null);
    await next();
  });
  app.route('/api/telegram', telegramRoutes);
  return app;
}

function makeEnv(db, overrides = {}) {
  return {
    DB: db,
    TELEGRAM_BOT_TOKEN: 'test-token',
    TELEGRAM_WEBHOOK_SECRET: 'test-secret',
    TELEGRAM_BOT_USERNAME: 'OpenFactoryBot',
    TELEGRAM_API_BASE: 'https://telegram.test',
    ...overrides,
  };
}

function telegramUpdate(text, { chatId = 123456789, username = 'alice_tg', type = 'private' } = {}) {
  return {
    update_id: 1,
    message: {
      message_id: 1,
      text,
      chat: { id: chatId, type },
      from: { id: 42, username, is_bot: false },
    },
  };
}

function fakeDb({
  users = [
    { id: 'u1', login: 'alice' },
    { id: 'u2', login: 'bob' },
  ],
  links = [],
  codes = [],
  favorites = [],
  recommendations = [],
  snapshots = [],
  trending = [],
} = {}) {
  const db = {
    links: links.map((row) => ({ ...row })),
    codes: codes.map((row) => ({ ...row })),
    users: users.map((row) => ({ ...row })),
    favorites: favorites.map((row) => ({ ...row })),
    recommendations: recommendations.map((row) => ({ ...row })),
    snapshots: snapshots.map((row) => ({ ...row })),
    trending: trending.map((row) => ({ ...row })),
  };

  function withLogin(row) {
    return { ...row, login: db.users.find((user) => user.id === row.user_id)?.login ?? null };
  }

  db.prepare = (sql) => ({
    bind(...params) {
      return {
        async first() {
          if (sql.includes('FROM telegram_links l')) {
            const row = sql.includes('l.user_id = ?')
              ? db.links.find((item) => item.user_id === params[0])
              : db.links.find((item) => item.chat_id === params[0]);
            return row ? withLogin(row) : null;
          }
          if (sql.includes('FROM telegram_link_codes')) {
            return db.codes.find((item) => item.code_hash === params[0]) ?? null;
          }
          if (sql.includes('FROM users')) {
            return db.users.find((item) => item.id === params[0]) ?? null;
          }
          if (sql.includes('MAX(snapshot_date)')) {
            const dates = db.snapshots.map((item) => item.snapshot_date).sort();
            return { d: dates.length > 0 ? dates[dates.length - 1] : null };
          }
          return null;
        },
        async all() {
          if (sql.includes('FROM my_repositories')) {
            const [userId, keyword] = params;
            const limit = Number(params[params.length - 1]);
            const needle = String(keyword).toLowerCase();
            return {
              results: db.favorites
                .filter((row) => row.user_id === userId)
                .filter(
                  (row) =>
                    !needle ||
                    String(row.name).toLowerCase().includes(needle) ||
                    String(row.description ?? '').toLowerCase().includes(needle) ||
                    String(row.id).toLowerCase().includes(needle)
                )
                .sort((a, b) => Number(b.stars ?? 0) - Number(a.stars ?? 0))
                .slice(0, limit),
            };
          }
          if (sql.includes('FROM recommendations')) {
            const [userId] = params;
            const limit = Number(params[params.length - 1]);
            return {
              results: db.recommendations
                .filter((row) => row.user_id === userId)
                .filter((row) => row.status === 'new' || row.status == null)
                .sort(
                  (a, b) =>
                    Math.max(Number(b.rerank_score ?? 0), Number(b.score ?? 0)) -
                    Math.max(Number(a.rerank_score ?? 0), Number(a.score ?? 0))
                )
                .slice(0, limit),
            };
          }
          if (sql.includes('FROM trending_snapshots')) {
            const [snapshotDate, language] = params;
            const limit = Number(params[params.length - 1]);
            return {
              results: db.snapshots
                .filter((row) => row.snapshot_date === snapshotDate)
                .filter(
                  (row) =>
                    !language || String(row.language ?? '').toLowerCase() === String(language).toLowerCase()
                )
                .sort((a, b) => Number(a.rank ?? 0) - Number(b.rank ?? 0))
                .slice(0, limit),
            };
          }
          if (sql.includes('FROM trending_repositories')) {
            const [language] = params;
            const limit = Number(params[params.length - 1]);
            return {
              results: db.trending
                .filter(
                  (row) =>
                    !language || String(row.language ?? '').toLowerCase() === String(language).toLowerCase()
                )
                .sort((a, b) => Number(b.stars_today ?? 0) - Number(a.stars_today ?? 0))
                .slice(0, limit),
            };
          }
          return { results: [] };
        },
        async run() {
          if (sql.includes('DELETE FROM telegram_link_codes WHERE expires_at <= ?')) {
            const now = Date.parse(params[0]);
            const before = db.codes.length;
            db.codes = db.codes.filter((item) => Date.parse(item.expires_at) > now);
            return { meta: { changes: before - db.codes.length } };
          }
          if (sql.includes('DELETE FROM telegram_link_codes WHERE user_id = ?')) {
            const before = db.codes.length;
            db.codes = db.codes.filter((item) => item.user_id !== params[0]);
            return { meta: { changes: before - db.codes.length } };
          }
          if (sql.includes('DELETE FROM telegram_link_codes WHERE code_hash = ?')) {
            const before = db.codes.length;
            db.codes = db.codes.filter((item) => item.code_hash !== params[0]);
            return { meta: { changes: before - db.codes.length } };
          }
          if (sql.includes('INSERT INTO telegram_link_codes')) {
            db.codes.push({
              code_hash: params[0],
              user_id: params[1],
              expires_at: params[2],
              created_at: params[3],
            });
            return { meta: { changes: 1 } };
          }
          if (sql.includes('DELETE FROM telegram_links WHERE chat_id = ? OR user_id = ?')) {
            const before = db.links.length;
            db.links = db.links.filter(
              (item) => item.chat_id !== params[0] && item.user_id !== params[1]
            );
            return { meta: { changes: before - db.links.length } };
          }
          if (sql.includes('DELETE FROM telegram_links WHERE user_id = ?')) {
            const before = db.links.length;
            db.links = db.links.filter((item) => item.user_id !== params[0]);
            return { meta: { changes: before - db.links.length } };
          }
          if (sql.includes('DELETE FROM telegram_links WHERE chat_id = ?')) {
            const before = db.links.length;
            db.links = db.links.filter((item) => item.chat_id !== params[0]);
            return { meta: { changes: before - db.links.length } };
          }
          if (sql.includes('INSERT INTO telegram_links')) {
            db.links.push({
              chat_id: params[0],
              user_id: params[1],
              username: params[2],
              linked_at: params[3],
              last_seen_at: params[4],
            });
            return { meta: { changes: 1 } };
          }
          if (sql.includes('UPDATE telegram_links SET last_seen_at')) {
            const row = db.links.find((item) => item.chat_id === params[1]);
            if (row) row.last_seen_at = params[0];
            return { meta: { changes: row ? 1 : 0 } };
          }
          return { meta: { changes: 0 } };
        },
      };
    },
  });
  return db;
}

async function captureFetch(fn) {
  const originalFetch = globalThis.fetch;
  const sent = [];
  globalThis.fetch = async (url, init) => {
    sent.push({ url: String(url), body: JSON.parse(init?.body ?? '{}') });
    return new Response(JSON.stringify({ ok: true }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    });
  };
  try {
    await fn();
  } finally {
    globalThis.fetch = originalFetch;
  }
  return sent;
}

async function webhook(app, env, update) {
  return app.request(
    '/api/telegram/webhook',
    {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Telegram-Bot-Api-Secret-Token': 'test-secret',
      },
      body: JSON.stringify(update),
    },
    env
  );
}

// ── 纯函数 ──────────────────────────────────────────────────────

test('命令解析：别名、@Bot 后缀、中文命令与参数', () => {
  assert.deepEqual(parseTelegramCommand('/favorites 支付'), { command: 'favorites', args: '支付' });
  assert.deepEqual(parseTelegramCommand('/favorites@OpenFactoryBot AI'), {
    command: 'favorites',
    args: 'AI',
  });
  assert.deepEqual(parseTelegramCommand('/收藏 支付'), { command: 'favorites', args: '支付' });
  assert.deepEqual(parseTelegramCommand('/hot Rust'), { command: 'trending', args: 'Rust' });
  assert.deepEqual(parseTelegramCommand('/start 123456'), { command: 'start', args: '123456' });
  assert.equal(parseTelegramCommand('hello').command, 'unknown');
  assert.equal(parseTelegramCommand('').command, 'unknown');
});

test('HTML 转义与文本截断', () => {
  assert.equal(
    escapeTelegramHtml('<script>&"'),
    '&lt;script&gt;&amp;&quot;'
  );
  assert.equal(truncateTelegramText('  a   b\n c ', 20), 'a b c');
  assert.equal(truncateTelegramText('abcdefghij', 6), 'abcde…');
});

test('数字与百分比格式化', () => {
  assert.equal(formatCompactNumber(999), '999');
  assert.equal(formatCompactNumber(1200), '1.2k');
  assert.equal(formatCompactNumber(1_250_000), '1.3m');
  assert.equal(formatPercent(0.923), '92%');
  assert.equal(formatPercent(1.4), '100%');
  assert.equal(formatPercent(null), '0%');
});

test('收藏消息：空数据、关键词、转义与 Star 排序展示', () => {
  const empty = buildFavoritesMessage([], { keyword: '支付' });
  assert.match(empty, /没有找到匹配的收藏项目/);

  const text = buildFavoritesMessage(
    [
      {
        id: 'acme/pay',
        name: 'pay<&>',
        description: '支付<网关>',
        html_url: 'https://github.com/acme/pay',
        stars: 1234,
        language: 'Go',
        category_name: '支付',
      },
    ],
    { keyword: '支付' }
  );
  assert.match(text, /关键词「支付」/);
  assert.match(text, /acme\/pay/);
  assert.match(text, /支付&lt;网关&gt;/);
  assert.match(text, /1\.2k/);
  assert.match(text, /https:\/\/github\.com\/acme\/pay/);
});

test('推荐与热榜消息：分数、增量与空数据', () => {
  const recommend = buildRecommendationsMessage([
    {
      id: 'rec1',
      owner: 'acme',
      name: 'good',
      description: null,
      language: 'Go',
      stars: 900,
      score: 0.5,
      rerank_score: 0.92,
      reason: '与你收藏的项目相似',
      url: 'https://github.com/acme/good',
    },
  ]);
  assert.match(recommend, /匹配度 92%/);
  assert.match(recommend, /acme\/good/);

  const trending = buildTrendingMessage(
    [
      {
        id: 't1',
        owner: 'trend',
        name: 'two',
        html_url: 'https://github.com/trend/two',
        description: '热榜项目',
        language: 'Zig',
        stars: 2000,
        stars_today: 500,
        star_delta: 500,
        rank: 1,
        date: '2026-10-22',
      },
    ],
    { date: '2026-10-22' }
  );
  assert.match(trending, /2026-10-22/);
  assert.match(trending, /\+500 \/ 日/);
  assert.match(buildTrendingMessage([], { language: 'Rust' }), /没有找到 Rust/);
});

test('帮助消息与分片', () => {
  const help = buildHelpMessage({ linked: false, botUsername: 'OpenFactoryBot' });
  assert.match(help, /\/link 123456/);
  assert.match(help, /@OpenFactoryBot/);

  const chunks = chunkTelegramMessage('a'.repeat(100) + '\n' + 'b'.repeat(100), 120);
  assert.equal(chunks.length, 2);
  assert.ok(chunks.every((chunk) => chunk.length <= 120));
});

test('绑定码为 6 位数字', () => {
  for (let i = 0; i < 50; i += 1) {
    assert.match(generateLinkCode(), /^\d{6}$/);
  }
});

// ── 登录态接口 ──────────────────────────────────────────────────

test('GET /api/telegram/status：未登录 401，已绑定返回脱敏 chat id', async () => {
  const db = fakeDb({
    links: [
      {
        chat_id: '1234567890',
        user_id: 'u1',
        username: 'alice_tg',
        linked_at: '2026-10-22T00:00:00.000Z',
        last_seen_at: '2026-10-22T01:00:00.000Z',
      },
    ],
  });
  const env = makeEnv(db);
  const anonymous = await makeAnonymousApp(db).request('/api/telegram/status', {}, env);
  assert.equal(anonymous.status, 401);

  const res = await makeApp(db).request('/api/telegram/status', {}, env);
  assert.equal(res.status, 200);
  const body = await res.json();
  assert.equal(body.configured, true);
  assert.equal(body.linked, true);
  assert.equal(body.link.chatId, '***7890');
  assert.equal(body.link.login, 'alice');
  assert.ok(Array.isArray(body.commands));
});

test('POST /api/telegram/link-code：只存摘要并返回 10 分钟有效的绑定码', async () => {
  const db = fakeDb();
  const res = await makeApp(db).request(
    '/api/telegram/link-code',
    { method: 'POST' },
    makeEnv(db)
  );
  assert.equal(res.status, 200);
  const body = await res.json();
  assert.match(body.code, /^\d{6}$/);
  assert.equal(body.command, `/link ${body.code}`);
  assert.equal(body.deepLink, `https://t.me/OpenFactoryBot?start=${body.code}`);
  assert.equal(db.codes.length, 1);
  assert.equal(db.codes[0].user_id, 'u1');
  assert.notEqual(db.codes[0].code_hash, body.code);
  assert.equal(db.codes[0].code_hash, await sha256Hex(body.code));
  const ttl = Date.parse(body.expiresAt) - Date.now();
  assert.ok(ttl > 9 * 60 * 1000 && ttl <= 10 * 60 * 1000 + 5000);
});

test('POST /api/telegram/link-code：未配置 Bot 返回 503', async () => {
  const db = fakeDb();
  const res = await makeApp(db).request(
    '/api/telegram/link-code',
    { method: 'POST' },
    makeEnv(db, { TELEGRAM_BOT_TOKEN: '', TELEGRAM_WEBHOOK_SECRET: '' })
  );
  assert.equal(res.status, 503);
});

test('DELETE /api/telegram/link：解绑当前用户', async () => {
  const db = fakeDb({
    links: [
      {
        chat_id: '42',
        user_id: 'u1',
        username: 'alice_tg',
        linked_at: '2026-10-22T00:00:00.000Z',
        last_seen_at: null,
      },
    ],
  });
  const res = await makeApp(db).request(
    '/api/telegram/link',
    { method: 'DELETE' },
    makeEnv(db)
  );
  assert.equal(res.status, 200);
  assert.deepEqual(await res.json(), { linked: false, removed: true });
  assert.equal(db.links.length, 0);
});

// ── Webhook ─────────────────────────────────────────────────────

test('webhook：未配置 503，secret 错误 401，非文本更新忽略', async () => {
  const db = fakeDb();
  const app = makeAnonymousApp(db);

  const unconfigured = await app.request(
    '/api/telegram/webhook',
    { method: 'POST', body: '{}' },
    makeEnv(db, { TELEGRAM_BOT_TOKEN: '', TELEGRAM_WEBHOOK_SECRET: '' })
  );
  assert.equal(unconfigured.status, 503);

  const wrong = await app.request(
    '/api/telegram/webhook',
    {
      method: 'POST',
      headers: { 'X-Telegram-Bot-Api-Secret-Token': 'wrong' },
      body: JSON.stringify(telegramUpdate('/help')),
    },
    makeEnv(db)
  );
  assert.equal(wrong.status, 401);

  const ignored = await webhook(
    app,
    makeEnv(db),
    { update_id: 2, message: { message_id: 1, chat: { id: 1, type: 'private' } } }
  );
  assert.equal(ignored.status, 200);
  assert.equal((await ignored.json()).ignored, true);
});

test('webhook：群组会话不处理查询，只提示私聊', async () => {
  const db = fakeDb({
    links: [
      {
        chat_id: '-100123',
        user_id: 'u1',
        username: 'alice_tg',
        linked_at: '2026-10-22T00:00:00.000Z',
        last_seen_at: null,
      },
    ],
    favorites: [
      {
        id: 'u1/secret',
        user_id: 'u1',
        name: 'secret',
        description: '不应出现',
        html_url: 'https://github.com/u1/secret',
        stars: 1,
      },
    ],
  });
  const app = makeAnonymousApp(db);
  const sent = await captureFetch(async () => {
    const res = await webhook(
      app,
      makeEnv(db),
      telegramUpdate('/favorites', { chatId: -100123, type: 'group' })
    );
    assert.equal(res.status, 200);
    assert.equal((await res.json()).ignored, true);
  });
  assert.match(sent[0].body.text, /私聊/);
  assert.doesNotMatch(sent[0].body.text, /secret|不应出现/);
});

test('webhook：未绑定查询只返回绑定指引，不泄漏数据', async () => {
  const db = fakeDb({
    favorites: [
      {
        id: 'u1/secret',
        user_id: 'u1',
        name: 'secret',
        description: '不应出现',
        html_url: 'https://github.com/u1/secret',
        stars: 1,
      },
    ],
  });
  const app = makeAnonymousApp(db);

  const sent = await captureFetch(async () => {
    const res = await webhook(app, makeEnv(db), telegramUpdate('/favorites'));
    assert.equal(res.status, 200);
  });
  assert.match(sent[0].body.text, /尚未绑定/);
  assert.doesNotMatch(sent[0].body.text, /secret|不应出现/);
});

test('webhook：/link 绑定成功后可按用户查询收藏（含关键词过滤）', async () => {
  const code = '123456';
  const db = fakeDb({
    codes: [
      {
        code_hash: await sha256Hex(code),
        user_id: 'u1',
        expires_at: new Date(Date.now() + 600000).toISOString(),
        created_at: new Date().toISOString(),
      },
    ],
    favorites: [
      {
        id: 'u1/pay',
        user_id: 'u1',
        name: 'pay-gateway',
        description: '支付网关',
        html_url: 'https://github.com/u1/pay',
        stars: 1200,
        language: 'Go',
        category_name: '支付',
      },
      {
        id: 'u1/other',
        user_id: 'u1',
        name: 'other',
        description: '其他项目',
        html_url: 'https://github.com/u1/other',
        stars: 10,
        language: 'Go',
      },
      {
        id: 'u2/pay',
        user_id: 'u2',
        name: 'pay-other',
        description: '别人的支付项目',
        html_url: 'https://github.com/u2/pay',
        stars: 9999,
      },
    ],
  });
  const app = makeAnonymousApp(db);
  const env = makeEnv(db);

  const sent = await captureFetch(async () => {
    const linkRes = await webhook(app, env, telegramUpdate(`/link ${code}`));
    assert.equal(linkRes.status, 200);
  });
  assert.match(sent[0].body.text, /绑定成功/);
  assert.equal(db.links[0].user_id, 'u1');
  assert.equal(db.codes.length, 0);

  const sent2 = await captureFetch(async () => {
    const favRes = await webhook(app, env, telegramUpdate('/favorites 支付'));
    assert.equal(favRes.status, 200);
  });
  const text = sent2[0].body.text;
  assert.match(text, /u1\/pay/);
  assert.match(text, /支付网关/);
  assert.doesNotMatch(text, /u2\/pay|pay-other|别人的支付项目/);
  assert.doesNotMatch(text, /other/);
});

test('webhook：绑定码过期与错误分别提示', async () => {
  const db = fakeDb({
    codes: [
      {
        code_hash: await sha256Hex('111111'),
        user_id: 'u1',
        expires_at: new Date(Date.now() - 1000).toISOString(),
        created_at: new Date().toISOString(),
      },
    ],
  });
  const app = makeAnonymousApp(db);
  const env = makeEnv(db);

  const sent = await captureFetch(async () => {
    await webhook(app, env, telegramUpdate('/link 111111'));
  });
  assert.match(sent[0].body.text, /已过期/);
  assert.equal(db.codes.length, 0);

  const sent2 = await captureFetch(async () => {
    await webhook(app, env, telegramUpdate('/link 999999'));
  });
  assert.match(sent2[0].body.text, /绑定码无效/);
});

test('webhook：/recommend 只返回待处理推荐并按精排分排序', async () => {
  const db = fakeDb({
    links: [
      {
        chat_id: '123456789',
        user_id: 'u1',
        username: 'alice_tg',
        linked_at: '2026-10-22T00:00:00.000Z',
        last_seen_at: null,
      },
    ],
    recommendations: [
      {
        id: 'r1',
        user_id: 'u1',
        owner: 'acme',
        name: 'lower',
        description: null,
        language: 'Go',
        stars: 100,
        score: 0.4,
        rerank_score: 0.5,
        reason: '普通',
        url: 'https://github.com/acme/lower',
        status: 'new',
        created_at: '2026-10-21',
      },
      {
        id: 'r2',
        user_id: 'u1',
        owner: 'acme',
        name: 'higher',
        description: null,
        language: 'Go',
        stars: 200,
        score: 0.6,
        rerank_score: 0.9,
        reason: '更匹配',
        url: 'https://github.com/acme/higher',
        status: 'new',
        created_at: '2026-10-20',
      },
      {
        id: 'r3',
        user_id: 'u1',
        owner: 'acme',
        name: 'saved',
        description: null,
        language: 'Go',
        stars: 300,
        score: 0.99,
        reason: '已保存',
        url: 'https://github.com/acme/saved',
        status: 'saved',
        created_at: '2026-10-19',
      },
    ],
  });
  const app = makeAnonymousApp(db);
  const sent = await captureFetch(async () => {
    await webhook(app, makeEnv(db), telegramUpdate('/recommend'));
  });
  const text = sent[0].body.text;
  assert.ok(text.indexOf('higher') < text.indexOf('lower'));
  assert.doesNotMatch(text, /saved/);
});

test('webhook：/trending 优先最新快照，无快照回退旧表', async () => {
  const snapshotDb = fakeDb({
    links: [
      {
        chat_id: '123456789',
        user_id: 'u1',
        username: 'alice_tg',
        linked_at: '2026-10-22T00:00:00.000Z',
        last_seen_at: null,
      },
    ],
    snapshots: [
      {
        snapshot_date: '2026-10-22',
        repo_id: 'trend/go',
        owner: 'trend',
        name: 'go-repo',
        html_url: 'https://github.com/trend/go-repo',
        description: 'Go 热榜',
        language: 'Go',
        stars: 3000,
        stars_today: 800,
        star_delta: 800,
        rank: 1,
      },
      {
        snapshot_date: '2026-10-22',
        repo_id: 'trend/rust',
        owner: 'trend',
        name: 'rust-repo',
        html_url: 'https://github.com/trend/rust-repo',
        description: 'Rust 热榜',
        language: 'Rust',
        stars: 2000,
        stars_today: 600,
        star_delta: 600,
        rank: 2,
      },
    ],
  });
  const snapshotApp = makeAnonymousApp(snapshotDb);
  const sent = await captureFetch(async () => {
    await webhook(snapshotApp, makeEnv(snapshotDb), telegramUpdate('/trending Go'));
  });
  assert.match(sent[0].body.text, /2026-10-22/);
  assert.match(sent[0].body.text, /go-repo/);
  assert.doesNotMatch(sent[0].body.text, /rust-repo/);

  const fallbackDb = fakeDb({
    links: [
      {
        chat_id: '123456789',
        user_id: 'u1',
        username: 'alice_tg',
        linked_at: '2026-10-22T00:00:00.000Z',
        last_seen_at: null,
      },
    ],
    trending: [
      {
        id: 'trend/old',
        owner: 'trend',
        name: 'old-repo',
        html_url: 'https://github.com/trend/old-repo',
        description: '旧表数据',
        language: 'Go',
        stars: 100,
        stars_today: 50,
        crawled_at: '2026-10-20',
      },
    ],
  });
  const fallbackApp = makeAnonymousApp(fallbackDb);
  const sent2 = await captureFetch(async () => {
    await webhook(fallbackApp, makeEnv(fallbackDb), telegramUpdate('/trending'));
  });
  assert.match(sent2[0].body.text, /old-repo/);
  assert.match(sent2[0].body.text, /2026-10-20/);
});

test('webhook：/start 深链绑定、/unlink 解绑与未知命令', async () => {
  const code = '654321';
  const db = fakeDb({
    codes: [
      {
        code_hash: await sha256Hex(code),
        user_id: 'u1',
        expires_at: new Date(Date.now() + 600000).toISOString(),
        created_at: new Date().toISOString(),
      },
    ],
  });
  const app = makeAnonymousApp(db);
  const env = makeEnv(db);

  const sent = await captureFetch(async () => {
    await webhook(app, env, telegramUpdate(`/start ${code}`));
  });
  assert.match(sent[0].body.text, /绑定成功/);

  const sent2 = await captureFetch(async () => {
    await webhook(app, env, telegramUpdate('/unlink'));
  });
  assert.match(sent2[0].body.text, /已解绑/);
  assert.equal(db.links.length, 0);

  const sent3 = await captureFetch(async () => {
    await webhook(app, env, telegramUpdate('/nonsense'));
  });
  assert.match(sent3[0].body.text, /未识别的命令/);
});

test('webhook：同一用户重新绑定会替换旧会话（一人一聊）', async () => {
  const code = '222222';
  const db = fakeDb({
    codes: [
      {
        code_hash: await sha256Hex(code),
        user_id: 'u1',
        expires_at: new Date(Date.now() + 600000).toISOString(),
        created_at: new Date().toISOString(),
      },
    ],
    links: [
      {
        chat_id: 'old-chat',
        user_id: 'u1',
        username: 'old',
        linked_at: '2026-10-01T00:00:00.000Z',
        last_seen_at: null,
      },
    ],
  });
  const app = makeAnonymousApp(db);
  const sent = await captureFetch(async () => {
    await webhook(app, makeEnv(db), telegramUpdate(`/link ${code}`, { chatId: 999 }));
  });
  assert.match(sent[0].body.text, /绑定成功/);
  assert.equal(db.links.length, 1);
  assert.equal(db.links[0].chat_id, '999');
});
