import assert from 'node:assert/strict';
import test from 'node:test';

import {
  clusterSignature,
  detectNameDuplicates,
  mergeDuplicateClusters,
  nameSimilarity,
  normalizeDuplicateScope,
  normalizeRepoKey,
  textTokens,
  tokenJaccard,
} from '../src/duplicates/helpers.ts';

function repo(source, repoId, overrides = {}) {
  return {
    source,
    repoId,
    platform: 'github',
    name: repoId.split('/').pop(),
    description: '',
    htmlUrl: `https://github.com/${repoId}`,
    stars: 0,
    language: '',
    readmeSummary: '',
    categoryId: '',
    techStack: [],
    ...overrides,
  };
}

test('scope 归一化只接受 my / trending / all', () => {
  assert.equal(normalizeDuplicateScope(undefined), 'all');
  assert.equal(normalizeDuplicateScope('my'), 'my');
  assert.equal(normalizeDuplicateScope('trending'), 'trending');
  assert.equal(normalizeDuplicateScope('all'), 'all');
  assert.equal(normalizeDuplicateScope('bad'), null);
});

test('仓库地址归一化：大小写 / .git / 末尾斜杠 / 平台', () => {
  assert.equal(
    normalizeRepoKey('github', 'Acme/Awesome-Tool', 'https://github.com/Acme/Awesome-Tool.git'),
    'github:acme/awesome-tool'
  );
  assert.equal(
    normalizeRepoKey('', 'acme/awesome-tool', 'http://www.github.com/acme/awesome-tool/'),
    'github:acme/awesome-tool'
  );
  assert.equal(
    normalizeRepoKey('', 'acme/awesome-tool', 'https://gitee.com/Acme/Awesome-Tool'),
    'gitee:acme/awesome-tool'
  );
});

test('名称相似度识别分隔符 / 驼峰', () => {
  assert.equal(nameSimilarity('tenant-admin', 'tenant_admin'), 1);
  assert.equal(nameSimilarity('tenantAdmin', 'tenant-admin'), 1);
  assert.ok(nameSimilarity('react-admin', 'react-admin-pro') > 0.8);
  assert.ok(nameSimilarity('langchain', 'numpy') < 0.4);
});

test('中文 bigram token 与 Jaccard', () => {
  const left = textTokens('多租户 SaaS 计费与订阅管理平台');
  const right = textTokens('多租户 SaaS 订阅计费管理平台');
  assert.ok(left.includes('多租') && left.includes('租户'));
  assert.ok(tokenJaccard(left, right) > 0.4);
  assert.equal(tokenJaccard(textTokens('Python 命令行工具'), textTokens('React 组件库')), 0);
});

test('地址完全一致跨来源聚成一簇，收藏库条目为保留项', () => {
  const clusters = detectNameDuplicates([
    repo('my', 'dup-test-acme/awesome-tool', {
      name: 'awesome-tool',
      description: 'Acme 的工具集',
      stars: 120,
      language: 'TypeScript',
      categoryId: 'devtools',
    }),
    repo('trending', 'dup-test-Acme/Awesome-Tool', {
      name: 'Awesome Tool',
      description: 'Acme 出品的工具集，支持插件扩展与多语言',
      stars: 900,
      techStack: ['Node.js', 'TypeScript'],
    }),
  ]);
  assert.equal(clusters.length, 1);
  const cluster = clusters[0];
  assert.equal(cluster.kind, 'exact');
  assert.equal(cluster.confidence, 1);
  assert.equal(cluster.suggestion.keep.source, 'my');
  assert.equal(cluster.suggestion.keep.repoId, 'dup-test-acme/awesome-tool');
  assert.equal(cluster.members.filter((member) => member.role === 'canonical').length, 1);
  const fields = new Map(cluster.suggestion.fields.map((field) => [field.field, field]));
  assert.equal(fields.get('description').from.source, 'trending');
  assert.equal(fields.get('stars').value, 900);
  assert.ok(fields.has('techStack'));
});

test('名称相似且简介相近才聚类，无关项目不误报', () => {
  const clusters = detectNameDuplicates([
    repo('my', 'dup-test-acme/tenant-admin', {
      name: 'tenant-admin',
      description: '多租户后台',
      stars: 10,
    }),
    repo('my', 'dup-test-acme/tenant_admin', {
      name: 'tenant_admin',
      description: '多租户后台模板',
      stars: 8,
    }),
    repo('my', 'dup-test-acme/payments', {
      name: 'payments',
      description: '支付网关 SDK',
      stars: 20,
    }),
    repo('my', 'dup-test-acme/charts', {
      name: 'charts',
      description: 'React 图表组件库',
      stars: 15,
    }),
  ]);
  assert.equal(clusters.length, 1);
  assert.equal(clusters[0].kind, 'name');
  assert.equal(clusters[0].members.length, 2);
});

test('簇签名与成员顺序无关', () => {
  const a = clusterSignature([
    { source: 'my', repoId: 'a' },
    { source: 'trending', repoId: 'b' },
  ]);
  const b = clusterSignature([
    { source: 'trending', repoId: 'b' },
    { source: 'my', repoId: 'a' },
  ]);
  assert.equal(a, b);
  assert.match(a, /^dup_[a-z0-9]+$/);
});

test('两批簇按成员交集合并并保留全部证据', () => {
  const remote = detectNameDuplicates([
    repo('my', 'dup-test-acme/awesome-tool', {
      name: 'awesome-tool',
      description: '开发者工具',
      stars: 10,
    }),
    repo('trending', 'dup-test-acme/awesome-tool', {
      name: 'awesome-tool',
      description: '开发者工具',
      stars: 20,
    }),
  ]);
  const local = detectNameDuplicates([
    repo('my', 'dup-test-acme/awesome-tool', {
      name: 'awesome-tool',
      description: '开发者工具',
      stars: 10,
    }),
    repo('my', 'dup-test-acme/awesome-tool2', {
      name: 'awesome-tool2',
      description: '开发者工具',
      stars: 9,
    }),
  ]);
  const merged = mergeDuplicateClusters([...remote, ...local]);
  assert.equal(merged.length, 1);
  assert.equal(merged[0].members.length, 3);
  assert.ok(merged[0].reasons.length >= 1);
});
