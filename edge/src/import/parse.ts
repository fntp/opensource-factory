/**
 * 外部收藏导入（M9-03 / REQ-202610-0980）：格式识别、解析、归一与导入计划。
 *
 * 纯函数模块，不访问 D1 / 网络：
 * - JSON：openfactory.knowledge.v1、{ items: [...] } 或对象数组；
 * - CSV：逗号 / 制表符 / 分号，支持引号与字段内换行；
 * - HTML：浏览器 Netscape Bookmark 导出，可选文件夹映射为分类。
 */

export type ImportFormat = 'json' | 'csv' | 'html';
export type ImportFormatInput = ImportFormat | 'auto';
export type ImportStatus = 'new' | 'update' | 'conflict';
export type Platform = 'github' | 'gitee';

export interface ImportEntry {
  id: string;
  platform: Platform;
  owner: string;
  name: string;
  url: string;
  description: string | null;
  summary: string | null;
  language: string | null;
  stars: number;
  forks: number;
  category: string | null;
  tags: string[];
}

export interface ImportIssue {
  row: number;
  reason: string;
  value: string;
}

export interface ParsedImport {
  format: ImportFormat;
  entries: ImportEntry[];
  issues: ImportIssue[];
  /** 全部无效条目数（issues 仅保留前 MAX_ISSUES 条） */
  invalidCount: number;
  totalRows: number;
  duplicates: number;
  truncated: boolean;
}

export interface ImportOptions {
  format?: string | null;
  useFolders?: boolean;
}

export interface ExistingRepoRef {
  id: string;
  user_id: string | null;
}

export interface ImportPlanItem extends ImportEntry {
  status: ImportStatus;
}

export interface ImportCounts {
  total: number;
  new: number;
  update: number;
  conflict: number;
  invalid: number;
  duplicates: number;
}

export interface ImportPlan {
  format: ImportFormat;
  items: ImportPlanItem[];
  counts: ImportCounts;
  issues: ImportIssue[];
  truncated: boolean;
}

export const MAX_CONTENT_LENGTH = 2_000_000;
export const MAX_IMPORT_ENTRIES = 2_000;
export const MAX_TAGS_PER_REPO = 20;
export const MAX_ISSUES = 100;
export const PREVIEW_SAMPLE_LIMIT = 50;

const MAX_DESCRIPTION = 500;
const MAX_SUMMARY = 4_000;
const MAX_CATEGORY = 100;
const MAX_TAG = 50;
const MAX_LANGUAGE = 50;
const MAX_STARS = 10_000_000;

const GITHUB_RESERVED = new Set([
  'about',
  'apps',
  'collections',
  'contact',
  'customer-stories',
  'education',
  'enterprise',
  'events',
  'explore',
  'features',
  'github',
  'issues',
  'join',
  'login',
  'marketplace',
  'new',
  'nonprofit',
  'notifications',
  'orgs',
  'pricing',
  'readme',
  'resources',
  'search',
  'security',
  'settings',
  'site',
  'solutions',
  'sponsors',
  'team',
  'topics',
  'trending',
  'users',
]);

const GITEE_RESERVED = new Set([
  'about',
  'enterprise',
  'explore',
  'features',
  'help',
  'login',
  'marketplace',
  'notifications',
  'organizations',
  'pricing',
  'search',
  'settings',
  'signup',
  'trending',
  'users',
]);

const IGNORED_FOLDERS = new Set([
  'bookmarks bar',
  'bookmarks menu',
  'bookmarks toolbar',
  'favorites bar',
  'mobile bookmarks',
  'other bookmarks',
  '书签栏',
  '书签菜单',
  '其他书签',
  '收藏夹',
  '收藏夹栏',
  '移动设备书签',
]);

const TAG_SPLIT = /[,，;；]/;

// ── 基础工具 ───────────────────────────────────────────────────

function cleanText(value: unknown, max: number): string | null {
  if (typeof value !== 'string') return null;
  const text = value.replace(/\s+/g, ' ').trim();
  if (!text) return null;
  return text.length > max ? text.slice(0, max) : text;
}

function toCount(value: unknown, max: number): number {
  const parsed = Number(value);
  if (!Number.isFinite(parsed) || parsed <= 0) return 0;
  return Math.min(Math.trunc(parsed), max);
}

function pickString(record: Record<string, unknown>, keys: string[]): string | null {
  for (const key of keys) {
    const value = record[key];
    if (typeof value === 'string' && value.trim()) return value.trim();
  }
  return null;
}

function pickNumber(record: Record<string, unknown>, keys: string[]): number {
  for (const key of keys) {
    const value = record[key];
    if (value !== null && value !== undefined && value !== '') return toCount(value, MAX_STARS);
  }
  return 0;
}

function decodeHtmlEntities(value: string): string {
  return value
    .replace(/&#x([0-9a-f]+);/gi, (_, hex: string) => {
      const code = Number.parseInt(hex, 16);
      return Number.isFinite(code) && code > 0 && code <= 0x10ffff
        ? String.fromCodePoint(code)
        : '';
    })
    .replace(/&#(\d+);/g, (_, dec: string) => {
      const code = Number.parseInt(dec, 10);
      return Number.isFinite(code) && code > 0 && code <= 0x10ffff
        ? String.fromCodePoint(code)
        : '';
    })
    .replace(/&nbsp;/gi, ' ')
    .replace(/&amp;/gi, '&')
    .replace(/&lt;/gi, '<')
    .replace(/&gt;/gi, '>')
    .replace(/&quot;/gi, '"')
    .replace(/&#39;|&apos;/gi, "'");
}

function stripHtml(value: string): string {
  return decodeHtmlEntities(value.replace(/<[^>]*>/g, ' '));
}

function splitTags(value: unknown): string[] {
  const raw: string[] = [];
  if (Array.isArray(value)) {
    for (const item of value) {
      if (typeof item === 'string') raw.push(item);
    }
  } else if (typeof value === 'string') {
    raw.push(...value.split(TAG_SPLIT));
  }
  const seen = new Set<string>();
  const tags: string[] = [];
  for (const item of raw) {
    const tag = item.trim().replace(/^#+/, '').trim();
    if (!tag) continue;
    const key = tag.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    tags.push(tag.length > MAX_TAG ? tag.slice(0, MAX_TAG) : tag);
    if (tags.length >= MAX_TAGS_PER_REPO) break;
  }
  return tags;
}

// ── 仓库链接归一 ───────────────────────────────────────────────

interface RepoRef {
  id: string;
  platform: Platform;
  owner: string;
  name: string;
  url: string;
}

function repoRefFromParts(
  platform: Platform,
  ownerRaw: string,
  nameRaw: string
): RepoRef | null {
  const owner = ownerRaw.trim();
  const name = nameRaw.trim().replace(/\.git$/i, '');
  if (!owner || !name) return null;
  if (owner.length > 100 || name.length > 100) return null;
  if (!/^[A-Za-z0-9_.-]+$/.test(owner) || !/^[A-Za-z0-9_.-]+$/.test(name)) return null;
  const reserved = platform === 'github' ? GITHUB_RESERVED : GITEE_RESERVED;
  if (reserved.has(owner.toLowerCase())) return null;
  const host = platform === 'gitee' ? 'gitee.com' : 'github.com';
  return {
    id: `${owner}/${name}`,
    platform,
    owner,
    name,
    url: `https://${host}/${owner}/${name}`,
  };
}

/** 从仓库链接解析 owner/repo；非仓库链接返回 null。 */
export function parseRepoUrl(raw: string): RepoRef | null {
  let value = raw.trim();
  if (!value) return null;
  if (value.startsWith('//')) value = `https:${value}`;
  if (!/^https?:\/\//i.test(value)) {
    if (/^(github\.com|gitee\.com|www\.github\.com|www\.gitee\.com)\//i.test(value)) {
      value = `https://${value}`;
    } else {
      return null;
    }
  }

  let url: URL;
  try {
    url = new URL(value);
  } catch {
    return null;
  }
  if (url.protocol !== 'http:' && url.protocol !== 'https:') return null;

  const host = url.hostname.toLowerCase().replace(/^www\./, '');
  const platform: Platform | null =
    host === 'github.com' ? 'github' : host === 'gitee.com' ? 'gitee' : null;
  if (!platform) return null;

  const segments = url.pathname
    .split('/')
    .map((part) => {
      try {
        return decodeURIComponent(part);
      } catch {
        return part;
      }
    })
    .filter(Boolean);
  if (segments.length < 2) return null;

  const owner = segments[0] ?? '';
  const name = segments[1] ?? '';
  const reserved = platform === 'github' ? GITHUB_RESERVED : GITEE_RESERVED;
  if (reserved.has(owner.toLowerCase())) return null;
  return repoRefFromParts(platform, owner, name);
}

/** 从 owner/repo 或链接解析；用于 JSON / CSV 的 fullName 字段。 */
export function parseRepoFullName(raw: string): RepoRef | null {
  const value = raw.trim().replace(/^@/, '');
  if (!value) return null;
  if (/^https?:\/\//i.test(value) || value.startsWith('//')) return parseRepoUrl(value);
  if (/^(www\.)?(github|gitee)\.com\//i.test(value)) return parseRepoUrl(value);

  const parts = value.split('/').filter(Boolean);
  if (parts.length !== 2) return null;
  return repoRefFromParts('github', parts[0] ?? '', parts[1] ?? '');
}

// ── 格式识别 ───────────────────────────────────────────────────

export function normalizeImportFormat(value: string | null | undefined): ImportFormatInput {
  const normalized = (value ?? '').trim().toLowerCase();
  if (normalized === 'json' || normalized === 'csv' || normalized === 'html') return normalized;
  return 'auto';
}

export function detectImportFormat(content: string): ImportFormat {
  const head = content.replace(/^﻿/, '').trimStart().slice(0, 4000).toLowerCase();
  if (head.startsWith('{') || head.startsWith('[')) return 'json';
  if (head.includes('<a ') || head.includes('netscape-bookmark-file') || head.includes('<dl')) {
    return 'html';
  }
  return 'csv';
}

// ── JSON ───────────────────────────────────────────────────────

function entryFromRecord(
  record: Record<string, unknown>,
  row: number,
  folder: string | null,
  issues: ImportIssue[]
): ImportEntry | null {
  const fullName = pickString(record, ['fullName', 'full_name', 'repo', 'repository', 'id']);
  const urlRaw = pickString(record, ['url', 'htmlUrl', 'html_url', 'link']);
  const owner = pickString(record, ['owner', 'ownerName', 'owner_name']);
  const name = pickString(record, ['name', 'repoName', 'repo_name']);

  let ref: RepoRef | null = null;
  if (urlRaw) {
    ref = parseRepoUrl(urlRaw);
  } else if (fullName) {
    ref = parseRepoFullName(fullName);
  } else if (owner && name) {
    ref = parseRepoFullName(`${owner}/${name}`);
  }

  if (!ref) {
    issues.push({
      row,
      reason: 'invalid_repo',
      value: urlRaw ?? fullName ?? [owner, name].filter(Boolean).join('/') ?? '',
    });
    return null;
  }

  const platformRaw = pickString(record, ['platform']);
  const platform: Platform =
    platformRaw?.toLowerCase() === 'gitee' || platformRaw?.toLowerCase() === 'github'
      ? (platformRaw.toLowerCase() as Platform)
      : ref.platform;

  const description = cleanText(record.description ?? record.desc, MAX_DESCRIPTION);
  const summary = cleanText(
    record.summary ?? record.readmeSummary ?? record.readme_summary,
    MAX_SUMMARY
  );

  return {
    ...ref,
    platform,
    description,
    summary,
    language: cleanText(record.language, MAX_LANGUAGE),
    stars: pickNumber(record, ['stars', 'stargazers_count', 'stargazersCount']),
    forks: pickNumber(record, ['forks', 'forks_count', 'forksCount']),
    category: cleanText(
      record.category ?? record.categoryName ?? record.category_name ?? folder,
      MAX_CATEGORY
    ),
    tags: splitTags(record.tags),
  };
}

function parseJson(content: string, issues: ImportIssue[]): {
  entries: ImportEntry[];
  totalRows: number;
} {
  let parsed: unknown;
  try {
    parsed = JSON.parse(content.replace(/^﻿/, ''));
  } catch {
    issues.push({ row: 0, reason: 'invalid_json', value: '' });
    return { entries: [], totalRows: 0 };
  }

  let list: unknown[] = [];
  if (Array.isArray(parsed)) {
    list = parsed;
  } else if (parsed && typeof parsed === 'object') {
    const record = parsed as Record<string, unknown>;
    const candidate = record.repositories ?? record.items ?? record.repos;
    if (Array.isArray(candidate)) {
      list = candidate;
    } else if (record.url || record.fullName || record.full_name) {
      list = [record];
    }
  }

  if (!Array.isArray(list) || list.length === 0) {
    if (list.length === 0) {
      issues.push({ row: 0, reason: 'empty_content', value: '' });
    } else {
      issues.push({ row: 0, reason: 'invalid_json_structure', value: '' });
    }
    return { entries: [], totalRows: 0 };
  }

  const entries: ImportEntry[] = [];
  let totalRows = 0;
  for (let index = 0; index < list.length; index += 1) {
    const item = list[index];
    if (!item || typeof item !== 'object' || Array.isArray(item)) {
      issues.push({ row: index + 1, reason: 'invalid_row', value: '' });
      continue;
    }
    totalRows += 1;
    if (entries.length >= MAX_IMPORT_ENTRIES) continue;
    const entry = entryFromRecord(item as Record<string, unknown>, index + 1, null, issues);
    if (entry) entries.push(entry);
  }
  return { entries, totalRows };
}

// ── CSV ────────────────────────────────────────────────────────

function detectDelimiter(text: string): string {
  const firstLine = text.split(/\r?\n/, 1)[0] ?? '';
  const counts: Array<[string, number]> = [
    [',', (firstLine.match(/,/g) ?? []).length],
    ['\t', (firstLine.match(/\t/g) ?? []).length],
    [';', (firstLine.match(/;/g) ?? []).length],
  ];
  counts.sort((a, b) => b[1] - a[1]);
  return counts[0]?.[1] ? (counts[0]?.[0] ?? ',') : ',';
}

export function parseCsvRows(text: string, delimiter = ','): string[][] {
  const rows: string[][] = [];
  let row: string[] = [];
  let field = '';
  let inQuotes = false;

  for (let i = 0; i < text.length; i += 1) {
    const ch = text[i] ?? '';
    if (inQuotes) {
      if (ch === '"') {
        if (text[i + 1] === '"') {
          field += '"';
          i += 1;
        } else {
          inQuotes = false;
        }
      } else {
        field += ch;
      }
      continue;
    }
    if (ch === '"' && field.length === 0) {
      inQuotes = true;
    } else if (ch === delimiter) {
      row.push(field);
      field = '';
    } else if (ch === '\n') {
      row.push(field);
      rows.push(row);
      row = [];
      field = '';
    } else if (ch !== '\r') {
      field += ch;
    }
  }
  if (field.length > 0 || row.length > 0) {
    row.push(field);
    rows.push(row);
  }
  return rows.filter((item) => item.some((cell) => cell.trim().length > 0));
}

function normalizeHeader(value: string): string {
  return value
    .replace(/^﻿/, '')
    .trim()
    .toLowerCase()
    .replace(/[\s_\-]+/g, '');
}

const HEADER_ALIASES: Record<string, string> = {
  fullname: 'fullName',
  repo: 'fullName',
  repository: 'fullName',
  id: 'fullName',
  url: 'url',
  htmlurl: 'url',
  link: 'url',
  owner: 'owner',
  name: 'name',
  reponame: 'name',
  description: 'description',
  desc: 'description',
  summary: 'summary',
  readmesummary: 'summary',
  language: 'language',
  stars: 'stars',
  stargazerscount: 'stars',
  forks: 'forks',
  forkscount: 'forks',
  category: 'category',
  categoryname: 'category',
  tags: 'tags',
  platform: 'platform',
};

function parseCsv(content: string, issues: ImportIssue[]): {
  entries: ImportEntry[];
  totalRows: number;
} {
  const delimiter = detectDelimiter(content);
  const rows = parseCsvRows(content.replace(/^﻿/, ''), delimiter);
  if (rows.length < 2) {
    issues.push({ row: 0, reason: 'empty_content', value: '' });
    return { entries: [], totalRows: 0 };
  }

  const headerRow = rows[0] ?? [];
  const headers = headerRow.map(normalizeHeader);
  const mapped = headers.map((header) => HEADER_ALIASES[header] ?? '');
  if (!mapped.some(Boolean)) {
    issues.push({ row: 1, reason: 'missing_header', value: headerRow.join(',') });
    return { entries: [], totalRows: 0 };
  }

  const entries: ImportEntry[] = [];
  let totalRows = 0;
  for (let index = 1; index < rows.length; index += 1) {
    const cells = rows[index] ?? [];
    const record: Record<string, unknown> = {};
    for (let column = 0; column < mapped.length; column += 1) {
      const key = mapped[column];
      if (!key) continue;
      record[key] = cells[column] ?? '';
    }
    totalRows += 1;
    if (entries.length >= MAX_IMPORT_ENTRIES) continue;
    const entry = entryFromRecord(record, index + 1, null, issues);
    if (entry) entries.push(entry);
  }
  return { entries, totalRows };
}

// ── Netscape Bookmark HTML ─────────────────────────────────────

function bookmarkHref(attrs: string): string | null {
  const match = /\bhref\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))/i.exec(attrs);
  return match ? (match[1] ?? match[2] ?? match[3] ?? null) : null;
}

function parseHtml(
  content: string,
  useFolders: boolean,
  issues: ImportIssue[]
): { entries: ImportEntry[]; totalRows: number } {
  const tokenRe =
    /<dl\b[^>]*>|<\/dl\s*>|<h3\b[^>]*>([\s\S]*?)<\/h3\s*>|<a\b([^>]*)>([\s\S]*?)<\/a\s*>/gi;
  const folders: Array<string | null> = [];
  let pendingFolder: string | null = null;
  const entries: ImportEntry[] = [];
  let totalRows = 0;
  let row = 0;

  let match: RegExpExecArray | null;
  while ((match = tokenRe.exec(content)) !== null) {
    const token = match[0] ?? '';
    if (/^<dl\b/i.test(token)) {
      folders.push(pendingFolder);
      pendingFolder = null;
      continue;
    }
    if (/^<\/dl/i.test(token)) {
      folders.pop();
      continue;
    }
    if (/^<h3\b/i.test(token)) {
      pendingFolder = cleanText(stripHtml(match[1] ?? ''), MAX_CATEGORY);
      continue;
    }

    row += 1;
    totalRows += 1;
    if (entries.length >= MAX_IMPORT_ENTRIES) continue;

    const href = bookmarkHref(match[2] ?? '');
    const title = cleanText(stripHtml(match[3] ?? ''), MAX_DESCRIPTION);
    if (!href) {
      issues.push({ row, reason: 'missing_url', value: title ?? '' });
      continue;
    }
    const ref = parseRepoUrl(decodeHtmlEntities(href));
    if (!ref) {
      issues.push({ row, reason: 'unsupported_url', value: href });
      continue;
    }

    let folder: string | null = null;
    if (useFolders) {
      for (let depth = folders.length - 1; depth >= 0; depth -= 1) {
        const candidate = folders[depth];
        if (candidate && !IGNORED_FOLDERS.has(candidate.toLowerCase())) {
          folder = candidate;
          break;
        }
      }
    }

    entries.push({
      ...ref,
      description: title && title.toLowerCase() !== ref.name.toLowerCase() ? title : null,
      summary: null,
      language: null,
      stars: 0,
      forks: 0,
      category: folder,
      tags: [],
    });
  }

  if (totalRows === 0) {
    issues.push({ row: 0, reason: 'empty_content', value: '' });
  }
  return { entries, totalRows };
}

// ── 去重与计划 ─────────────────────────────────────────────────

function mergeEntry(target: ImportEntry, source: ImportEntry): void {
  target.description = target.description ?? source.description;
  target.summary = target.summary ?? source.summary;
  target.language = target.language ?? source.language;
  target.category = target.category ?? source.category;
  target.stars = Math.max(target.stars, source.stars);
  target.forks = Math.max(target.forks, source.forks);
  const seen = new Set(target.tags.map((tag) => tag.toLowerCase()));
  for (const tag of source.tags) {
    if (target.tags.length >= MAX_TAGS_PER_REPO) break;
    if (seen.has(tag.toLowerCase())) continue;
    seen.add(tag.toLowerCase());
    target.tags.push(tag);
  }
}

export function dedupeEntries(entries: ImportEntry[]): {
  entries: ImportEntry[];
  duplicates: number;
} {
  const map = new Map<string, ImportEntry>();
  let duplicates = 0;
  for (const entry of entries) {
    const key = entry.id.toLowerCase();
    const existing = map.get(key);
    if (existing) {
      mergeEntry(existing, entry);
      duplicates += 1;
    } else {
      map.set(key, { ...entry, tags: [...entry.tags] });
    }
  }
  return { entries: [...map.values()], duplicates };
}

export function parseImportContent(content: string, options: ImportOptions = {}): ParsedImport {
  const format =
    normalizeImportFormat(options.format) === 'auto'
      ? detectImportFormat(content)
      : (normalizeImportFormat(options.format) as ImportFormat);
  const issues: ImportIssue[] = [];
  const useFolders = options.useFolders !== false;

  let parsed: { entries: ImportEntry[]; totalRows: number };
  if (format === 'json') parsed = parseJson(content, issues);
  else if (format === 'csv') parsed = parseCsv(content, issues);
  else parsed = parseHtml(content, useFolders, issues);

  const deduped = dedupeEntries(parsed.entries);
  return {
    format,
    entries: deduped.entries,
    issues: issues.slice(0, MAX_ISSUES),
    invalidCount: issues.length,
    totalRows: parsed.totalRows,
    duplicates: deduped.duplicates,
    truncated: parsed.totalRows > MAX_IMPORT_ENTRIES,
  };
}

export function buildImportPlan(
  parsed: ParsedImport,
  existing: ExistingRepoRef[],
  userId: string
): ImportPlan {
  const existingMap = new Map<string, ExistingRepoRef>();
  for (const row of existing) {
    existingMap.set(row.id.toLowerCase(), row);
  }

  let created = 0;
  let updated = 0;
  let conflicts = 0;
  const items: ImportPlanItem[] = parsed.entries.map((entry) => {
    const row = existingMap.get(entry.id.toLowerCase());
    let status: ImportStatus = 'new';
    if (row) {
      if (row.user_id && row.user_id !== userId) {
        status = 'conflict';
        conflicts += 1;
      } else {
        status = 'update';
        updated += 1;
      }
    } else {
      created += 1;
    }
    return { ...entry, status };
  });

  return {
    format: parsed.format,
    items,
    counts: {
      total: items.length,
      new: created,
      update: updated,
      conflict: conflicts,
      invalid: parsed.invalidCount,
      duplicates: parsed.duplicates,
    },
    issues: parsed.issues,
    truncated: parsed.truncated,
  };
}

/** 预览样例：只暴露必要字段，最多 50 条。 */
export function previewItems(plan: ImportPlan, limit = PREVIEW_SAMPLE_LIMIT): Array<{
  fullName: string;
  platform: Platform;
  url: string;
  description: string | null;
  language: string | null;
  stars: number;
  category: string | null;
  tags: string[];
  status: ImportStatus;
}> {
  return plan.items.slice(0, Math.max(0, limit)).map((item) => ({
    fullName: item.id,
    platform: item.platform,
    url: item.url,
    description: item.description ?? item.summary,
    language: item.language,
    stars: item.stars,
    category: item.category,
    tags: item.tags,
    status: item.status,
  }));
}
