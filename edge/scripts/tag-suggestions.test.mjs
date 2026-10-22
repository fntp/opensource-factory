import assert from 'node:assert/strict';
import test from 'node:test';

import {
  buildLocalGenerateResult,
  clampLimit,
  clampOffset,
  clampPerRepo,
  hashSuggestionId,
  localSuggestTags,
  mergeGeneratedTags,
  normalizeGeneratedResult,
  normalizeSuggestionStatus,
  normalizeTagKey,
  toTagSuggestionDto,
} from '../src/tag-suggestions/helpers.ts';

const SUMMARY =
  '这个项目是一个面向开发者的智能工作台，后端基于 Python FastAPI 构建，' +
  '前端使用 React 与 TypeScript，支持大模型对话与私有化部署。';

test('normalizeTagKey 去 # / 压缩空白 / 小写', () => {
  assert.equal(normalizeTagKey('  #AI/LLM '), 'ai/llm');
  assert.equal(normalizeTagKey('Next.js'), 'next.js');
  assert.equal(normalizeTagKey('多  租户'), '多 租户');
});

test('hashSuggestionId 稳定且随用户 / 仓库 / 标签变化', () => {
  const first = hashSuggestionId('u1', 'owner/repo', 'React');
  assert.equal(first, hashSuggestionId('u1', 'owner/repo', 'react'));
  assert.notEqual(first, hashSuggestionId('u2', 'owner/repo', 'React'));
  assert.notEqual(first, hashSuggestionId('u1', 'owner/other', 'React'));
  assert.notEqual(first, hashSuggestionId('u1', 'owner/repo', 'Vue'));
  assert.match(first, /^ts_[0-9a-f]{16}$/);
});

test('clampLimit / clampOffset / clampPerRepo / 状态归一化', () => {
  assert.equal(clampLimit(undefined), 50);
  assert.equal(clampLimit('0'), 50);
  assert.equal(clampLimit('15'), 15);
  assert.equal(clampLimit('500'), 200);
  assert.equal(clampOffset('-1'), 0);
  assert.equal(clampOffset('999999'), 10000);
  assert.equal(clampPerRepo(undefined), 6);
  assert.equal(clampPerRepo('99'), 10);
  assert.equal(normalizeSuggestionStatus(undefined), 'pending');
  assert.equal(normalizeSuggestionStatus('ACCEPTED'), 'accepted');
  assert.equal(normalizeSuggestionStatus('all'), 'all');
  assert.equal(normalizeSuggestionStatus('unknown'), 'pending');
});

test('localSuggestTags 语言优先、词边界与中文关键词', () => {
  const tags = localSuggestTags(SUMMARY, 'Python', 10);
  const names = tags.map((tag) => tag.name);
  assert.equal(names[0], 'Python');
  assert.ok(names.includes('FastAPI'));
  assert.ok(names.includes('React'));
  assert.ok(names.includes('AI/LLM'));
  assert.ok(names.includes('自托管'));

  const reactive = localSuggestTags('一个 reactive 风格的实验项目。', '');
  assert.ok(!reactive.some((tag) => tag.name === 'React'));
});

test('mergeGeneratedTags 按归一化名称去重并保留高分', () => {
  const merged = mergeGeneratedTags([
    { name: 'React', category: 'framework', score: 0.7, reason: '', evidence: '' },
    { name: 'react', category: 'framework', score: 0.8, reason: '', evidence: '' },
    { name: 'Vue', category: 'framework', score: 0.6, reason: '', evidence: '' },
  ]);
  assert.equal(merged.length, 2);
  assert.equal(merged[0].name, 'react');
  assert.equal(merged[0].score, 0.8);
});

test('buildLocalGenerateResult 跳过无摘要仓库并标记 source', () => {
  const result = buildLocalGenerateResult(
    [
      { id: 'a/has', language: 'Python', summary: SUMMARY },
      { id: 'a/empty', language: 'Go', summary: '' },
    ],
    3
  );
  assert.equal(result.scanned, 2);
  assert.equal(result.suggested, 1);
  assert.equal(result.skipped, 1);
  assert.equal(result.source, 'local');
  assert.equal(result.items[0].repoId, 'a/has');
  assert.ok(result.items[0].tags.length <= 3);
});

test('normalizeGeneratedResult 过滤非授权仓库与非法标签', () => {
  const result = normalizeGeneratedResult(
    {
      generatedAt: '2026-10-22T00:00:00Z',
      scanned: 2,
      items: [
        {
          repoId: 'a/ok',
          tags: [
            { name: 'Python', category: 'language', score: 0.83, reason: 'r', evidence: 'e' },
            { name: '', category: 'domain', score: 0.9 },
          ],
        },
        { repoId: 'a/other', tags: [{ name: 'Vue', category: 'framework', score: 0.7 }] },
      ],
    },
    ['a/ok'],
    6
  );
  assert.ok(result);
  assert.equal(result.source, 'vps');
  assert.equal(result.items.length, 1);
  assert.equal(result.items[0].repoId, 'a/ok');
  assert.deepEqual(result.items[0].tags.map((tag) => tag.name), ['Python']);
  assert.equal(result.suggested, 1);
  assert.equal(result.skipped, 1);

  assert.equal(normalizeGeneratedResult(null, ['a/ok']), null);
  assert.equal(normalizeGeneratedResult({ items: 'bad' }, ['a/ok']), null);
});

test('toTagSuggestionDto 提供默认值与仓库信息', () => {
  const dto = toTagSuggestionDto({
    id: 'ts_1',
    user_id: 'u1',
    repo_id: 'owner/repo',
    tag_name: 'Python',
    normalized_name: 'python',
    category: 'language',
    score: 0.83,
    reason: '语言字段为 Python',
    evidence: 'language 字段：Python',
    status: 'pending',
    created_at: '2026-10-22 00:00:00',
    updated_at: '2026-10-22 00:00:00',
  });
  assert.equal(dto.repoName, 'owner/repo');
  assert.equal(dto.repoUrl, 'https://github.com/owner/repo');
  assert.equal(dto.summary, '');
  assert.equal(dto.category, 'language');
  assert.equal(dto.status, 'pending');

  const fallback = toTagSuggestionDto({
    id: 'ts_2',
    user_id: 'u1',
    repo_id: 'owner/repo',
    tag_name: 'X',
    normalized_name: 'x',
    category: 'unknown',
    score: 0.5,
    reason: null,
    evidence: null,
    status: 'weird',
    created_at: '',
    updated_at: '',
  });
  assert.equal(fallback.category, 'domain');
  assert.equal(fallback.status, 'pending');
});
