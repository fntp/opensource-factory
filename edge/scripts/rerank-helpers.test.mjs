import assert from 'node:assert/strict';
import test from 'node:test';

import {
  candidateFromRow,
  localRerank,
  normalizeRerankWeights,
  toRerankDetail,
} from '../src/rerank/helpers.ts';

test('权重归一化：默认和为 1，全 0 退化为相关性', () => {
  const defaults = normalizeRerankWeights();
  const total = Object.values(defaults).reduce((sum, value) => sum + value, 0);
  assert.ok(Math.abs(total - 1) < 1e-9);
  assert.ok(defaults.relevance > defaults.affinity);

  const zero = normalizeRerankWeights({
    relevance: 0,
    affinity: 0,
    freshness: 0,
    momentum: 0,
    popularity: 0,
    health: 0,
  });
  assert.equal(zero.relevance, 1);
  assert.equal(zero.health, 0);
});

test('候选转换：优先 base_score，缺失回退 score', () => {
  const row = {
    id: 'rec-1',
    user_id: 'u1',
    repo_id: 'owner/repo',
    owner: 'owner',
    name: 'repo',
    description: 'demo',
    language: 'Python',
    stars: 100,
    score: 0.6,
    base_score: 0.8,
    reason: null,
    based_on: null,
    url: 'https://github.com/owner/repo',
    status: 'new',
    created_at: null,
    updated_at: null,
  };
  const candidate = candidateFromRow(row);
  assert.equal(candidate.repoId, 'owner/repo');
  assert.equal(candidate.baseScore, 0.8);
  assert.equal(candidate.stars, 100);

  const legacy = candidateFromRow({ ...row, base_score: null, score: 0.55 });
  assert.equal(legacy.baseScore, 0.55);
});

test('本地精排：画像完整 + 健康度高的候选上位', () => {
  const result = localRerank(
    [
      {
        repoId: 'a/high-base',
        baseScore: 0.9,
        language: 'Go',
        stars: 10,
        description: '',
      },
      {
        repoId: 'b/fit',
        baseScore: 0.85,
        language: 'Python',
        stars: 500,
        description: 'web framework',
      },
    ],
    {
      topK: 2,
      mmrLambda: 1,
      weights: { relevance: 0.2, affinity: 0.1, freshness: 0, momentum: 0.1, popularity: 0.1, health: 0.5 },
      now: Date.parse('2026-10-22T00:00:00Z'),
    }
  );
  assert.equal(result.items[0].repoId, 'b/fit');
  assert.equal(result.items[0].rankBefore, 2);
  assert.equal(result.items[0].rankAfter, 1);
  assert.ok(result.items[0].reasons.length > 0);
  assert.equal(result.metrics.movedUp, 1);
});

test('本地精排：MMR 抑制同语言重复项', () => {
  const result = localRerank(
    [
      { repoId: 'a', baseScore: 0.9, language: 'Python', stars: 100, description: 'a' },
      { repoId: 'b', baseScore: 0.88, language: 'Python', stars: 90, description: 'b' },
      { repoId: 'c', baseScore: 0.8, language: 'Rust', stars: 80, description: 'c' },
    ],
    {
      topK: 2,
      mmrLambda: 0.5,
      weights: { relevance: 1, affinity: 0, freshness: 0, momentum: 0, popularity: 0, health: 0 },
      now: Date.parse('2026-10-22T00:00:00Z'),
    }
  );
  assert.deepEqual(
    result.items.map((item) => item.repoId),
    ['a', 'c']
  );
  assert.ok(result.metrics.diversityAfter > 0);
});

test('精排明细包含前后名次与信号', () => {
  const result = localRerank([{ repoId: 'a', baseScore: 0.7, language: 'Python', stars: 1 }], {
    topK: 1,
    now: Date.parse('2026-10-22T00:00:00Z'),
  });
  const detail = toRerankDetail(result.items[0]);
  assert.equal(detail.rankAfter, 1);
  assert.ok(detail.signals && 'relevance' in detail.signals);
  assert.ok(Array.isArray(detail.reasons));
});
