import assert from 'node:assert/strict';
import test from 'node:test';

import {
  buildRepoUpdateId,
  normalizeUpdateKind,
  normalizeUpdateLimit,
  normalizeUpdateOffset,
  normalizeUpdateState,
  normalizeUpdateStatus,
  normalizeUpdateType,
  repoUpdateNotificationTitle,
  toRepoUpdateItem,
} from '../src/repo-updates/helpers.ts';

test('normalizeUpdateStatus 只接受 all / unread / read / dismissed', () => {
  assert.equal(normalizeUpdateStatus(undefined), 'all');
  assert.equal(normalizeUpdateStatus('UNREAD'), 'unread');
  assert.equal(normalizeUpdateStatus('read'), 'read');
  assert.equal(normalizeUpdateStatus('dismissed'), 'dismissed');
  assert.equal(normalizeUpdateStatus('weird'), 'all');
});

test('normalizeUpdateType 只接受 all / release / major', () => {
  assert.equal(normalizeUpdateType(undefined), 'all');
  assert.equal(normalizeUpdateType('MAJOR'), 'major');
  assert.equal(normalizeUpdateType('release'), 'release');
  assert.equal(normalizeUpdateType('other'), 'all');
});

test('normalizeUpdateLimit / Offset 边界', () => {
  assert.equal(normalizeUpdateLimit(undefined), 20);
  assert.equal(normalizeUpdateLimit('0'), 20);
  assert.equal(normalizeUpdateLimit('15'), 15);
  assert.equal(normalizeUpdateLimit('500'), 100);
  assert.equal(normalizeUpdateOffset('-1'), 0);
  assert.equal(normalizeUpdateOffset('40'), 40);
});

test('normalizeUpdateState / Kind 未知值回退', () => {
  assert.equal(normalizeUpdateState('read'), 'read');
  assert.equal(normalizeUpdateState('dismissed'), 'dismissed');
  assert.equal(normalizeUpdateState('weird'), 'unread');
  assert.equal(normalizeUpdateKind('major'), 'major');
  assert.equal(normalizeUpdateKind('release'), 'release');
  assert.equal(normalizeUpdateKind(null), 'release');
});

test('buildRepoUpdateId 对同一用户 + 仓库 + 版本稳定', () => {
  const first = buildRepoUpdateId('u1', 'owner/repo', 'v2.0.0');
  assert.equal(first, buildRepoUpdateId('u1', 'owner/repo', 'v2.0.0'));
  assert.notEqual(first, buildRepoUpdateId('u2', 'owner/repo', 'v2.0.0'));
  assert.notEqual(first, buildRepoUpdateId('u1', 'owner/repo', 'v2.0.1'));
});

test('repoUpdateNotificationTitle 区分重大变更', () => {
  assert.equal(
    repoUpdateNotificationTitle('major', 'owner/repo', 'v2.0.0'),
    '【重大变更】owner/repo v2.0.0'
  );
  assert.equal(
    repoUpdateNotificationTitle('release', 'owner/repo', 'v1.3.0'),
    'owner/repo 发布新版本 v1.3.0'
  );
});

test('toRepoUpdateItem 输出前端 DTO 字段', () => {
  const item = toRepoUpdateItem({
    id: 'repo-update:u1:owner/repo:v2.0.0',
    user_id: 'u1',
    repo_id: 'owner/repo',
    repo_name: 'repo',
    repo_url: 'https://github.com/owner/repo',
    type: 'major',
    version: 'v2.0.0',
    title: 'v2.0.0',
    summary: '重大重构',
    url: 'https://github.com/owner/repo/releases/tag/v2.0.0',
    published_at: '2026-10-20T00:00:00Z',
    detected_at: '2026-10-22T06:37:00Z',
    status: 'unread',
    read_at: null,
    payload: null,
    created_at: '2026-10-22T06:37:00Z',
  });
  assert.equal(item.repoId, 'owner/repo');
  assert.equal(item.repoName, 'repo');
  assert.equal(item.type, 'major');
  assert.equal(item.version, 'v2.0.0');
  assert.equal(item.status, 'unread');
  assert.equal(item.readAt, null);
});
