import assert from 'node:assert/strict';
import test from 'node:test';

import {
  buildTrendingSummary,
  parseTechStack,
  splitRepoId,
  toTrendingDetail,
} from '../src/trending/detail.ts';

const row = {
  id: 'openai/whisper',
  platform: 'github',
  name: 'whisper',
  html_url: 'https://github.com/openai/whisper',
  stars_today: 1234,
  description: 'Robust Speech Recognition',
  tech_stack: 'Python, PyTorch, Python',
  crawled_at: '2026-10-22',
  owner: 'openai',
  language: 'Python',
  stars: 65432,
  readme_summary: null,
};

test('parseTechStack 去空白、去重并保持顺序', () => {
  assert.deepEqual(parseTechStack('Python, PyTorch, Python, , RAG'), [
    'Python',
    'PyTorch',
    'RAG',
  ]);
  assert.deepEqual(parseTechStack(null), []);
});

test('摘要优先级：README 摘要 → 描述 → 技术栈', () => {
  assert.deepEqual(buildTrendingSummary({ ...row, readme_summary: '模型摘要' }), {
    summary: '模型摘要',
    source: 'readme',
  });
  assert.deepEqual(buildTrendingSummary(row), {
    summary: 'Robust Speech Recognition',
    source: 'description',
  });
  assert.deepEqual(
    buildTrendingSummary({ ...row, description: '   ', tech_stack: 'Go, Redis' }),
    { summary: '该项目主要使用 Go, Redis。', source: 'tech' }
  );
  assert.deepEqual(
    buildTrendingSummary({ ...row, description: '', tech_stack: '' }),
    { summary: null, source: 'empty' }
  );
});

test('toTrendingDetail 输出完整元信息', () => {
  const detail = toTrendingDetail({ ...row, readme_summary: '模型摘要' }, true);
  assert.equal(detail.id, 'openai/whisper');
  assert.equal(detail.owner, 'openai');
  assert.equal(detail.stars, 65432);
  assert.equal(detail.starsToday, 1234);
  assert.deepEqual(detail.techStack, ['Python', 'PyTorch']);
  assert.equal(detail.summary, '模型摘要');
  assert.equal(detail.summarySource, 'readme');
  assert.equal(detail.isFavorited, true);
});

test('splitRepoId 仅接受 owner/repo', () => {
  assert.deepEqual(splitRepoId('openai/whisper'), { owner: 'openai', name: 'whisper' });
  assert.equal(splitRepoId('openai'), null);
  assert.equal(splitRepoId('a/b/c'), null);
});
