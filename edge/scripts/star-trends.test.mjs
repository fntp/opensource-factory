import assert from 'node:assert/strict';
import test from 'node:test';

import { Hono } from 'hono';
import starTrendsRoutes from '../src/routes/star-trends.ts';
import { buildStarTrends } from '../src/insights/star-trends.ts';

const NOW = new Date('2026-10-22T10:00:00Z');

function snapshot(repoId, date, stars, extra = {}) {
  const [owner, name] = repoId.split('/');
  return {
    snapshot_date: date,
    repo_id: repoId,
    owner,
    name,
    html_url: `https://github.com/${repoId}`,
    description: '',
    language: 'TypeScript',
    stars,
    stars_today: 0,
    rank: 1,
    language_rank: 1,
    star_delta: 0,
    rank_delta: 0,
    appearances: 1,
    is_new: 0,
    trend: 'steady',
    ...extra,
  };
}

test('buildStarTrends 聚合每日序列、净增与 Top Movers', () => {
  const rows = [
    snapshot('acme/a', '2026-10-20', 100, { star_delta: 0 }),
    snapshot('acme/a', '2026-10-21', 130, { star_delta: 30 }),
    snapshot('acme/a', '2026-10-22', 160, { star_delta: 30, appearances: 3 }),
    snapshot('acme/b', '2026-10-20', 200, { star_delta: 0 }),
    snapshot('acme/b', '2026-10-21', 210, { star_delta: 10 }),
    snapshot('acme/b', '2026-10-22', 220, { star_delta: 10, appearances: 3 }),
    snapshot('acme/c', '2026-10-21', 50, { star_delta: 0, is_new: 1 }),
    snapshot('acme/c', '2026-10-22', 80, { star_delta: 30, is_new: 1 }),
  ];

  const data = buildStarTrends(rows, {
    days: 3,
    scope: 'trending',
    now: NOW,
  });

  assert.equal(data.scope, 'trending');
  assert.deepEqual(data.period, {
    days: 3,
    startDate: '2026-10-20',
    endDate: '2026-10-22',
    snapshotDays: 3,
  });
  assert.equal(data.summary.trackedRepos, 3);
  assert.equal(data.summary.totalStars, 460);
  assert.equal(data.summary.starGain, 110);
  assert.equal(data.summary.averageDailyGain, 55);
  assert.equal(data.summary.fastestGrowing.repoId, 'acme/a');
  assert.equal(data.summary.fastestGrowing.gain, 60);
  assert.equal(data.summary.fastestGrowing.growthRate, 60);
  assert.equal(data.summary.newEntries, 1);
  assert.equal(data.summary.risingRepos, 3);
  assert.equal(data.summary.fallingRepos, 0);

  assert.equal(data.series.length, 3);
  assert.deepEqual(data.series[0], {
    date: '2026-10-20',
    trackedRepos: 2,
    totalStars: 300,
    starGain: 0,
    newRepos: 0,
  });
  assert.deepEqual(data.series[1], {
    date: '2026-10-21',
    trackedRepos: 3,
    totalStars: 390,
    starGain: 40,
    newRepos: 1,
  });
  assert.deepEqual(data.series[2], {
    date: '2026-10-22',
    trackedRepos: 3,
    totalStars: 460,
    starGain: 70,
    newRepos: 0,
  });

  assert.deepEqual(
    data.topMovers.map((item) => item.repoId),
    ['acme/a', 'acme/c', 'acme/b']
  );
  assert.equal(data.topMovers[1].trend, 'new');
  assert.equal(data.topMovers[1].growthRate, 60);
  assert.deepEqual(data.topMovers[0].sparkline, [100, 130, 160]);
  assert.deepEqual(
    data.newEntries.map((item) => item.repoId),
    ['acme/c']
  );
  assert.equal(data.languages[0].language, 'TypeScript');
  assert.equal(data.languages[0].starGain, 110);
  assert.equal(data.languages[0].share, 100);
  assert.ok(data.insights.some((item) => item.kind === 'growth'));
  assert.ok(data.insights.some((item) => item.kind === 'language'));
  assert.ok(data.insights.some((item) => item.kind === 'new'));
});

test('单日快照用 star_delta 作为区间净增', () => {
  const data = buildStarTrends(
    [snapshot('acme/one', '2026-10-22', 125, { star_delta: 25 })],
    { days: 7, scope: 'trending', now: NOW }
  );

  assert.equal(data.summary.trackedRepos, 1);
  assert.equal(data.summary.starGain, 25);
  assert.equal(data.summary.fastestGrowing.gain, 25);
  assert.equal(data.summary.fastestGrowing.growthRate, 25);
  assert.equal(data.summary.averageDailyGain, 25);
});

test('my 范围按收藏白名单过滤并返回覆盖率', () => {
  const portfolio = [
    { id: 'acme/a', name: 'a', stars: 100, language: 'TypeScript' },
    { id: 'acme/b', name: 'b', stars: 200, language: 'Python' },
    { id: 'acme/c', name: 'c', stars: 300, language: 'Go' },
  ];
  const rows = [
    snapshot('acme/a', '2026-10-21', 90, { star_delta: 0 }),
    snapshot('acme/a', '2026-10-22', 110, { star_delta: 20 }),
    snapshot('acme/b', '2026-10-22', 205, { star_delta: 5 }),
    snapshot('other/leak', '2026-10-22', 999, { star_delta: 999 }),
  ];

  const data = buildStarTrends(rows, {
    days: 30,
    scope: 'my',
    portfolio,
    now: NOW,
  });

  assert.equal(data.summary.portfolioRepos, 3);
  assert.equal(data.summary.trackedRepos, 2);
  assert.equal(data.summary.totalStars, 600);
  assert.equal(data.summary.starGain, 25);
  assert.equal(data.summary.coverage, 66.7);
  assert.deepEqual(
    data.topMovers.map((item) => item.repoId),
    ['acme/a', 'acme/b']
  );
  assert.ok(!data.topMovers.some((item) => item.repoId === 'other/leak'));
});

test('语言过滤只保留匹配语言的快照', () => {
  const rows = [
    snapshot('acme/ts', '2026-10-21', 10, { star_delta: 0 }),
    snapshot('acme/ts', '2026-10-22', 20, { star_delta: 10 }),
    snapshot('acme/py', '2026-10-21', 100, {
      star_delta: 0,
      language: 'Python',
    }),
    snapshot('acme/py', '2026-10-22', 160, {
      star_delta: 60,
      language: 'Python',
    }),
  ];

  const data = buildStarTrends(rows, {
    days: 7,
    scope: 'trending',
    language: 'python',
    now: NOW,
  });

  assert.equal(data.summary.trackedRepos, 1);
  assert.equal(data.summary.starGain, 60);
  assert.equal(data.topMovers[0].repoId, 'acme/py');
  assert.equal(data.languages.length, 1);
  assert.equal(data.languages[0].language, 'Python');
});

test('头部集中与降温洞察按实际增量生成', () => {
  const rows = [];
  const gains = [100, 90, 80, 10, 5, -20];
  gains.forEach((gain, index) => {
    const repoId = `acme/r${index}`;
    rows.push(snapshot(repoId, '2026-10-21', 1000, { star_delta: 0 }));
    rows.push(snapshot(repoId, '2026-10-22', 1000 + gain, { star_delta: gain }));
  });

  const data = buildStarTrends(rows, {
    days: 7,
    scope: 'trending',
    now: NOW,
  });

  assert.equal(data.summary.fallingRepos, 1);
  assert.ok(data.insights.some((item) => item.kind === 'concentration'));
  const cooling = data.insights.find((item) => item.kind === 'cooling');
  assert.ok(cooling);
  assert.match(cooling.description, /acme\/r5/);
});

test('空数据返回结构化空态', () => {
  const data = buildStarTrends([], {
    days: 30,
    scope: 'my',
    portfolio: [],
    now: NOW,
  });

  assert.equal(data.period.snapshotDays, 0);
  assert.equal(data.period.startDate, null);
  assert.equal(data.summary.trackedRepos, 0);
  assert.equal(data.summary.totalStars, 0);
  assert.equal(data.summary.starGain, 0);
  assert.equal(data.summary.coverage, 0);
  assert.deepEqual(data.series, []);
  assert.deepEqual(data.topMovers, []);
  assert.deepEqual(data.newEntries, []);
  assert.deepEqual(data.languages, []);
  assert.deepEqual(data.insights, []);
  assert.equal(data.generatedAt, NOW.toISOString());
});

function fakeDb({ portfolio = [], snapshots = [] } = {}) {
  return {
    prepare(sql) {
      return {
        bind() {
          return {
            async all() {
              if (sql.includes('FROM my_repositories')) {
                return { results: portfolio };
              }
              if (sql.includes('FROM trending_snapshots')) {
                return { results: snapshots };
              }
              return { results: [] };
            },
            async first() {
              return null;
            },
            async run() {
              return { meta: { changes: 0 } };
            },
          };
        },
      };
    },
  };
}

function makeRouteApp(db, user = { id: 'u1', login: 'tester' }) {
  const app = new Hono();
  if (user) {
    app.use('*', async (c, next) => {
      c.set('user', user);
      await next();
    });
  }
  app.route('/api/star-trends', starTrendsRoutes);
  return app;
}

test('路由未登录返回 401', async () => {
  const res = await makeRouteApp(fakeDb(), null).request(
    '/api/star-trends',
    {},
    { DB: fakeDb() }
  );
  assert.equal(res.status, 401);
});

test('路由 scope=my 只返回当前用户收藏并带覆盖率', async () => {
  const db = fakeDb({
    portfolio: [
      { id: 'acme/a', name: 'a', stars: 160, language: 'TypeScript' },
      { id: 'acme/b', name: 'b', stars: 220, language: 'Python' },
    ],
    snapshots: [
      snapshot('acme/a', '2026-10-21', 130, { star_delta: 30 }),
      snapshot('acme/a', '2026-10-22', 160, { star_delta: 30 }),
      snapshot('other/leak', '2026-10-22', 999, { star_delta: 999 }),
    ],
  });
  const res = await makeRouteApp(db).request(
    '/api/star-trends?days=7&scope=my',
    {},
    { DB: db }
  );
  assert.equal(res.status, 200);
  const body = await res.json();
  assert.equal(body.scope, 'my');
  assert.equal(body.summary.portfolioRepos, 2);
  assert.equal(body.summary.trackedRepos, 1);
  assert.equal(body.summary.coverage, 50);
  assert.deepEqual(
    body.topMovers.map((item) => item.repoId),
    ['acme/a']
  );
  assert.ok(!body.topMovers.some((item) => item.repoId === 'other/leak'));
});

test('路由非法 days 回退 30 天', async () => {
  const db = fakeDb({
    snapshots: [snapshot('acme/a', '2026-10-22', 100, { star_delta: 10 })],
  });
  for (const value of ['oops', '0', '-7']) {
    const res = await makeRouteApp(db).request(
      `/api/star-trends?days=${value}&scope=trending`,
      {},
      { DB: db }
    );
    assert.equal(res.status, 200);
    const body = await res.json();
    assert.equal(body.period.days, 30);
  }
});
