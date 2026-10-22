import assert from 'node:assert/strict';
import test from 'node:test';

import {
  buildRecommendationNotification,
  normalizeNotificationLimit,
  normalizeNotificationOffset,
  normalizeNotificationState,
  normalizeNotificationStatus,
  parseBasedOn,
  recommendationTitle,
  toNotificationItem,
  truncateText,
} from '../src/notifications/helpers.ts';

test('normalizeNotificationStatus 只接受 all / unread / read', () => {
  assert.equal(normalizeNotificationStatus(undefined), 'all');
  assert.equal(normalizeNotificationStatus(''), 'all');
  assert.equal(normalizeNotificationStatus('UNREAD'), 'unread');
  assert.equal(normalizeNotificationStatus('read'), 'read');
  assert.equal(normalizeNotificationStatus('dismissed'), 'all');
  assert.equal(normalizeNotificationStatus('unknown'), 'all');
});

test('normalizeNotificationLimit 默认 20，范围 1~100', () => {
  assert.equal(normalizeNotificationLimit(undefined), 20);
  assert.equal(normalizeNotificationLimit(''), 20);
  assert.equal(normalizeNotificationLimit('0'), 20);
  assert.equal(normalizeNotificationLimit('-3'), 20);
  assert.equal(normalizeNotificationLimit('15'), 15);
  assert.equal(normalizeNotificationLimit('500'), 100);
});

test('normalizeNotificationOffset 负数归零并限制上限', () => {
  assert.equal(normalizeNotificationOffset(undefined), 0);
  assert.equal(normalizeNotificationOffset('-1'), 0);
  assert.equal(normalizeNotificationOffset('40'), 40);
  assert.equal(normalizeNotificationOffset('999999'), 10000);
});

test('parseBasedOn 支持 JSON 数组与旧逗号格式', () => {
  assert.deepEqual(parseBasedOn('["AI/LLM","Python"]'), ['AI/LLM', 'Python']);
  assert.deepEqual(parseBasedOn('AI/LLM, Python'), ['AI/LLM', 'Python']);
  assert.deepEqual(parseBasedOn(''), []);
  assert.deepEqual(parseBasedOn(null), []);
  assert.deepEqual(parseBasedOn('{"a":1}'), []);
});

test('normalizeNotificationState 未知状态按未读处理', () => {
  assert.equal(normalizeNotificationState('read'), 'read');
  assert.equal(normalizeNotificationState('dismissed'), 'dismissed');
  assert.equal(normalizeNotificationState('unread'), 'unread');
  assert.equal(normalizeNotificationState(null), 'unread');
  assert.equal(normalizeNotificationState('weird'), 'unread');
});

test('recommendationTitle 依次回退 owner/name、name、repo_id', () => {
  assert.equal(
    recommendationTitle({
      id: 'r1',
      user_id: 'u1',
      owner: 'owner',
      name: 'repo',
      repo_id: 'owner/repo',
    }),
    'owner/repo'
  );
  assert.equal(
    recommendationTitle({ id: 'r2', user_id: 'u1', owner: null, name: 'repo' }),
    'repo'
  );
  assert.equal(
    recommendationTitle({ id: 'r3', user_id: 'u1', owner: null, name: null, repo_id: 'a/b' }),
    'a/b'
  );
  assert.equal(
    recommendationTitle({ id: 'r4', user_id: 'u1', owner: null, name: null }),
    '为你推荐的开源项目'
  );
});

test('buildRecommendationNotification 生成幂等通知行', () => {
  const row = buildRecommendationNotification(
    {
      id: 'rec-1',
      user_id: 'u1',
      repo_id: 'owner/repo',
      owner: 'owner',
      name: 'repo',
      description: '一个项目',
      language: 'TypeScript',
      stars: 42,
      score: 0.87,
      reason: '与你收藏的项目相似',
      based_on: '["AI/LLM","TypeScript"]',
      url: 'https://github.com/owner/repo',
      status: 'pushed',
      created_at: '2026-10-22 08:30:00',
    },
    'u1',
    'ntf-1',
    '2026-10-22T08:30:00.000Z'
  );

  assert.equal(row.id, 'ntf-1');
  assert.equal(row.user_id, 'u1');
  assert.equal(row.type, 'recommendation');
  assert.equal(row.title, 'owner/repo');
  assert.equal(row.body, '一个项目');
  assert.equal(row.repo_id, 'owner/repo');
  assert.equal(row.recommendation_id, 'rec-1');
  assert.equal(row.dedupe_key, 'recommendation:rec-1');
  assert.equal(row.status, 'unread');
  assert.equal(row.created_at, '2026-10-22 08:30:00');
  assert.deepEqual(JSON.parse(row.payload), {
    basedOn: ['AI/LLM', 'TypeScript'],
  });
});

test('toNotificationItem 输出前端 DTO 字段', () => {
  const dto = toNotificationItem({
    id: 'ntf-1',
    user_id: 'u1',
    type: 'recommendation',
    title: 'owner/repo',
    body: 'desc',
    url: 'https://github.com/owner/repo',
    repo_id: 'owner/repo',
    recommendation_id: 'rec-1',
    dedupe_key: 'recommendation:rec-1',
    score: 0.9,
    reason: 'because',
    language: 'Go',
    stars: 12,
    status: 'read',
    payload: '{"basedOn":["AI"]}',
    created_at: '2026-10-22 00:00:00',
    read_at: '2026-10-22 01:00:00',
  });
  assert.equal(dto.id, 'ntf-1');
  assert.equal(dto.type, 'recommendation');
  assert.equal(dto.repoId, 'owner/repo');
  assert.equal(dto.recommendationId, 'rec-1');
  assert.equal(dto.status, 'read');
  assert.equal(dto.stars, 12);
  assert.equal(dto.readAt, '2026-10-22 01:00:00');
});

test('truncateText 去空白并截断', () => {
  assert.equal(truncateText('  hi  ', 10), 'hi');
  assert.equal(truncateText('abcdef', 3), 'abc');
  assert.equal(truncateText(null, 3), '');
  assert.equal(truncateText(42, 10), '42');
});
