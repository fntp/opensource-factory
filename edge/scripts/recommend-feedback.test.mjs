import assert from 'node:assert/strict';
import test from 'node:test';

import {
  buildFeedbackRow,
  deriveRepoId,
  normalizeDismissReason,
  normalizeStatusFilter,
  parseBasedOn,
  shouldKeepUserStatus,
  toRecommendation,
} from '../src/recommend/feedback.ts';

test('normalizeStatusFilter 只接受白名单，其余回退 new', () => {
  assert.equal(normalizeStatusFilter(undefined), 'new');
  assert.equal(normalizeStatusFilter(''), 'new');
  assert.equal(normalizeStatusFilter('SAVED'), 'saved');
  assert.equal(normalizeStatusFilter('dismissed'), 'dismissed');
  assert.equal(normalizeStatusFilter('all'), 'all');
  assert.equal(normalizeStatusFilter('pushed'), 'new');
  assert.equal(normalizeStatusFilter('unknown'), 'new');
});

test('parseBasedOn 支持 JSON 数组与旧的逗号分隔格式', () => {
  assert.deepEqual(parseBasedOn('["AI/LLM","Python"]'), ['AI/LLM', 'Python']);
  assert.deepEqual(parseBasedOn('AI/LLM, Python'), ['AI/LLM', 'Python']);
  assert.deepEqual(parseBasedOn(''), []);
  assert.deepEqual(parseBasedOn(null), []);
  assert.deepEqual(parseBasedOn('{"a":1}'), []);
});

test('deriveRepoId 优先 repo_id，其次 owner/name，最后 GitHub URL', () => {
  assert.equal(
    deriveRepoId({ repo_id: 'owner/repo', owner: 'x', name: 'y', url: null }),
    'owner/repo'
  );
  assert.equal(
    deriveRepoId({ repo_id: null, owner: 'owner', name: 'repo', url: null }),
    'owner/repo'
  );
  assert.equal(
    deriveRepoId({
      repo_id: null,
      owner: null,
      name: null,
      url: 'https://github.com/foo/bar?tab=readme',
    }),
    'foo/bar'
  );
  assert.equal(deriveRepoId({ repo_id: null, owner: null, name: null, url: '' }), null);
});

test('normalizeDismissReason 去空白并截断到 200 字', () => {
  assert.equal(normalizeDismissReason('  不感兴趣  '), '不感兴趣');
  assert.equal(normalizeDismissReason('   '), null);
  assert.equal(normalizeDismissReason(42), null);
  assert.equal(normalizeDismissReason('x'.repeat(300))?.length, 200);
});

test('toRecommendation 输出前端 DTO 字段', () => {
  const dto = toRecommendation({
    id: 'rec-1',
    user_id: 'u1',
    repo_id: 'owner/repo',
    owner: 'owner',
    name: 'repo',
    description: 'desc',
    language: 'TypeScript',
    stars: 12,
    url: 'https://github.com/owner/repo',
    score: 0.8,
    reason: 'because',
    based_on: '["AI"]',
    status: 'saved',
    created_at: '2026-10-22 00:00:00',
  });
  assert.equal(dto.id, 'rec-1');
  assert.equal(dto.repoId, 'owner/repo');
  assert.deepEqual(dto.basedOn, ['AI']);
  assert.equal(dto.status, 'saved');
  assert.equal(dto.createdAt, '2026-10-22 00:00:00');
});

test('buildFeedbackRow 生成可入库的反馈行', () => {
  const row = buildFeedbackRow({
    id: 'fb-1',
    userId: 'u1',
    recommendationId: 'rec-1',
    repoId: 'owner/repo',
    action: 'dismissed',
    reason: '技术栈不匹配',
    createdAt: '2026-10-22T00:00:00.000Z',
  });
  assert.deepEqual(row, {
    id: 'fb-1',
    user_id: 'u1',
    recommendation_id: 'rec-1',
    repo_id: 'owner/repo',
    action: 'dismissed',
    reason: '技术栈不匹配',
    created_at: '2026-10-22T00:00:00.000Z',
  });
});

test('shouldKeepUserStatus 只保留 saved / dismissed', () => {
  assert.equal(shouldKeepUserStatus('saved'), true);
  assert.equal(shouldKeepUserStatus('dismissed'), true);
  assert.equal(shouldKeepUserStatus('new'), false);
  assert.equal(shouldKeepUserStatus(null), false);
});
