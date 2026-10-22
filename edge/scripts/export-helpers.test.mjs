import assert from 'node:assert/strict';
import test from 'node:test';

import {
  buildExport,
  buildKnowledgeExport,
  buildMarkdownExport,
  buildObsidianEntries,
  buildStoreZip,
  crc32,
  escapeInline,
  exportFileName,
  formatStars,
  normalizeExportOptions,
  obsidianTag,
  safeFileName,
} from '../src/export/build.ts';

const ROWS = [
  {
    id: 'acme/alpha',
    platform: 'github',
    name: 'alpha',
    description: '支付网关 [SDK]',
    html_url: 'https://github.com/acme/alpha',
    stars: 1200,
    language: 'TypeScript',
    readme_summary: '一个支付网关 SDK。',
    category_id: 'cat-pay',
    created_at: '2026-09-01 08:00:00',
    owner: 'acme',
    forks: 30,
    updated_at: '2026-10-20T08:00:00Z',
    synced_at: null,
    category_name: '支付系统',
    tag_names: '支付,SDK,支付',
  },
  {
    id: 'acme/beta',
    platform: 'github',
    name: 'beta',
    description: null,
    html_url: 'https://github.com/acme/beta',
    stars: 50,
    language: 'Python',
    readme_summary: null,
    category_id: null,
    created_at: '2026-09-02 08:00:00',
    owner: 'acme',
    forks: 3,
    updated_at: null,
    synced_at: '2026-10-21T08:00:00Z',
    category_name: null,
    tag_names: null,
  },
  {
    id: 'acme/gamma',
    platform: 'gitee',
    name: 'gamma',
    description: '轻量工具',
    html_url: 'https://gitee.com/acme/gamma',
    stars: 5,
    language: null,
    readme_summary: '工具摘要',
    category_id: 'cat-tool',
    created_at: null,
    owner: 'acme',
    forks: null,
    updated_at: null,
    synced_at: null,
    category_name: '工具',
    tag_names: '工具',
  },
];

const USER = { login: 'fntp', name: 'Fntp' };
const NOW = '2026-10-22T10:00:00.000Z';

function readZipEntries(bytes) {
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  let eocd = -1;
  for (let i = bytes.length - 22; i >= 0; i -= 1) {
    if (view.getUint32(i, true) === 0x06054b50) {
      eocd = i;
      break;
    }
  }
  assert.notEqual(eocd, -1, 'EOCD 存在');
  const total = view.getUint16(eocd + 10, true);
  let offset = view.getUint32(eocd + 16, true);
  const names = [];
  const decoder = new TextDecoder();
  for (let i = 0; i < total; i += 1) {
    assert.equal(view.getUint32(offset, true), 0x02014b50, '中央目录签名');
    const nameLength = view.getUint16(offset + 28, true);
    const extraLength = view.getUint16(offset + 30, true);
    const commentLength = view.getUint16(offset + 32, true);
    const nameBytes = bytes.slice(offset + 46, offset + 46 + nameLength);
    names.push(decoder.decode(nameBytes));
    offset += 46 + nameLength + extraLength + commentLength;
  }
  return names;
}

test('normalizeExportOptions 默认 markdown / 含摘要 / 按分类', () => {
  assert.deepEqual(normalizeExportOptions({}), {
    format: 'markdown',
    includeSummary: true,
    groupBy: 'category',
  });
  assert.equal(normalizeExportOptions({ format: 'JSON' }).format, 'json');
  assert.equal(normalizeExportOptions({ format: 'obsidian' }).format, 'obsidian');
  assert.equal(normalizeExportOptions({ format: 'pdf' }).format, 'markdown');
  assert.equal(normalizeExportOptions({ includeSummary: '0' }).includeSummary, false);
  assert.equal(normalizeExportOptions({ includeSummary: 'false' }).includeSummary, false);
  assert.equal(normalizeExportOptions({ groupBy: 'none' }).groupBy, 'none');
  assert.equal(normalizeExportOptions({ groupBy: 'language' }).groupBy, 'category');
});

test('buildKnowledgeExport 聚合统计、分类、标签并按 Star 排序', () => {
  const data = buildKnowledgeExport(ROWS, USER, NOW);
  assert.equal(data.schema, 'openfactory.knowledge.v1');
  assert.equal(data.version, 1);
  assert.equal(data.user.login, 'fntp');
  assert.equal(data.stats.totalRepos, 3);
  assert.equal(data.stats.withSummary, 2);
  assert.equal(data.stats.categories, 3); // 支付系统 / 工具 / 未分类
  assert.equal(data.stats.tags, 3); // 支付 / SDK / 工具
  assert.equal(data.stats.totalStars, 1255);
  assert.deepEqual(
    data.repositories.map((repo) => repo.fullName),
    ['acme/alpha', 'acme/beta', 'acme/gamma']
  );
  assert.deepEqual(data.repositories[0].tags, ['支付', 'SDK']);
  const categoryByName = new Map(data.categories.map((category) => [category.name, category]));
  assert.equal(categoryByName.get('支付系统').repoCount, 1);
  assert.equal(categoryByName.get('工具').repoCount, 1);
  assert.equal(data.categories.at(-1).name, '未分类');
  assert.equal(data.tags.find((tag) => tag.name === '支付').count, 1);
});

test('buildMarkdownExport 生成 frontmatter、目录、分类与摘要', () => {
  const data = buildKnowledgeExport(ROWS, USER, NOW);
  const markdown = buildMarkdownExport(data, {
    format: 'markdown',
    includeSummary: true,
    groupBy: 'category',
  });
  assert.match(markdown, /^---\ntitle: "我的开源知识库"/);
  assert.match(markdown, /## 目录/);
  assert.match(markdown, /## 支付系统/);
  assert.match(markdown, /## 未分类/);
  assert.match(markdown, /### \[acme\/alpha\]\(https:\/\/github.com\/acme\/alpha\)/);
  assert.match(markdown, /支付网关 \\\[SDK\\\]/);
  assert.match(markdown, /\*\*摘要\*\*：一个支付网关 SDK。/);
  assert.match(markdown, /⭐ 1.2k/);
});

test('buildMarkdownExport 关闭摘要后不输出摘要正文', () => {
  const data = buildKnowledgeExport(ROWS, USER, NOW);
  const markdown = buildMarkdownExport(data, {
    format: 'markdown',
    includeSummary: false,
    groupBy: 'none',
  });
  assert.doesNotMatch(markdown, /\*\*摘要\*\*/);
  assert.doesNotMatch(markdown, /一个支付网关 SDK。/);
  assert.match(markdown, /## 全部项目/);
});

test('buildObsidianEntries 生成 README、分类笔记与仓库笔记', () => {
  const data = buildKnowledgeExport(ROWS, USER, NOW);
  const entries = buildObsidianEntries(data, {
    format: 'obsidian',
    includeSummary: true,
    groupBy: 'category',
  });
  const names = entries.map((entry) => entry.name);
  assert.ok(names.includes('README.md'));
  assert.ok(names.includes('20-分类/支付系统.md'));
  assert.ok(names.includes('20-分类/未分类.md'));
  assert.ok(names.includes('10-项目/支付系统/acme--alpha.md'));
  assert.ok(names.includes('10-项目/未分类/acme--beta.md'));

  const note = entries.find((entry) => entry.name === '10-项目/支付系统/acme--alpha.md');
  assert.match(note.content, /title: "acme\/alpha"/);
  assert.match(note.content, /"lang\/typescript"/);
  assert.match(note.content, /"tag\/支付"/);
  assert.match(note.content, /"cat\/支付系统"/);
  assert.match(note.content, /## 摘要/);
  assert.match(note.content, /\[GitHub\]\(https:\/\/github.com\/acme\/alpha\)/);
});

test('buildObsidianEntries 关闭摘要时不写摘要段', () => {
  const data = buildKnowledgeExport(ROWS, USER, NOW);
  const entries = buildObsidianEntries(data, {
    format: 'obsidian',
    includeSummary: false,
    groupBy: 'none',
  });
  const note = entries.find((entry) => entry.name === '10-项目/acme--alpha.md');
  assert.ok(note);
  assert.doesNotMatch(note.content, /## 摘要/);
  assert.doesNotMatch(note.content, /一个支付网关 SDK。/);
});

test('buildStoreZip 输出可解析的 ZIP 中央目录', () => {
  const bytes = buildStoreZip(
    [
      { name: 'README.md', content: '# 知识库' },
      { name: '10-项目/a--b.md', content: '---\ntitle: b\n---\n' },
    ],
    new Date('2026-10-22T10:00:00Z')
  );
  assert.equal(bytes[0], 0x50);
  assert.equal(bytes[1], 0x4b);
  assert.deepEqual(readZipEntries(bytes), ['README.md', '10-项目/a--b.md']);
  assert.equal(crc32(new TextEncoder().encode('hello')), 0x3610a686);
});

test('buildExport 输出附件名与 Content-Type', () => {
  const data = buildKnowledgeExport(ROWS, USER, NOW);
  const json = buildExport(data, {
    format: 'json',
    includeSummary: true,
    groupBy: 'category',
  });
  assert.equal(json.fileName, 'openfactory-knowledge-2026-10-22.json');
  assert.match(json.contentType, /application\/json/);
  assert.equal(JSON.parse(new TextDecoder().decode(json.body)).schema, 'openfactory.knowledge.v1');

  const zip = buildExport(data, {
    format: 'obsidian',
    includeSummary: true,
    groupBy: 'category',
  });
  assert.equal(zip.fileName, 'openfactory-obsidian-vault-2026-10-22.zip');
  assert.equal(zip.contentType, 'application/zip');
});

test('空数据导出有引导文案且 Obsidian 只有 README', () => {
  const data = buildKnowledgeExport([], USER, NOW);
  assert.equal(data.stats.totalRepos, 0);
  const markdown = buildMarkdownExport(data, {
    format: 'markdown',
    includeSummary: true,
    groupBy: 'category',
  });
  assert.match(markdown, /还没有收藏任何项目/);
  const entries = buildObsidianEntries(data, {
    format: 'obsidian',
    includeSummary: true,
    groupBy: 'category',
  });
  assert.deepEqual(entries.map((entry) => entry.name), ['README.md']);
});

test('文本工具处理转义、文件名、标签与数字格式', () => {
  assert.equal(escapeInline('a\n b [x]'), 'a b \\[x\\]');
  assert.equal(formatStars(999), '999');
  assert.equal(formatStars(1200), '1.2k');
  assert.equal(formatStars(0), '0');
  assert.equal(safeFileName('AI/LLM: 工具?'), 'AI-LLM- 工具');
  assert.equal(obsidianTag('AI/LLM 工具', 'tag'), 'tag/ai/llm-工具');
  assert.equal(exportFileName('markdown', NOW), 'openfactory-knowledge-2026-10-22.md');
});
