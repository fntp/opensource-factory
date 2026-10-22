/**
 * 标签名称 / 查询参数纯逻辑单测（node --test）
 * 运行：cd edge && npm run test:scripts
 */
import assert from 'node:assert/strict';
import test from 'node:test';
import {
  escapeLikePattern,
  normalizeTagName,
  parseTagId,
  parseTagListQuery,
  TAG_NAME_MAX_LENGTH,
  validateTagName,
} from '../src/tags/logic.ts';

test('normalizeTagName：去首尾空白并压缩连续空白', () => {
  assert.equal(normalizeTagName('  React   Hooks  '), 'React Hooks');
  assert.equal(normalizeTagName('大模型\t推理'), '大模型 推理');
  assert.equal(normalizeTagName(null), '');
  assert.equal(normalizeTagName(42), '');
});

test('validateTagName：接受中文、空格与常见符号', () => {
  assert.deepEqual(validateTagName('  AI / LLM  '), { ok: true, name: 'AI / LLM' });
  assert.deepEqual(validateTagName('大模型'), { ok: true, name: '大模型' });
  assert.deepEqual(validateTagName('C++'), { ok: true, name: 'C++' });
});

test('validateTagName：拒绝空名、超长、逗号与控制字符', () => {
  assert.deepEqual(validateTagName('   '), { ok: false, error: 'tag_name_required' });
  assert.deepEqual(validateTagName(undefined), { ok: false, error: 'tag_name_required' });
  assert.deepEqual(validateTagName('a'.repeat(TAG_NAME_MAX_LENGTH + 1)), {
    ok: false,
    error: 'tag_name_too_long',
  });
  assert.deepEqual(validateTagName('React,Vue'), {
    ok: false,
    error: 'tag_name_invalid_chars',
  });
  assert.deepEqual(validateTagName('a\u0000b'), {
    ok: false,
    error: 'tag_name_invalid_chars',
  });
});

test('validateTagName：长度按 Unicode 码点计算', () => {
  const name = '🚀'.repeat(TAG_NAME_MAX_LENGTH);
  assert.deepEqual(validateTagName(name), { ok: true, name });
});

test('parseTagId：只接受正整数', () => {
  assert.equal(parseTagId('1'), 1);
  assert.equal(parseTagId('42'), 42);
  assert.equal(parseTagId('0'), null);
  assert.equal(parseTagId('-1'), null);
  assert.equal(parseTagId('1.5'), null);
  assert.equal(parseTagId('abc'), null);
  assert.equal(parseTagId(undefined), null);
});

test('parseTagListQuery：合法值透传，非法值回落默认', () => {
  assert.deepEqual(parseTagListQuery('  ai  ', 'name', 'asc'), {
    q: 'ai',
    sort: 'name',
    order: 'asc',
  });
  assert.deepEqual(parseTagListQuery(undefined, 'unknown', 'sideways'), {
    q: '',
    sort: 'count',
    order: 'desc',
  });
});

test('escapeLikePattern：转义 %、_ 与反斜杠', () => {
  assert.equal(escapeLikePattern('100%_test'), '100\\%\\_test');
  assert.equal(escapeLikePattern('a\\b'), 'a\\\\b');
  assert.equal(escapeLikePattern('normal'), 'normal');
});
