import assert from 'node:assert/strict';
import test from 'node:test';
import {
  computeTrendMap,
  isValidDate,
  matchesLanguage,
  parseTrendingQuery,
  trendFromRankChange,
} from '../src/trending/query.ts';

test('parseTrendingQuery：缺省值取最新快照 / 全部语言 / 20 条', () => {
  const result = parseTrendingQuery(new URLSearchParams());
  assert.equal(result.ok, true);
  if (!result.ok) return;
  assert.deepEqual(result.query, { date: '', language: '', limit: 20 });
});

test('parseTrendingQuery：日期 / 语言 / limit 正常解析并截断上限', () => {
  const result = parseTrendingQuery(
    new URLSearchParams({ date: '2026-10-22', language: ' Python ', limit: '999' })
  );
  assert.equal(result.ok, true);
  if (!result.ok) return;
  assert.deepEqual(result.query, {
    date: '2026-10-22',
    language: 'Python',
    limit: 100,
  });
});

test('parseTrendingQuery：非法日期与 limit 返回字段级错误', () => {
  const badDate = parseTrendingQuery(new URLSearchParams({ date: '2026-02-31' }));
  assert.equal(badDate.ok, false);
  if (badDate.ok) return;
  assert.equal(badDate.field, 'date');

  const badLimit = parseTrendingQuery(new URLSearchParams({ limit: '0' }));
  assert.equal(badLimit.ok, false);
  if (badLimit.ok) return;
  assert.equal(badLimit.field, 'limit');
});

test('isValidDate：接受闰日、拒绝越界日期', () => {
  assert.equal(isValidDate('2024-02-29'), true);
  assert.equal(isValidDate('2026-02-29'), false);
  assert.equal(isValidDate('2026-13-01'), false);
  assert.equal(isValidDate('2026-1-1'), false);
});

test('computeTrendMap：排名从 1 开始，正数表示上升，未上榜为新项目', () => {
  const current = [
    { id: 'b/repo', stars_today: 200 },
    { id: 'a/repo', stars_today: 80 },
    { id: 'd/repo', stars_today: 10 },
  ];
  const previous = new Map([
    ['a/repo', 1],
    ['b/repo', 2],
  ]);
  const map = computeTrendMap(current, previous);
  assert.deepEqual(map.get('b/repo'), { rank: 1, rankChange: 1, trend: 'up' });
  assert.deepEqual(map.get('a/repo'), { rank: 2, rankChange: -1, trend: 'down' });
  assert.deepEqual(map.get('d/repo'), { rank: 3, rankChange: null, trend: 'new' });
});

test('trendFromRankChange：0 为持平', () => {
  assert.equal(trendFromRankChange(0), 'same');
  assert.equal(trendFromRankChange(3), 'up');
  assert.equal(trendFromRankChange(-2), 'down');
  assert.equal(trendFromRankChange(null), 'new');
});

test('matchesLanguage：大小写不敏感，空筛选匹配全部', () => {
  assert.equal(matchesLanguage('TypeScript', 'typescript'), true);
  assert.equal(matchesLanguage(null, ''), true);
  assert.equal(matchesLanguage('Go', 'Python'), false);
});
