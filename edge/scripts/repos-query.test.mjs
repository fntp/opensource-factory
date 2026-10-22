import assert from 'node:assert/strict';
import test from 'node:test';
import {
  buildRepoOrderBy,
  buildRepoWhere,
  collectCategoryIds,
  endOfDateExclusive,
  escapeLike,
  parseRepoQuery,
  startOfDate,
} from '../src/repos-query.ts';

test('parseRepoQuery：缺省值使用 Star 降序', () => {
  const result = parseRepoQuery(new URLSearchParams());
  assert.equal(result.ok, true);
  if (!result.ok) return;
  assert.deepEqual(result.query, {
    q: '',
    categoryId: '',
    tagNames: [],
    tagIds: [],
    languages: [],
    starsMin: null,
    starsMax: null,
    updatedAfter: '',
    updatedBefore: '',
    sort: 'stars',
    order: 'desc',
  });
});

test('parseRepoQuery：解析组合筛选参数并去重语言', () => {
  const result = parseRepoQuery(
    new URLSearchParams({
      q: '  react ',
      categoryId: 'cat-1',
      tags: 'LLM, 框架',
      tagIds: '3,5',
      languages: 'TypeScript,Python',
      language: 'TypeScript',
      starsMin: '100',
      starsMax: '5000',
      updatedAfter: '2026-09-01',
      updatedBefore: '2026-10-01',
      sort: 'updated',
      order: 'asc',
    })
  );
  assert.equal(result.ok, true);
  if (!result.ok) return;
  assert.equal(result.query.q, 'react');
  assert.deepEqual(result.query.tagNames, ['LLM', '框架']);
  assert.deepEqual(result.query.tagIds, [3, 5]);
  assert.deepEqual(result.query.languages, ['TypeScript', 'Python']);
  assert.equal(result.query.starsMin, 100);
  assert.equal(result.query.starsMax, 5000);
  assert.equal(result.query.sort, 'updated');
  assert.equal(result.query.order, 'asc');
});

test('parseRepoQuery：非法输入返回字段级错误', () => {
  const cases = [
    ['starsMin=-1', 'starsMin'],
    ['starsMin=100&starsMax=10', 'starsMin'],
    ['updatedAfter=2026-13-01', 'updatedAfter'],
    ['updatedAfter=2026-10-02&updatedBefore=2026-10-01', 'updatedAfter'],
    ['tagIds=abc', 'tagIds'],
    ['sort=random', 'sort'],
    ['order=sideways', 'order'],
  ];
  for (const [query, field] of cases) {
    const result = parseRepoQuery(new URLSearchParams(query));
    assert.equal(result.ok, false, query);
    if (result.ok) continue;
    assert.equal(result.field, field, query);
  }
});

test('buildRepoWhere：组合条件生成参数化 SQL', () => {
  const result = parseRepoQuery(
    new URLSearchParams({
      q: '100%_off',
      categoryId: 'cat-1',
      tags: 'LLM',
      tagIds: '7',
      languages: 'Go,Rust',
      starsMin: '10',
      starsMax: '99',
      updatedAfter: '2026-09-01',
      updatedBefore: '2026-09-30',
    })
  );
  assert.equal(result.ok, true);
  if (!result.ok) return;

  const { where, params } = buildRepoWhere(result.query, 'user-1', ['cat-1', 'cat-2']);
  const sql = where.join(' AND ');

  assert.equal(where[0], 'r.user_id = ?');
  assert.match(sql, /r\.category_id IN \(\?, \?\)/);
  assert.match(sql, /t\.name = \? COLLATE NOCASE/);
  assert.match(sql, /rt\.tag_id = \?/);
  assert.match(sql, /r\.language COLLATE NOCASE IN \(\?, \?\)/);
  assert.match(sql, /COALESCE\(r\.stars, 0\) >= \?/);
  assert.match(sql, /COALESCE\(r\.stars, 0\) <= \?/);
  assert.match(sql, /r\.updated_at >= \?/);
  assert.match(sql, /r\.updated_at < \?/);
  assert.match(sql, /LIKE \? ESCAPE '\\'/);

  assert.deepEqual(params.slice(0, 2), ['user-1', '%100\\%\\_off%']);
  assert.deepEqual(params.slice(-10), [
    'cat-1',
    'cat-2',
    'LLM',
    7,
    'Go',
    'Rust',
    10,
    99,
    startOfDate('2026-09-01'),
    endOfDateExclusive('2026-09-30'),
  ]);
});

test('buildRepoOrderBy：白名单映射与稳定次序', () => {
  assert.equal(buildRepoOrderBy('stars', 'desc'), 'COALESCE(r.stars, 0) DESC, r.id ASC');
  assert.equal(
    buildRepoOrderBy('updated', 'asc'),
    "COALESCE(r.updated_at, r.synced_at, '') ASC, r.id ASC"
  );
  assert.equal(buildRepoOrderBy('name', 'asc'), 'r.name COLLATE NOCASE ASC, r.id ASC');
  assert.equal(buildRepoOrderBy('forks', 'desc'), 'COALESCE(r.forks, 0) DESC, r.id ASC');
});

test('collectCategoryIds：递归展开无限级子分类', () => {
  const nodes = [
    { id: 'root', parent_id: null },
    { id: 'child-a', parent_id: 'root' },
    { id: 'child-b', parent_id: 'root' },
    { id: 'grandchild', parent_id: 'child-a' },
    { id: 'other', parent_id: null },
  ];
  assert.deepEqual(collectCategoryIds(nodes, 'root').sort(), [
    'child-a',
    'child-b',
    'grandchild',
    'root',
  ]);
  assert.deepEqual(collectCategoryIds(nodes, 'missing'), ['missing']);
});

test('escapeLike 与日期边界', () => {
  assert.equal(escapeLike('a%b_c\\d'), 'a\\%b\\_c\\\\d');
  assert.equal(startOfDate('2026-10-01'), '2026-10-01T00:00:00.000Z');
  assert.equal(endOfDateExclusive('2026-10-31'), '2026-11-01T00:00:00.000Z');
  assert.equal(endOfDateExclusive('2026-12-31'), '2027-01-01T00:00:00.000Z');
});
