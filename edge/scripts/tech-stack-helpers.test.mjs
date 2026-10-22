import assert from 'node:assert/strict';
import test from 'node:test';

import {
  buildTechStackGraph,
  matchFrameworks,
  normalizeLanguage,
  normalizeToken,
} from '../src/tech-stack/aggregate.ts';

const NOW = new Date('2026-10-22T10:00:00Z');

function repo(id, language, extra = {}) {
  return {
    id,
    name: id.split('/')[1] ?? id,
    language,
    stars: 0,
    description: '',
    readme_summary: '',
    ...extra,
  };
}

test('normalizeToken 统一大小写与分隔符', () => {
  assert.equal(normalizeToken('Next.js'), 'next js');
  assert.equal(normalizeToken('shadcn/ui'), 'shadcn ui');
  assert.equal(normalizeToken('  React  '), 'react');
  assert.equal(normalizeToken('Tailwind_CSS'), 'tailwind css');
});

test('normalizeLanguage 归一常见别名并保留未知语言', () => {
  assert.equal(normalizeLanguage('typescript'), 'TypeScript');
  assert.equal(normalizeLanguage('golang'), 'Go');
  assert.equal(normalizeLanguage('Jupyter Notebook'), 'Jupyter Notebook');
  assert.equal(normalizeLanguage('Brainfuck'), 'Brainfuck');
  assert.equal(normalizeLanguage(''), null);
  assert.equal(normalizeLanguage(null), null);
});

test('matchFrameworks 优先按标签精确命中，忽略业务标签', () => {
  const result = matchFrameworks(repo('a/b', 'TypeScript'), [
    'React',
    'next-js',
    '支付',
    'tailwindcss',
  ]);
  assert.deepEqual(result, ['React', 'Next.js', 'Tailwind CSS']);
});

test('matchFrameworks 从简介 / 摘要识别框架并使用词边界', () => {
  const item = repo('a/b', 'Python', {
    description: '基于 FastAPI 与 PostgreSQL 的推荐服务，使用 Docker 部署。',
    readme_summary: '这是一个 reactive 风格的演示项目，也不会误命中 invite。',
  });
  const result = matchFrameworks(item, []);
  assert.ok(result.includes('FastAPI'));
  assert.ok(result.includes('PostgreSQL'));
  assert.ok(result.includes('Docker'));
  assert.ok(!result.includes('React'));
  assert.ok(!result.includes('Vite'));
});

test('buildTechStackGraph 聚合语言 / 框架 / 星标与覆盖率', () => {
  const repos = [
    repo('u/one', 'TypeScript', {
      stars: 100,
      description: 'React 管理后台',
    }),
    repo('u/two', 'TypeScript', {
      stars: 50,
      readme_summary: '使用 Next.js 与 Tailwind CSS 构建',
    }),
    repo('u/three', 'Python', {
      stars: 30,
      description: 'FastAPI 服务',
    }),
    repo('u/four', null, {
      stars: 10,
      description: '一个没有语言字段的仓库',
    }),
  ];
  const tags = [
    { repo_id: 'u/one', name: 'React' },
    { repo_id: 'u/one', name: '支付' },
    { repo_id: 'u/three', name: 'FastAPI' },
  ];

  const data = buildTechStackGraph(repos, tags, { now: NOW });

  assert.equal(data.summary.totalRepos, 4);
  assert.equal(data.summary.withLanguage, 3);
  assert.equal(data.summary.withFramework, 3);
  assert.equal(data.summary.languageCount, 2);
  assert.equal(data.summary.topLanguage, 'TypeScript');
  assert.equal(data.summary.topFramework, 'React');
  assert.equal(data.summary.totalStars, 190);
  assert.equal(data.summary.coverage, 75);
  assert.equal(data.generatedAt, NOW.toISOString());

  const typescript = data.languages.find((item) => item.name === 'TypeScript');
  assert.equal(typescript.repoCount, 2);
  assert.equal(typescript.starCount, 150);
  assert.equal(typescript.share, 50);
  assert.ok(typescript.frameworks.includes('React'));
  assert.ok(typescript.frameworks.includes('Next.js'));

  const react = data.frameworks.find((item) => item.name === 'React');
  assert.equal(react.category, '前端');
  assert.equal(react.repoCount, 1);
  assert.deepEqual(react.languages, ['TypeScript']);
});

test('buildTechStackGraph 图谱只保留 Top N 且连线权重正确', () => {
  const repos = [
    repo('u/a', 'TypeScript', { description: 'React React' }),
    repo('u/b', 'TypeScript', { description: 'React 与 Vue' }),
    repo('u/c', 'Python', { description: 'Django 与 Celery' }),
    repo('u/d', 'Go', { description: 'Docker 与 Kubernetes' }),
  ];
  const tags = [
    { repo_id: 'u/a', name: 'React' },
    { repo_id: 'u/b', name: 'React' },
    { repo_id: 'u/b', name: 'Vue' },
  ];

  const data = buildTechStackGraph(repos, tags, {
    now: NOW,
    maxLanguages: 2,
    maxFrameworks: 3,
  });

  const languageNodes = data.graph.nodes.filter((node) => node.kind === 'language');
  assert.equal(languageNodes.length, 2);
  assert.ok(data.graph.nodes.length <= 5);
  const reactLink = data.graph.links.find(
    (link) => link.source === 'lang:TypeScript' && link.target === 'fw:React'
  );
  assert.equal(reactLink.weight, 2);
  assert.equal(data.graph.links[0].weight >= data.graph.links.at(-1).weight, true);
});

test('buildTechStackGraph 空数据返回稳定空结构', () => {
  const data = buildTechStackGraph([], [], { now: NOW });
  assert.equal(data.summary.totalRepos, 0);
  assert.equal(data.summary.coverage, 0);
  assert.equal(data.summary.topLanguage, null);
  assert.equal(data.summary.topFramework, null);
  assert.deepEqual(data.languages, []);
  assert.deepEqual(data.frameworks, []);
  assert.deepEqual(data.graph.nodes, []);
  assert.deepEqual(data.graph.links, []);
});
