import assert from 'node:assert/strict';
import test from 'node:test';

import {
  evaluateHealth,
  healthFromRow,
  normalizeHealthStatus,
  summarizeRepoHealth,
} from '../src/repos/health.ts';

const NOW = new Date('2026-10-22T10:00:00Z');
const daysAgo = (days) => new Date(NOW.getTime() - days * 24 * 60 * 60 * 1000).toISOString();

test('健康度分档：活跃 / 需关注 / 停滞 / 未知', () => {
  const active = evaluateHealth({ pushedAt: daysAgo(10), stars: 100, now: NOW });
  assert.equal(active.status, 'active');
  assert.equal(active.score, 100);
  assert.equal(active.daysSincePush, 10);
  assert.equal(active.label, '活跃');

  const attention = evaluateHealth({ pushedAt: daysAgo(120), stars: 100, now: NOW });
  assert.equal(attention.status, 'attention');
  assert.equal(attention.score, 75);

  const stale = evaluateHealth({ pushedAt: daysAgo(400), stars: 100, now: NOW });
  assert.equal(stale.status, 'stale');
  assert.equal(stale.score, 25);
  assert.ok(stale.reasons.some((reason) => reason.includes('建议评估')));

  const unknown = evaluateHealth({ pushedAt: null, now: NOW });
  assert.equal(unknown.status, 'unknown');
  assert.equal(unknown.score, 0);
});

test('归档优先于一切；禁用最多 30 分且强制停滞', () => {
  const archived = evaluateHealth({ pushedAt: daysAgo(1), archived: true, now: NOW });
  assert.equal(archived.status, 'archived');
  assert.equal(archived.score, 0);
  assert.deepEqual(archived.reasons, ['仓库已归档，不再接收更新']);

  const disabled = evaluateHealth({ pushedAt: daysAgo(1), disabled: true, now: NOW });
  assert.equal(disabled.status, 'stale');
  assert.ok(disabled.score <= 30);
  assert.ok(disabled.reasons.some((reason) => reason.includes('禁用')));
});

test('issue 压力只扣分，不改变活跃状态', () => {
  const health = evaluateHealth({
    pushedAt: daysAgo(5),
    openIssues: 60,
    stars: 100,
    now: NOW,
  });
  assert.equal(health.status, 'active');
  assert.equal(health.score, 80);
  assert.ok(health.reasons.some((reason) => reason.includes('未关闭 issue')));
});

test('healthFromRow 优先采用 VPS 回写结果', () => {
  const row = {
    id: 'openai/whisper',
    platform: 'github',
    name: 'whisper',
    description: null,
    html_url: 'https://github.com/openai/whisper',
    stars: 100,
    language: 'Python',
    readme_summary: null,
    category_id: null,
    created_at: null,
    user_id: 'u1',
    owner: 'openai',
    forks: 0,
    updated_at: null,
    synced_at: null,
    pushed_at: daysAgo(120),
    open_issues_count: 3,
    archived: 0,
    disabled: 0,
    health_status: 'attention',
    health_score: 66,
    health_checked_at: '2026-10-22 09:00:00',
  };
  const health = healthFromRow(row, NOW);
  assert.equal(health.status, 'attention');
  assert.equal(health.score, 66);
  assert.equal(health.checkedAt, '2026-10-22T09:00:00Z');
  assert.equal(health.openIssues, 3);

  const local = healthFromRow({ ...row, health_status: null, health_checked_at: null }, NOW);
  assert.equal(local.status, 'attention');
  assert.equal(local.score, 70); // 120 天档位 70 分；3/100 未达 0.2 比例不扣分
});

test('summarizeRepoHealth 汇总计数与平均分', () => {
  const summary = summarizeRepoHealth([
    { health: { status: 'active', score: 100 } },
    { health: { status: 'attention', score: 70 } },
    { health: { status: 'stale', score: 30 } },
    { health: { status: 'archived', score: 0 } },
    { health: { status: 'unknown', score: 0 } },
  ]);
  assert.deepEqual(summary, {
    total: 5,
    active: 1,
    attention: 1,
    stale: 1,
    archived: 1,
    unknown: 1,
    averageScore: 40,
  });
  assert.equal(normalizeHealthStatus('ARCHIVED'), 'archived');
  assert.equal(normalizeHealthStatus('bogus'), 'unknown');
});
