import assert from 'node:assert/strict';
import test from 'node:test';

import {
  clampSimilarTopK,
  fallbackReason,
  fallbackScore,
  normalizeSimilarScope,
  normalizeSimilarSource,
  parseBoolean,
  sharedTechStack,
} from '../src/similar/helpers.ts';

test('source / scope / topK / boolean 归一化', () => {
  assert.equal(normalizeSimilarSource('my'), 'my');
  assert.equal(normalizeSimilarSource('trending'), 'trending');
  assert.equal(normalizeSimilarSource('all'), null);

  assert.equal(normalizeSimilarScope(undefined), 'all');
  assert.equal(normalizeSimilarScope('my'), 'my');
  assert.equal(normalizeSimilarScope('bad'), null);

  assert.equal(clampSimilarTopK(undefined), 8);
  assert.equal(clampSimilarTopK('0'), 1);
  assert.equal(clampSimilarTopK('999'), 30);
  assert.equal(clampSimilarTopK('6'), 6);

  assert.equal(parseBoolean('true'), true);
  assert.equal(parseBoolean('0'), false);
  assert.equal(parseBoolean(undefined, true), true);
});

test('关键词兜底打分：同语言 + 共享技术栈最高', () => {
  assert.equal(fallbackScore('TypeScript', ['React'], 'TypeScript', ['React']), 0.55);
  assert.equal(fallbackScore('TypeScript', ['React'], 'TypeScript', ['Vue']), 0.4);
  assert.equal(fallbackScore('TypeScript', ['React'], 'JavaScript', ['React']), 0.3);
  assert.equal(fallbackScore('TypeScript', ['React'], 'Python', ['Django']), 0);
  assert.equal(fallbackScore('', [], '', []), 0);
});

test('共享技术栈忽略大小写并保持种子顺序', () => {
  assert.deepEqual(sharedTechStack(['React', 'TypeScript'], ['typescript', 'react']), [
    'React',
    'TypeScript',
  ]);
  assert.deepEqual(sharedTechStack([], ['React']), []);
});

test('兜底理由明确是技术栈 / 语言匹配', () => {
  assert.equal(
    fallbackReason('langchain', 'Python', ['LLM']),
    '与「langchain」同属 LLM 技术栈。'
  );
  assert.equal(fallbackReason('langchain', 'Python', []), '与「langchain」主要语言同为 Python。');
  assert.equal(fallbackReason('langchain', '', []), '与「langchain」语言 / 技术栈相近。');
});
