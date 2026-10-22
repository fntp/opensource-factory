import assert from 'node:assert/strict';
import test from 'node:test';

import { Hono } from 'hono';
import searchChat from '../src/routes/search-chat.ts';
import {
  buildChatFacets,
  buildChatSuggestions,
  buildFallbackAnswer,
  ChatInputError,
  detectIntent,
  detectLanguage,
  detectScope,
  extractTopic,
  keywordTermsForTopic,
  normalizeChatMessages,
  normalizeShownIds,
  resolveChatTurn,
} from '../src/search/chat.ts';

const history = [
  { role: 'user', content: '我的收藏里有哪些支付相关项目？' },
  { role: 'assistant', content: '找到 2 个支付项目。' },
  { role: 'user', content: '那 Rust 的呢？' },
];

test('normalizeChatMessages 校验角色 / 空内容 / 长度 / 最后一条', () => {
  const messages = normalizeChatMessages([
    { role: 'user', content: '  我的收藏里有哪些支付项目？  ' },
    { role: 'assistant', content: '找到 2 个。' },
    { role: 'user', content: '那 Rust 的呢？' },
  ]);
  assert.deepEqual(
    messages.map((item) => item.role),
    ['user', 'assistant', 'user']
  );
  assert.equal(messages[0].content, '我的收藏里有哪些支付项目？');

  assert.throws(() => normalizeChatMessages([]), ChatInputError);
  assert.throws(() => normalizeChatMessages([{ role: 'system', content: 'hi' }]), ChatInputError);
  assert.throws(() => normalizeChatMessages([{ role: 'user', content: '' }]), ChatInputError);
  assert.throws(
    () => normalizeChatMessages([{ role: 'user', content: 'x'.repeat(501) }]),
    ChatInputError
  );
  assert.throws(
    () =>
      normalizeChatMessages([
        { role: 'user', content: '问题' },
        { role: 'assistant', content: '回答' },
      ]),
    ChatInputError
  );
});

test('normalizeShownIds 去重并限制数量', () => {
  assert.deepEqual(normalizeShownIds(['a/b', 'a/b', ' c/d ']), ['a/b', 'c/d']);
  assert.deepEqual(normalizeShownIds(undefined), []);
  assert.throws(() => normalizeShownIds(['a', 1]), ChatInputError);
});

test('语言 / 范围 / 意图 / 主题解析与 VPS 规则一致', () => {
  assert.deepEqual(detectLanguage('那 Rust 的呢？'), { language: 'Rust', explicit: true });
  assert.deepEqual(detectLanguage('Python 项目'), { language: 'Python', explicit: true });
  assert.deepEqual(detectLanguage('不限语言'), { language: '', explicit: true });
  assert.deepEqual(detectLanguage('支付项目'), { language: '', explicit: false });

  assert.equal(detectScope('我的收藏里有哪些'), 'my');
  assert.equal(detectScope('热榜里有哪些'), 'trending');
  assert.equal(detectScope('全部来源'), 'all');
  assert.equal(detectScope('我的收藏和热榜对比'), 'all');
  assert.equal(detectScope('有哪些支付项目'), null);

  assert.equal(detectIntent('我的收藏里有多少支付项目？'), 'count');
  assert.equal(detectIntent('还有吗？'), 'more');
  assert.equal(detectIntent('第一个怎么样？'), 'detail');
  assert.equal(detectIntent('收藏和热榜对比'), 'compare');
  assert.equal(detectIntent('有哪些支付项目？'), 'list');

  assert.equal(extractTopic('我的收藏里有哪些支付相关项目？'), '支付');
  assert.equal(extractTopic('帮我找一些支付相关的项目'), '支付');
  assert.equal(extractTopic('那 Rust 的呢？'), '');
  assert.equal(extractTopic('还有吗？'), '');
  assert.equal(extractTopic('换个话题：推荐系统'), '推荐系统');
});

test('resolveChatTurn 继承主题 / 语言 / 范围并处理翻页排除', () => {
  const first = resolveChatTurn([history[0]]);
  assert.equal(first.topic, '支付');
  assert.equal(first.scope, 'my');
  assert.equal(first.language, '');
  assert.equal(first.turn, 1);

  const followup = resolveChatTurn(history);
  assert.equal(followup.topic, '支付');
  assert.equal(followup.language, 'Rust');
  assert.equal(followup.scope, 'my');
  assert.equal(followup.intent, 'list');
  assert.equal(followup.turn, 2);

  const more = resolveChatTurn(
    [...history, { role: 'user', content: '还有吗？' }],
    ['chat-test/pay-rust']
  );
  assert.equal(more.intent, 'more');
  assert.deepEqual(more.excluded, ['chat-test/pay-rust']);
  assert.equal(more.topic, '支付');
  assert.equal(more.language, 'Rust');
});

test('resolveChatTurn 支持显式范围覆盖', () => {
  const context = resolveChatTurn(history, [], 'trending');
  assert.equal(context.scope, 'trending');
  assert.equal(context.topic, '支付');
  assert.equal(context.language, 'Rust');
});

const items = [
  {
    id: 'chat-test/pay-rust',
    source: 'my',
    fullName: 'chat-test/pay-rust',
    name: 'pay-rust',
    description: 'Rust 支付网关',
    language: 'Rust',
    stars: 120,
  },
  {
    id: 'chat-test/pay-python',
    source: 'my',
    fullName: 'chat-test/pay-python',
    name: 'pay-python',
    description: 'Python 支付对账工具',
    language: 'Python',
    stars: 30,
  },
];

test('buildFallbackAnswer 覆盖列表 / 数量 / 对比 / 空结果', () => {
  const context = {
    topic: '支付',
    language: '',
    scope: 'my',
    intent: 'list',
    turn: 1,
    excluded: [],
  };
  const list = buildFallbackAnswer(context, items, 2);
  assert.match(list, /在\S*里找到 2 个/);
  assert.match(list, /\[1\]/);

  const count = buildFallbackAnswer({ ...context, intent: 'count' }, items, 2);
  assert.match(count, /共有 2 个/);

  const compare = buildFallbackAnswer({ ...context, intent: 'compare', scope: 'all' }, items, 2, {
    my: 2,
    trending: 1,
  });
  assert.match(compare, /你的收藏 2 个/);
  assert.match(compare, /每日热榜 1 个/);

  const empty = buildFallbackAnswer({ ...context, topic: '量子计算' }, [], 0);
  assert.match(empty, /没有找到/);
});

test('buildChatSuggestions 与 facets 生成可点击追问', () => {
  const context = {
    topic: '支付',
    language: 'Rust',
    scope: 'my',
    intent: 'list',
    turn: 1,
    excluded: [],
  };
  const facets = buildChatFacets(items);
  assert.deepEqual(facets.languages[0], { name: 'Python', count: 1 });
  const suggestions = buildChatSuggestions(context, items, 5, facets);
  assert.ok(suggestions.includes('还有吗？'));
  assert.ok(suggestions.includes('不限语言再看看'));
  assert.ok(suggestions.includes('热榜里有哪些支付项目？'));
  assert.ok(suggestions.length <= 4);
});

test('keywordTermsForTopic 去重并限制 8 个词', () => {
  assert.deepEqual(keywordTermsForTopic('支付 支付 账单'), ['支付', '账单']);
  assert.equal(keywordTermsForTopic('a b c d e f g h i').length, 8);
});


function repoRow(id, name, description, language, stars, userId = 'u1') {
  return {
    id,
    platform: 'github',
    name,
    description,
    html_url: `https://example.com/${id}`,
    stars,
    language,
    readme_summary: '',
    category_id: null,
    created_at: null,
    user_id: userId,
    owner: id.split('/')[0],
    forks: 0,
    updated_at: null,
    synced_at: null,
  };
}

function fakeDb({ myRows = [], trendingRows = [] } = {}) {
  return {
    prepare(sql) {
      let params = [];
      const statement = {
        bind(...values) {
          params = values;
          return statement;
        },
        async all() {
          if (sql.includes('SELECT id FROM my_repositories')) {
            return { results: myRows.map((row) => ({ id: row.id })) };
          }
          if (sql.includes('id IN') && sql.includes('FROM my_repositories')) {
            const ids = params.slice(0, -1);
            const userId = params[params.length - 1];
            return {
              results: myRows.filter(
                (row) => ids.includes(row.id) && row.user_id === userId
              ),
            };
          }
          if (sql.includes('id IN') && sql.includes('FROM trending_repositories')) {
            return { results: trendingRows.filter((row) => params.includes(row.id)) };
          }
          if (sql.includes('FROM my_repositories')) {
            const terms = params.slice(1, -1).map((value) => String(value).replaceAll('%', '').toLowerCase());
            return {
              results: myRows.filter((row) =>
                terms.some((term) =>
                  [row.id, row.name, row.description, row.readme_summary]
                    .filter(Boolean)
                    .join(' ')
                    .toLowerCase()
                    .includes(term)
                )
              ),
            };
          }
          if (sql.includes('FROM trending_repositories')) {
            const terms = params.slice(0, -1).map((value) => String(value).replaceAll('%', '').toLowerCase());
            return {
              results: trendingRows.filter((row) =>
                terms.some((term) =>
                  [row.id, row.name, row.description, row.tech_stack]
                    .filter(Boolean)
                    .join(' ')
                    .toLowerCase()
                    .includes(term)
                )
              ),
            };
          }
          return { results: [] };
        },
        async first() {
          return null;
        },
        async run() {
          return { meta: {} };
        },
      };
      return statement;
    },
  };
}

function makeApp(user = { id: 'u1' }) {
  const app = new Hono();
  app.use('*', async (c, next) => {
    c.set('user', user);
    await next();
  });
  app.route('/api/search/chat', searchChat);
  return app;
}

function chatRequest(app, env, body) {
  return app.request(
    '/api/search/chat',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    },
    env
  );
}

const myRows = [
  repoRow('demo/pay-rust', 'pay-rust', 'Rust 支付网关，支持账单与退款', 'Rust', 120),
  repoRow('demo/pay-python', 'pay-python', 'Python 支付对账工具', 'Python', 30),
  repoRow('demo/log-analyzer', 'log-analyzer', 'Go 日志分析平台', 'Go', 88),
];
const trendingRows = [
  {
    id: 'demo/trend-pay',
    platform: 'github',
    name: 'trend-pay',
    html_url: 'https://example.com/demo/trend-pay',
    stars_today: 50,
    description: '开源支付聚合平台',
    tech_stack: 'TypeScript',
    crawled_at: null,
    owner: 'demo',
    language: 'TypeScript',
    stars: 900,
    readme_summary: '',
  },
];

test('未登录返回 401，非法消息返回 400', async () => {
  const app = makeApp(null);
  const env = { DB: fakeDb(), VPS_NODE_URL: '' };
  const unauthorized = await chatRequest(app, env, {
    messages: [{ role: 'user', content: '我的收藏里有哪些支付项目？' }],
  });
  assert.equal(unauthorized.status, 401);

  const authed = makeApp();
  const invalid = await chatRequest(authed, env, { messages: [] });
  assert.equal(invalid.status, 400);
});

test('VPS 不可达时返回 D1 关键词兜底答案', async () => {
  const app = makeApp();
  const env = { DB: fakeDb({ myRows, trendingRows }), VPS_NODE_URL: '' };
  const res = await chatRequest(app, env, {
    messages: [{ role: 'user', content: '我的收藏里有哪些支付相关项目？' }],
  });
  assert.equal(res.status, 200);
  const body = await res.json();
  assert.equal(body.mode, 'keyword');
  assert.equal(body.fallback, true);
  assert.equal(body.scope, 'my');
  assert.equal(body.count, 2);
  assert.match(body.answer, /支付/);
  assert.deepEqual(
    body.items.map((item) => item.id),
    ['demo/pay-rust', 'demo/pay-python']
  );
  assert.deepEqual(
    body.items.map((item) => item.citation),
    [1, 2]
  );
  assert.ok(body.suggestions.length > 0);
});

test('兜底链路继承语言并切换范围', async () => {
  const app = makeApp();
  const env = { DB: fakeDb({ myRows, trendingRows }), VPS_NODE_URL: '' };
  const res = await chatRequest(app, env, {
    messages: [
      { role: 'user', content: '我的收藏里有哪些支付相关项目？' },
      { role: 'assistant', content: '找到 2 个支付项目。' },
      { role: 'user', content: '那 Rust 的呢？' },
    ],
  });
  assert.equal(res.status, 200);
  const body = await res.json();
  assert.equal(body.language, 'Rust');
  assert.equal(body.items.length, 1);
  assert.equal(body.items[0].id, 'demo/pay-rust');

  const trending = await chatRequest(app, env, {
    messages: [
      { role: 'user', content: '我的收藏里有哪些支付相关项目？' },
      { role: 'assistant', content: '找到 2 个支付项目。' },
      { role: 'user', content: '只看热榜' },
    ],
  });
  const trendingBody = await trending.json();
  assert.equal(trendingBody.scope, 'trending');
  assert.equal(trendingBody.items[0].id, 'demo/trend-pay');
  assert.equal(trendingBody.items[0].source, 'trending');
});

test('VPS 可用时按 D1 重新水合并保留引用编号', async () => {
  const app = makeApp();
  const env = {
    DB: fakeDb({ myRows, trendingRows }),
    VPS_NODE_URL: 'http://vps.test',
    INTERNAL_TOKEN: 'test-token',
  };
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () =>
    new Response(
      JSON.stringify({
        question: '我的收藏里有哪些支付相关项目？',
        answer: '在你的收藏里找到 1 个与「支付」相关的项目：\n[1] demo/pay-rust',
        intent: 'list',
        scope: 'my',
        topic: '支付',
        language: '',
        filters: { language: '', concepts: ['支付'], terms: ['支付'] },
        count: 1,
        total: 1,
        items: [
          {
            id: 'demo/pay-rust',
            source: 'my',
            score: 0.91,
            citation: 1,
            reason: '关键词匹配',
          },
        ],
        facets: { languages: [{ name: 'Rust', count: 1 }], sources: [{ name: 'my', count: 1 }] },
        suggestions: ['还有吗？'],
        mode: 'hybrid',
        tookMs: 3,
        turn: 1,
        backend: 'hash',
        model: 'hash',
      }),
      { status: 200, headers: { 'Content-Type': 'application/json' } }
    );
  try {
    const res = await chatRequest(app, env, {
      messages: [{ role: 'user', content: '我的收藏里有哪些支付相关项目？' }],
    });
    assert.equal(res.status, 200);
    const body = await res.json();
    assert.equal(body.mode, 'hybrid');
    assert.equal(body.items.length, 1);
    assert.equal(body.items[0].id, 'demo/pay-rust');
    assert.equal(body.items[0].citation, 1);
    assert.equal(body.items[0].reason, '关键词匹配');
  } finally {
    globalThis.fetch = originalFetch;
  }
});
