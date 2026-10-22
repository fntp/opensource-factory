import assert from 'node:assert/strict';
import test from 'node:test';

import {
  buildImportPlan,
  dedupeEntries,
  detectImportFormat,
  parseCsvRows,
  parseImportContent,
  parseRepoFullName,
  parseRepoUrl,
  previewItems,
} from '../src/import/parse.ts';

test('parseRepoUrl 识别 GitHub / Gitee 仓库并截断子路径', () => {
  assert.deepEqual(parseRepoUrl('https://github.com/ollama/ollama'), {
    id: 'ollama/ollama',
    platform: 'github',
    owner: 'ollama',
    name: 'ollama',
    url: 'https://github.com/ollama/ollama',
  });
  assert.equal(parseRepoUrl('https://github.com/foo/bar.git').id, 'foo/bar');
  assert.equal(parseRepoUrl('https://github.com/foo/bar/tree/main/src').id, 'foo/bar');
  assert.equal(parseRepoUrl('https://gitee.com/foo/bar').platform, 'gitee');
  assert.equal(parseRepoUrl('github.com/foo/bar').id, 'foo/bar');
  assert.equal(parseRepoUrl('https://github.com/topics/ai'), null);
  assert.equal(parseRepoUrl('https://github.com/foo'), null);
  assert.equal(parseRepoUrl('https://example.com/foo/bar'), null);
  assert.equal(parseRepoUrl('javascript:void(0)'), null);
});

test('parseRepoFullName 支持 owner/repo 与完整链接', () => {
  assert.equal(parseRepoFullName('ollama/ollama').id, 'ollama/ollama');
  assert.equal(parseRepoFullName('@ollama/ollama').id, 'ollama/ollama');
  assert.equal(parseRepoFullName('https://github.com/ollama/ollama').id, 'ollama/ollama');
  assert.equal(parseRepoFullName('ollama'), null);
  assert.equal(parseRepoFullName('a/b/c'), null);
});

test('detectImportFormat 按内容识别三种格式', () => {
  assert.equal(detectImportFormat('{"repositories": []}'), 'json');
  assert.equal(detectImportFormat('  [ {"url": "x"} ]'), 'json');
  assert.equal(
    detectImportFormat('<!DOCTYPE NETSCAPE-Bookmark-file-1><DL><p><DT><A HREF="x">x</A>'),
    'html'
  );
  assert.equal(detectImportFormat('fullName,url\nfoo/bar,https://github.com/foo/bar'), 'csv');
});

test('JSON：openfactory.knowledge.v1 可回读，文件内去重并合并标签', () => {
  const content = JSON.stringify({
    schema: 'openfactory.knowledge.v1',
    version: 1,
    repositories: [
      {
        fullName: 'ollama/ollama',
        url: 'https://github.com/ollama/ollama',
        description: '本地模型运行时',
        summary: '在本地运行大模型',
        language: 'Go',
        stars: 100,
        forks: 8,
        category: 'AI/LLM',
        tags: ['本地模型', 'Go'],
      },
      {
        fullName: 'OLLAMA/OLLAMA',
        url: 'https://github.com/ollama/ollama/issues',
        stars: 120,
        tags: ['Go', '推理'],
      },
      {
        fullName: 'foo/bar',
        description: '第二个项目',
        stars: '42',
        tags: '工具, 效率',
      },
      { fullName: 'not-a-repo', description: '无效' },
    ],
  });

  const parsed = parseImportContent(content, { format: 'auto' });
  assert.equal(parsed.format, 'json');
  assert.equal(parsed.totalRows, 4);
  assert.equal(parsed.duplicates, 1);
  assert.equal(parsed.entries.length, 2);
  assert.equal(parsed.issues.length, 1);
  assert.equal(parsed.issues[0].reason, 'invalid_repo');

  const ollama = parsed.entries.find((entry) => entry.id === 'ollama/ollama');
  assert.equal(ollama.description, '本地模型运行时');
  assert.equal(ollama.summary, '在本地运行大模型');
  assert.equal(ollama.stars, 120);
  assert.equal(ollama.category, 'AI/LLM');
  assert.deepEqual(ollama.tags, ['本地模型', 'Go', '推理']);

  const foo = parsed.entries.find((entry) => entry.id === 'foo/bar');
  assert.equal(foo.url, 'https://github.com/foo/bar');
  assert.equal(foo.stars, 42);
  assert.deepEqual(foo.tags, ['工具', '效率']);
});

test('JSON：对象数组与 { items } 均可解析', () => {
  const array = parseImportContent(
    JSON.stringify([{ full_name: 'a/one', html_url: 'https://github.com/a/one' }])
  );
  assert.equal(array.entries[0].id, 'a/one');

  const items = parseImportContent(
    JSON.stringify({ items: [{ repo: 'b/two', link: 'https://github.com/b/two' }] })
  );
  assert.equal(items.entries[0].id, 'b/two');
});

test('CSV：支持引号、逗号、字段内换行与表头别名', () => {
  const content =
    'full_name,html_url,description,language,stars,tags\n' +
    'a/one,https://github.com/a/one,"第一行, 含逗号",TypeScript,10,"前端, 工具"\n' +
    'b/two,https://github.com/b/two,"含\n换行的描述",Go,20,"后端"\n';

  const rows = parseCsvRows(content);
  assert.equal(rows.length, 3);
  assert.equal(rows[1][2], '第一行, 含逗号');
  assert.equal(rows[2][2], '含\n换行的描述');

  const parsed = parseImportContent(content, { format: 'csv' });
  assert.equal(parsed.format, 'csv');
  assert.equal(parsed.entries.length, 2);
  assert.equal(parsed.entries[0].description, '第一行, 含逗号');
  assert.deepEqual(parsed.entries[0].tags, ['前端', '工具']);
  assert.equal(parsed.entries[1].description, '含 换行的描述');
});

test('CSV：制表符分隔与缺少表头', () => {
  const tabbed = 'fullName\turl\nfoo/bar\thttps://github.com/foo/bar\n';
  const parsed = parseImportContent(tabbed, { format: 'csv' });
  assert.equal(parsed.entries[0].id, 'foo/bar');

  const missing = parseImportContent('a,b\n1,2\n', { format: 'csv' });
  assert.equal(missing.entries.length, 0);
  assert.equal(missing.issues[0].reason, 'missing_header');
});

test('HTML：浏览器书签文件夹映射为分类，忽略默认根目录并解码实体', () => {
  const content = `<!DOCTYPE NETSCAPE-Bookmark-file-1>
<DL><p>
  <DT><H3>Bookmarks bar</H3>
  <DL><p>
    <DT><A HREF="https://github.com/foo/bar">Foo Bar</A>
  </DL><p>
  <DT><H3>AI &amp; ML</H3>
  <DL><p>
    <DT><A HREF="https://github.com/ollama/ollama/issues/1">Ollama 本地模型</A>
    <DT><A HREF="https://example.com/post">外部文章</A>
  </DL><p>
</DL><p>`;

  const parsed = parseImportContent(content, { format: 'html', useFolders: true });
  assert.equal(parsed.format, 'html');
  assert.equal(parsed.totalRows, 3);
  assert.equal(parsed.entries.length, 2);
  assert.equal(parsed.entries[0].category, null);
  assert.equal(parsed.entries[1].category, 'AI & ML');
  assert.equal(parsed.entries[1].description, 'Ollama 本地模型');
  assert.equal(parsed.issues[0].reason, 'unsupported_url');

  const withoutFolders = parseImportContent(content, { format: 'html', useFolders: false });
  assert.equal(withoutFolders.entries[1].category, null);
});

test('dedupeEntries 大小写不敏感并合并标签', () => {
  const merged = dedupeEntries([
    {
      id: 'A/One',
      platform: 'github',
      owner: 'A',
      name: 'One',
      url: 'https://github.com/A/One',
      description: null,
      summary: null,
      language: null,
      stars: 1,
      forks: 0,
      category: null,
      tags: ['x'],
    },
    {
      id: 'a/one',
      platform: 'github',
      owner: 'a',
      name: 'one',
      url: 'https://github.com/a/one',
      description: 'desc',
      summary: null,
      language: 'Go',
      stars: 9,
      forks: 2,
      category: 'AI',
      tags: ['X', 'y'],
    },
  ]);
  assert.equal(merged.duplicates, 1);
  assert.equal(merged.entries.length, 1);
  assert.equal(merged.entries[0].stars, 9);
  assert.equal(merged.entries[0].description, 'desc');
  assert.deepEqual(merged.entries[0].tags, ['x', 'y']);
});

test('buildImportPlan 区分新增 / 更新 / 他人冲突', () => {
  const parsed = parseImportContent(
    JSON.stringify({
      repositories: [
        { fullName: 'a/one', url: 'https://github.com/a/one' },
        { fullName: 'b/two', url: 'https://github.com/b/two' },
        { fullName: 'c/three', url: 'https://github.com/c/three' },
        { fullName: 'd/four', url: 'https://github.com/d/four' },
      ],
    })
  );
  const plan = buildImportPlan(
    parsed,
    [
      { id: 'a/one', user_id: 'u1' },
      { id: 'b/two', user_id: 'u2' },
      { id: 'c/three', user_id: null },
    ],
    'u1'
  );
  assert.deepEqual(plan.counts, {
    total: 4,
    new: 1,
    update: 2,
    conflict: 1,
    invalid: 0,
    duplicates: 0,
  });
  assert.equal(plan.items.find((item) => item.id === 'b/two').status, 'conflict');
  assert.equal(plan.items.find((item) => item.id === 'c/three').status, 'update');
});

test('previewItems 限制样例条数并带状态', () => {
  const parsed = parseImportContent(
    JSON.stringify({
      repositories: Array.from({ length: 60 }, (_, index) => ({
        fullName: `owner/repo-${index}`,
        url: `https://github.com/owner/repo-${index}`,
      })),
    })
  );
  const plan = buildImportPlan(parsed, [], 'u1');
  const sample = previewItems(plan, 10);
  assert.equal(sample.length, 10);
  assert.equal(sample[0].status, 'new');
  assert.equal(sample[0].fullName, 'owner/repo-0');
});

test('内容上限与截断标记', () => {
  const many = {
    repositories: Array.from({ length: 2_005 }, (_, index) => ({
      fullName: `owner/repo-${index}`,
      url: `https://github.com/owner/repo-${index}`,
    })),
  };
  const parsed = parseImportContent(JSON.stringify(many));
  assert.equal(parsed.entries.length, 2_000);
  assert.equal(parsed.truncated, true);
  assert.equal(parsed.totalRows, 2_005);
});
