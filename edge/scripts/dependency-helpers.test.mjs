import assert from 'node:assert/strict';
import test from 'node:test';

import {
  buildLocalOverview,
  clampAnalysisTop,
  parseRepoIds,
} from '../src/dependencies/helpers.ts';

test('top 归一化：默认值 / 边界 / 非法值', () => {
  assert.equal(clampAnalysisTop(undefined), 20);
  assert.equal(clampAnalysisTop(''), 20);
  assert.equal(clampAnalysisTop('0'), 1);
  assert.equal(clampAnalysisTop('999'), 100);
  assert.equal(clampAnalysisTop('7'), 7);
  assert.equal(clampAnalysisTop('abc'), 20);
  assert.equal(clampAnalysisTop('3.9'), 3);
  assert.equal(clampAnalysisTop(12, 20, 50), 12);
});

test('repoIds 解析：去空白 / 去重 / 限制数量', () => {
  assert.deepEqual(parseRepoIds('a/b, c/d ,,a/b'), ['a/b', 'c/d']);
  assert.deepEqual(parseRepoIds(undefined), []);
  assert.deepEqual(parseRepoIds('  '), []);
  assert.equal(parseRepoIds(Array.from({ length: 150 }, (_, i) => `o/r${i}`).join(',')).length, 100);
  assert.deepEqual(parseRepoIds(`${'x'.repeat(256)},ok/repo`), ['ok/repo']);
});

test('本地降级概览：只统计语言，不伪造依赖', () => {
  const overview = buildLocalOverview([
    { id: 'b/two', name: 'two', language: 'Python' },
    { id: 'a/one', name: 'one', language: 'TypeScript' },
    { id: 'c/three', name: 'three', language: 'Python' },
    { id: 'd/none', name: 'none', language: null },
  ]);

  assert.equal(overview.summary.repos, 4);
  assert.equal(overview.summary.pending, 4);
  assert.equal(overview.summary.analyzed, 0);
  assert.equal(overview.summary.dependencyRows, 0);
  assert.deepEqual(overview.dependencies, []);
  assert.deepEqual(overview.ecosystems, []);

  const python = overview.techStack.find((item) => item.language === 'Python');
  assert.equal(python.count, 2);
  assert.equal(python.percent, 0.6667);
  assert.equal(overview.techStack[0].language, 'Python');
  assert.equal(overview.repos[0].repoId, 'a/one');
  assert.equal(overview.repos[0].status, 'unknown');
});

test('本地降级概览：空仓库列表', () => {
  const overview = buildLocalOverview([]);
  assert.equal(overview.summary.repos, 0);
  assert.deepEqual(overview.techStack, []);
  assert.deepEqual(overview.repos, []);
  assert.ok(overview.generatedAt.endsWith('Z'));
});
