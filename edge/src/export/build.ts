/**
 * 知识库导出（M6-08）：纯函数构建 Markdown / JSON / Obsidian 三种导出物。
 *
 * 设计约束：
 * - 不访问 D1 / 网络，输入为仓库行与用户信息，便于 node:test 直接覆盖；
 * - Obsidian 使用最小 store ZIP writer（不压缩、无外部依赖），保证 Worker 体积可控；
 * - JSON 结构固定为 `openfactory.knowledge.v1`，作为 M9-04 全量归档的格式基线。
 */

export type ExportFormat = 'markdown' | 'json' | 'obsidian';
export type ExportGroupBy = 'category' | 'none';

export interface ExportUser {
  login: string;
  name?: string | null;
}

/** D1 `my_repositories` 行 + JOIN 得到的分类 / 标签 */
export interface ExportRepoRow {
  id: string;
  platform: string | null;
  name: string | null;
  description: string | null;
  html_url: string | null;
  stars: number | null;
  language: string | null;
  readme_summary: string | null;
  category_id: string | null;
  created_at: string | null;
  owner: string | null;
  forks: number | null;
  updated_at: string | null;
  synced_at: string | null;
  category_name?: string | null;
  tag_names?: string | null;
}

export interface ExportRepo {
  id: string;
  fullName: string;
  platform: string;
  description: string | null;
  summary: string | null;
  language: string | null;
  stars: number;
  forks: number;
  categoryId: string | null;
  category: string | null;
  tags: string[];
  url: string;
  createdAt: string | null;
  updatedAt: string | null;
}

export interface ExportCategory {
  id: string | null;
  name: string;
  parentId: null;
  repoCount: number;
}

export interface ExportTag {
  name: string;
  count: number;
}

export interface KnowledgeExport {
  schema: 'openfactory.knowledge.v1';
  version: 1;
  generatedAt: string;
  generator: { name: string; url: string };
  user: { login: string; name: string | null };
  stats: {
    totalRepos: number;
    withSummary: number;
    categories: number;
    tags: number;
    totalStars: number;
  };
  categories: ExportCategory[];
  tags: ExportTag[];
  repositories: ExportRepo[];
}

export interface ExportOptions {
  format: ExportFormat;
  includeSummary: boolean;
  groupBy: ExportGroupBy;
}

export interface ZipEntry {
  name: string;
  content: string;
}

const UNCATEGORIZED = '未分类';
const GENERATOR_URL = 'https://github.com/fntp/opensource-factory';

// ── 参数归一化 ─────────────────────────────────────────────────

export function normalizeExportFormat(value: string | null | undefined): ExportFormat {
  const normalized = (value ?? '').trim().toLowerCase();
  if (normalized === 'json' || normalized === 'obsidian') return normalized;
  return 'markdown';
}

export function normalizeExportOptions(input: {
  format?: string | null;
  includeSummary?: string | null;
  groupBy?: string | null;
}): ExportOptions {
  return {
    format: normalizeExportFormat(input.format),
    includeSummary: input.includeSummary !== '0' && input.includeSummary !== 'false',
    groupBy: input.groupBy === 'none' ? 'none' : 'category',
  };
}

// ── 数据构建 ───────────────────────────────────────────────────

function splitTags(raw: string | null | undefined): string[] {
  if (!raw) return [];
  const seen = new Set<string>();
  const tags: string[] = [];
  for (const part of raw.split(',')) {
    const tag = part.trim();
    if (!tag || seen.has(tag)) continue;
    seen.add(tag);
    tags.push(tag);
  }
  return tags;
}

function fullNameOf(row: ExportRepoRow): string {
  const owner = (row.owner ?? row.id.split('/')[0] ?? '').trim();
  const name = (row.name ?? row.id.split('/')[1] ?? '').trim();
  if (owner && name) return `${owner}/${name}`;
  return row.id;
}

function sortRepos(a: ExportRepo, b: ExportRepo): number {
  if (b.stars !== a.stars) return b.stars - a.stars;
  return a.fullName.localeCompare(b.fullName, 'zh-Hans-CN');
}

/** 把 D1 行归一为导出数据；同一仓库同一标签只计一次。 */
export function buildKnowledgeExport(
  rows: ExportRepoRow[],
  user: ExportUser,
  generatedAt: string
): KnowledgeExport {
  const repositories: ExportRepo[] = rows
    .map((row) => ({
      id: row.id,
      fullName: fullNameOf(row),
      platform: row.platform ?? 'github',
      description: row.description ?? null,
      summary: row.readme_summary ?? null,
      language: row.language ?? null,
      stars: Number(row.stars ?? 0),
      forks: Number(row.forks ?? 0),
      categoryId: row.category_id ?? null,
      category: row.category_name ?? null,
      tags: splitTags(row.tag_names),
      url: row.html_url ?? `https://github.com/${fullNameOf(row)}`,
      createdAt: row.created_at ?? null,
      updatedAt: row.updated_at ?? row.synced_at ?? null,
    }))
    .sort(sortRepos);

  const categoryCounts = new Map<string, ExportCategory>();
  const tagCounts = new Map<string, number>();
  let withSummary = 0;
  let totalStars = 0;

  for (const repo of repositories) {
    totalStars += repo.stars;
    if (repo.summary?.trim()) withSummary += 1;

    const categoryName = repo.category?.trim() || UNCATEGORIZED;
    const existing = categoryCounts.get(categoryName);
    if (existing) {
      existing.repoCount += 1;
    } else {
      categoryCounts.set(categoryName, {
        id: repo.categoryId,
        name: categoryName,
        parentId: null,
        repoCount: 1,
      });
    }

    for (const tag of repo.tags) {
      tagCounts.set(tag, (tagCounts.get(tag) ?? 0) + 1);
    }
  }

  const categories = [...categoryCounts.values()].sort((a, b) => {
    if (a.name === UNCATEGORIZED) return 1;
    if (b.name === UNCATEGORIZED) return -1;
    return b.repoCount - a.repoCount || a.name.localeCompare(b.name, 'zh-Hans-CN');
  });
  const tags = [...tagCounts.entries()]
    .map(([name, count]) => ({ name, count }))
    .sort((a, b) => b.count - a.count || a.name.localeCompare(b.name, 'zh-Hans-CN'));

  return {
    schema: 'openfactory.knowledge.v1',
    version: 1,
    generatedAt,
    generator: { name: 'OpenFactory', url: GENERATOR_URL },
    user: { login: user.login, name: user.name ?? null },
    stats: {
      totalRepos: repositories.length,
      withSummary,
      categories: categories.length,
      tags: tags.length,
      totalStars,
    },
    categories,
    tags,
    repositories,
  };
}

// ── 文本工具 ───────────────────────────────────────────────────

/** 行内文本：压缩换行，转义会破坏 Markdown 结构的字符。 */
export function escapeInline(value: string | null | undefined): string {
  if (!value) return '';
  return value
    .replace(/\s+/g, ' ')
    .replace(/([\\[\]()<>])/g, '\\$1')
    .trim();
}

/** 标题 / 链接文本：额外转义强调与代码标记。 */
function escapeTitle(value: string): string {
  return escapeInline(value).replace(/([*_`#|])/g, '\\$1');
}

export function formatStars(value: number): string {
  if (!Number.isFinite(value) || value <= 0) return '0';
  if (value >= 1000) {
    const compact = (value / 1000).toFixed(1).replace(/\.0$/, '');
    return `${compact}k`;
  }
  return String(Math.round(value));
}

/** 文件系统安全名：保留中文与常见字符，替换路径分隔符 / 控制字符。 */
export function safeFileName(value: string, fallback = '未命名'): string {
  const cleaned = value
    .replace(/[\\/:*?"<>|\u0000-\u001f]/g, '-')
    .replace(/\s+/g, ' ')
    .replace(/^[.\s-]+|[.\s-]+$/g, '')
    .slice(0, 80)
    .trim();
  return cleaned || fallback;
}

/** Obsidian 标签：小写、空格转 -，去掉会破坏 YAML / 标签语法的字符。 */
export function obsidianTag(value: string, prefix: string): string {
  const cleaned = value
    .toLowerCase()
    .replace(/\s+/g, '-')
    .replace(/[#|[\],:{}()"'`]/g, '')
    .replace(/-+/g, '-')
    .replace(/^[-/]+|[-/]+$/g, '');
  return cleaned ? `${prefix}/${cleaned}` : '';
}

function anchorFor(name: string): string {
  return name
    .toLowerCase()
    .replace(/[^\p{L}\p{N}\s-]/gu, '')
    .trim()
    .replace(/\s+/g, '-');
}

function repoNoteName(repo: ExportRepo): string {
  return safeFileName(repo.fullName.replace('/', '--'), 'repo');
}

function categoryFolder(name: string): string {
  return safeFileName(name, '未分类');
}

function yamlString(value: string): string {
  return JSON.stringify(value);
}

function repoUpdatedDate(repo: ExportRepo): string {
  return (repo.updatedAt ?? repo.createdAt ?? '').slice(0, 10);
}

// ── Markdown ───────────────────────────────────────────────────

export function buildMarkdownExport(data: KnowledgeExport, options: ExportOptions): string {
  const lines: string[] = [];
  lines.push('---');
  lines.push(`title: ${yamlString('我的开源知识库')}`);
  lines.push(`generator: ${yamlString('OpenFactory')}`);
  lines.push(`generatedAt: ${yamlString(data.generatedAt)}`);
  lines.push(`repoCount: ${data.stats.totalRepos}`);
  lines.push('---');
  lines.push('');
  lines.push('# 我的开源知识库');
  lines.push('');
  lines.push(
    `> 由 OpenFactory 于 ${data.generatedAt} 导出 · 共 ${data.stats.totalRepos} 个项目 · ` +
      `${data.stats.categories} 个分类 · ${data.stats.tags} 个标签 · ⭐ ${formatStars(data.stats.totalStars)}`
  );
  lines.push('');

  const groups = groupRepos(data, options.groupBy);
  if (groups.length === 0) {
    lines.push('_当前账号还没有收藏任何项目，先去热榜或仓库页收藏几个吧。_');
    lines.push('');
    return lines.join('\n');
  }

  lines.push('## 目录');
  lines.push('');
  for (const group of groups) {
    lines.push(`- [${escapeTitle(group.name)}](#${anchorFor(group.name)})（${group.repos.length}）`);
  }
  lines.push('');

  for (const group of groups) {
    lines.push(`## ${escapeTitle(group.name)}`);
    lines.push('');
    for (const repo of group.repos) {
      lines.push(`### [${escapeTitle(repo.fullName)}](${repo.url})`);
      lines.push('');
      const meta: string[] = [];
      if (repo.language) meta.push(repo.language);
      meta.push(`⭐ ${formatStars(repo.stars)}`);
      if (repo.tags.length > 0) {
        meta.push(`标签：${repo.tags.map((tag) => `\`${escapeInline(tag)}\``).join(' ')}`);
      }
      lines.push(`> ${meta.join(' · ')}`);
      lines.push('');
      if (repo.description) {
        lines.push(escapeInline(repo.description));
        lines.push('');
      }
      if (options.includeSummary && repo.summary) {
        lines.push(`**摘要**：${escapeInline(repo.summary)}`);
        lines.push('');
      }
    }
  }

  return lines.join('\n');
}

function groupRepos(
  data: KnowledgeExport,
  groupBy: ExportGroupBy
): Array<{ name: string; repos: ExportRepo[] }> {
  if (groupBy === 'none') {
    return data.repositories.length > 0
      ? [{ name: '全部项目', repos: data.repositories }]
      : [];
  }
  const groups = new Map<string, ExportRepo[]>();
  for (const repo of data.repositories) {
    const name = repo.category?.trim() || UNCATEGORIZED;
    const list = groups.get(name);
    if (list) list.push(repo);
    else groups.set(name, [repo]);
  }
  return [...groups.entries()]
    .map(([name, repos]) => ({ name, repos }))
    .sort((a, b) => {
      if (a.name === UNCATEGORIZED) return 1;
      if (b.name === UNCATEGORIZED) return -1;
      return b.repos.length - a.repos.length || a.name.localeCompare(b.name, 'zh-Hans-CN');
    });
}

// ── Obsidian ───────────────────────────────────────────────────

export function buildObsidianEntries(
  data: KnowledgeExport,
  options: ExportOptions
): ZipEntry[] {
  const entries: ZipEntry[] = [];
  const groups = groupRepos(data, options.groupBy);

  const readme: string[] = [];
  readme.push('---');
  readme.push(`title: ${yamlString('OpenFactory 知识库')}`);
  readme.push('tags:');
  readme.push('  - "openfactory"');
  readme.push(`generated: ${yamlString(data.generatedAt)}`);
  readme.push('---');
  readme.push('');
  readme.push('# OpenFactory 知识库');
  readme.push('');
  readme.push(
    `> 共 ${data.stats.totalRepos} 个项目 · ${data.stats.categories} 个分类 · ` +
      `${data.stats.tags} 个标签 · ⭐ ${formatStars(data.stats.totalStars)}`
  );
  readme.push('');
  readme.push('## 分类');
  readme.push('');
  for (const group of groups) {
    const categoryPath = `20-分类/${categoryFolder(group.name)}`;
    readme.push(`- [[${categoryPath}|${group.name}]]（${group.repos.length}）`);
  }
  readme.push('');
  readme.push('## 最近更新');
  readme.push('');
  const recent = [...data.repositories]
    .filter((repo) => repoUpdatedDate(repo))
    .sort((a, b) => repoUpdatedDate(b).localeCompare(repoUpdatedDate(a)))
    .slice(0, 20);
  for (const repo of recent) {
    readme.push(
      `- [[${repoNotePath(repo, options.groupBy)}|${repo.fullName}]] · ${repoUpdatedDate(repo)}`
    );
  }
  readme.push('');
  entries.push({ name: 'README.md', content: readme.join('\n') });

  for (const group of groups) {
    const categoryName = categoryFolder(group.name);
    const note: string[] = [];
    note.push('---');
    note.push(`title: ${yamlString(group.name)}`);
    note.push('tags:');
    note.push('  - "openfactory"');
    const catTag = obsidianTag(group.name, 'cat');
    if (catTag) note.push(`  - ${yamlString(catTag)}`);
    note.push('---');
    note.push('');
    note.push(`# ${group.name}`);
    note.push('');
    for (const repo of group.repos) {
      const notePath = repoNotePath(repo, options.groupBy);
      note.push(`- [[${notePath}|${repo.fullName}]]${repo.description ? ` — ${escapeInline(repo.description)}` : ''}`);
    }
    note.push('');
    entries.push({ name: `20-分类/${categoryName}.md`, content: note.join('\n') });
  }

  for (const repo of data.repositories) {
    entries.push({
      name: repoNotePath(repo, options.groupBy),
      content: buildObsidianRepoNote(repo, options),
    });
  }

  return entries;
}

function repoNotePath(repo: ExportRepo, groupBy: ExportGroupBy): string {
  const note = `${repoNoteName(repo)}.md`;
  if (groupBy === 'none') return `10-项目/${note}`;
  return `10-项目/${categoryFolder(repo.category?.trim() || UNCATEGORIZED)}/${note}`;
}

function buildObsidianRepoNote(repo: ExportRepo, options: ExportOptions): string {
  const lines: string[] = [];
  lines.push('---');
  lines.push(`title: ${yamlString(repo.fullName)}`);
  lines.push('aliases:');
  lines.push(`  - ${yamlString(repo.fullName.split('/').pop() ?? repo.fullName)}`);
  const tags = ['openfactory'];
  if (repo.language) {
    const langTag = obsidianTag(repo.language, 'lang');
    if (langTag) tags.push(langTag);
  }
  for (const tag of repo.tags) {
    const normalized = obsidianTag(tag, 'tag');
    if (normalized) tags.push(normalized);
  }
  if (repo.category) {
    const catTag = obsidianTag(repo.category, 'cat');
    if (catTag) tags.push(catTag);
  }
  lines.push('tags:');
  for (const tag of [...new Set(tags)]) lines.push(`  - ${yamlString(tag)}`);
  lines.push(`category: ${yamlString(repo.category ?? UNCATEGORIZED)}`);
  lines.push(`language: ${yamlString(repo.language ?? '')}`);
  lines.push(`stars: ${repo.stars}`);
  lines.push(`forks: ${repo.forks}`);
  lines.push(`platform: ${yamlString(repo.platform)}`);
  lines.push(`repo: ${yamlString(repo.fullName)}`);
  lines.push(`url: ${yamlString(repo.url)}`);
  if (repo.createdAt) lines.push(`created: ${yamlString(repo.createdAt.slice(0, 10))}`);
  if (repoUpdatedDate(repo)) lines.push(`updated: ${yamlString(repoUpdatedDate(repo))}`);
  lines.push('---');
  lines.push('');
  lines.push(`# ${repo.fullName}`);
  lines.push('');
  if (repo.description) {
    lines.push(repo.description.trim());
    lines.push('');
  }
  if (options.includeSummary && repo.summary) {
    lines.push('## 摘要');
    lines.push('');
    lines.push(repo.summary.trim());
    lines.push('');
  }
  if (repo.tags.length > 0) {
    lines.push('## 标签');
    lines.push('');
    lines.push(repo.tags.map((tag) => `\`${tag}\``).join(' '));
    lines.push('');
  }
  lines.push('## 链接');
  lines.push('');
  lines.push(`- [${repo.platform === 'gitee' ? 'Gitee' : 'GitHub'}](${repo.url})`);
  lines.push('');
  return lines.join('\n');
}

// ── 文件名 ─────────────────────────────────────────────────────

export function exportFileName(format: ExportFormat, generatedAt: string): string {
  const date = generatedAt.slice(0, 10) || 'export';
  if (format === 'json') return `openfactory-knowledge-${date}.json`;
  if (format === 'obsidian') return `openfactory-obsidian-vault-${date}.zip`;
  return `openfactory-knowledge-${date}.md`;
}

// ── ZIP（store，无压缩） ───────────────────────────────────────

const CRC_TABLE = (() => {
  const table = new Uint32Array(256);
  for (let i = 0; i < 256; i += 1) {
    let value = i;
    for (let bit = 0; bit < 8; bit += 1) {
      value = (value & 1) === 1 ? 0xedb88320 ^ (value >>> 1) : value >>> 1;
    }
    table[i] = value >>> 0;
  }
  return table;
})();

export function crc32(bytes: Uint8Array): number {
  let crc = 0xffffffff;
  for (const byte of bytes) {
    crc = CRC_TABLE[(crc ^ byte) & 0xff]! ^ (crc >>> 8);
  }
  return (crc ^ 0xffffffff) >>> 0;
}

function dosDateTime(date: Date): { time: number; date: number } {
  const time =
    ((date.getHours() & 0x1f) << 11) |
    ((date.getMinutes() & 0x3f) << 5) |
    ((date.getSeconds() & 0x3f) >> 1);
  const day =
    (((Math.max(date.getFullYear(), 1980) - 1980) & 0x7f) << 9) |
    (((date.getMonth() + 1) & 0x0f) << 5) |
    (date.getDate() & 0x1f);
  return { time, date: day };
}

function u16(value: number): Uint8Array {
  return new Uint8Array([value & 0xff, (value >>> 8) & 0xff]);
}

function u32(value: number): Uint8Array {
  return new Uint8Array([
    value & 0xff,
    (value >>> 8) & 0xff,
    (value >>> 16) & 0xff,
    (value >>> 24) & 0xff,
  ]);
}

function concat(chunks: Uint8Array[]): Uint8Array {
  const total = chunks.reduce((sum, chunk) => sum + chunk.length, 0);
  const result = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) {
    result.set(chunk, offset);
    offset += chunk.length;
  }
  return result;
}

/** 生成最小 ZIP（store 模式，UTF-8 文件名），供 Obsidian vault 下载。 */
export function buildStoreZip(entries: ZipEntry[], mtime: Date = new Date()): Uint8Array {
  const encoder = new TextEncoder();
  const { time, date } = dosDateTime(mtime);
  const localChunks: Uint8Array[] = [];
  const centralChunks: Uint8Array[] = [];
  let offset = 0;

  for (const entry of entries) {
    const nameBytes = encoder.encode(entry.name);
    const dataBytes = encoder.encode(entry.content);
    const crc = crc32(dataBytes);

    const local = concat([
      u32(0x04034b50),
      u16(20),
      u16(0x0800),
      u16(0),
      u16(time),
      u16(date),
      u32(crc),
      u32(dataBytes.length),
      u32(dataBytes.length),
      u16(nameBytes.length),
      u16(0),
      nameBytes,
      dataBytes,
    ]);
    localChunks.push(local);

    centralChunks.push(
      concat([
        u32(0x02014b50),
        u16(20),
        u16(20),
        u16(0x0800),
        u16(0),
        u16(time),
        u16(date),
        u32(crc),
        u32(dataBytes.length),
        u32(dataBytes.length),
        u16(nameBytes.length),
        u16(0),
        u16(0),
        u16(0),
        u16(0),
        u32(0),
        u32(offset),
        nameBytes,
      ])
    );

    offset += local.length;
  }

  const central = concat(centralChunks);
  const end = concat([
    u32(0x06054b50),
    u16(0),
    u16(0),
    u16(entries.length),
    u16(entries.length),
    u32(central.length),
    u32(offset),
    u16(0),
  ]);

  return concat([...localChunks, central, end]);
}

// ── 统一入口 ───────────────────────────────────────────────────

export interface BuiltExport {
  contentType: string;
  fileName: string;
  body: Uint8Array;
}

export function buildExport(
  data: KnowledgeExport,
  options: ExportOptions,
  now: Date = new Date()
): BuiltExport {
  const fileName = exportFileName(options.format, data.generatedAt);
  if (options.format === 'json') {
    return {
      contentType: 'application/json; charset=utf-8',
      fileName,
      body: new TextEncoder().encode(JSON.stringify(data, null, 2)),
    };
  }
  if (options.format === 'obsidian') {
    return {
      contentType: 'application/zip',
      fileName,
      body: buildStoreZip(buildObsidianEntries(data, options), now),
    };
  }
  return {
    contentType: 'text/markdown; charset=utf-8',
    fileName,
    body: new TextEncoder().encode(buildMarkdownExport(data, options)),
  };
}
