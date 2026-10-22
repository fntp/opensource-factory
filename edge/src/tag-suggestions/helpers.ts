/**
 * 自动打标建议纯函数（REQ-202610-0960 / M7-01）。
 *
 * edge 侧负责：
 * - 标签归一化与稳定 id（同一用户 + 仓库 + 标签只保留一条建议）；
 * - VPS 返回结果与本地兜底结果的合并 / 去重 / 截断；
 * - D1 行 → 前端 DTO；
 * - VPS 不可达时的本地规则兜底（language 字段 + 摘要关键词）。
 */
import type { TagSuggestionRow } from '../types';

export type TagSuggestionCategory = 'language' | 'framework' | 'domain' | 'quality';
export type TagSuggestionStatus = 'pending' | 'accepted' | 'dismissed';

export interface GeneratedTag {
  name: string;
  category: TagSuggestionCategory;
  score: number;
  reason: string;
  evidence: string;
}

export interface GeneratedRepoItem {
  repoId: string;
  tags: GeneratedTag[];
}

export interface GenerateResult {
  generatedAt: string;
  scanned: number;
  suggested: number;
  skipped: number;
  items: GeneratedRepoItem[];
  source?: 'vps' | 'local';
}

export interface LocalRepoInput {
  id: string;
  language?: string | null;
  summary?: string | null;
  description?: string | null;
}

export interface TagSuggestionDto {
  id: string;
  repoId: string;
  repoName: string;
  repoUrl: string;
  summary: string;
  tagName: string;
  category: TagSuggestionCategory;
  score: number;
  reason: string;
  evidence: string;
  status: TagSuggestionStatus;
  createdAt: string;
  updatedAt: string;
}

interface LocalRule {
  name: string;
  category: TagSuggestionCategory;
  weight: number;
  aliases: string[];
  keywords: string[];
}

const CATEGORY_ORDER: Record<string, number> = {
  language: 0,
  framework: 1,
  domain: 2,
  quality: 3,
};

const MAX_PER_REPO = 10;

const LOCAL_RULES: LocalRule[] = [
  // 语言
  { name: 'TypeScript', category: 'language', weight: 0.35, aliases: ['typescript', 'ts'], keywords: [] },
  { name: 'JavaScript', category: 'language', weight: 0.35, aliases: ['javascript', 'js'], keywords: [] },
  { name: 'Python', category: 'language', weight: 0.35, aliases: ['python'], keywords: [] },
  { name: 'Go', category: 'language', weight: 0.35, aliases: ['golang'], keywords: ['go 语言'] },
  { name: 'Rust', category: 'language', weight: 0.35, aliases: ['rust'], keywords: [] },
  { name: 'Java', category: 'language', weight: 0.35, aliases: ['java'], keywords: [] },
  { name: 'Kotlin', category: 'language', weight: 0.35, aliases: ['kotlin'], keywords: [] },
  { name: 'Swift', category: 'language', weight: 0.35, aliases: ['swift'], keywords: [] },
  { name: 'C++', category: 'language', weight: 0.35, aliases: ['c++', 'cpp'], keywords: [] },
  { name: 'C#', category: 'language', weight: 0.35, aliases: ['c#', 'csharp'], keywords: [] },
  { name: 'PHP', category: 'language', weight: 0.35, aliases: ['php'], keywords: [] },
  { name: 'Ruby', category: 'language', weight: 0.35, aliases: ['ruby'], keywords: [] },
  // 框架
  { name: 'React', category: 'framework', weight: 0.27, aliases: ['react', 'react.js'], keywords: [] },
  { name: 'Vue', category: 'framework', weight: 0.27, aliases: ['vue', 'vue.js', 'vue3'], keywords: [] },
  { name: 'Next.js', category: 'framework', weight: 0.27, aliases: ['next.js', 'nextjs'], keywords: [] },
  { name: 'Svelte', category: 'framework', weight: 0.27, aliases: ['svelte', 'sveltekit'], keywords: [] },
  { name: 'Angular', category: 'framework', weight: 0.27, aliases: ['angular'], keywords: [] },
  { name: 'Node.js', category: 'framework', weight: 0.27, aliases: ['node.js', 'nodejs'], keywords: [] },
  { name: 'FastAPI', category: 'framework', weight: 0.27, aliases: ['fastapi'], keywords: [] },
  { name: 'Django', category: 'framework', weight: 0.27, aliases: ['django'], keywords: [] },
  { name: 'Flask', category: 'framework', weight: 0.27, aliases: ['flask'], keywords: [] },
  { name: 'Spring Boot', category: 'framework', weight: 0.27, aliases: ['spring boot', 'springboot'], keywords: [] },
  { name: 'Express', category: 'framework', weight: 0.27, aliases: ['express', 'express.js'], keywords: [] },
  { name: 'Tailwind CSS', category: 'framework', weight: 0.27, aliases: ['tailwind', 'tailwindcss'], keywords: [] },
  { name: 'Electron', category: 'framework', weight: 0.27, aliases: ['electron'], keywords: [] },
  { name: 'Tauri', category: 'framework', weight: 0.27, aliases: ['tauri'], keywords: [] },
  { name: 'Flutter', category: 'framework', weight: 0.27, aliases: ['flutter'], keywords: [] },
  // 业务域 / 工程属性
  { name: 'AI/LLM', category: 'domain', weight: 0.23, aliases: ['ai', 'llm', 'gpt', 'chatgpt'], keywords: ['人工智能', '大模型', '大语言模型'] },
  { name: '机器学习', category: 'domain', weight: 0.23, aliases: ['machine learning'], keywords: ['机器学习', '深度学习'] },
  { name: '数据分析', category: 'domain', weight: 0.23, aliases: ['analytics'], keywords: ['数据分析', '报表'] },
  { name: '数据可视化', category: 'domain', weight: 0.23, aliases: ['visualization'], keywords: ['数据可视化', '图表', '可视化'] },
  { name: '前端开发', category: 'domain', weight: 0.23, aliases: ['frontend', 'front-end'], keywords: ['前端'] },
  { name: '后端服务', category: 'domain', weight: 0.23, aliases: ['backend', 'back-end'], keywords: ['后端', '服务端'] },
  { name: '数据库', category: 'domain', weight: 0.23, aliases: ['database', 'sql'], keywords: ['数据库'] },
  { name: 'DevOps', category: 'domain', weight: 0.23, aliases: ['devops', 'ci/cd'], keywords: ['持续集成', '运维'] },
  { name: '云原生', category: 'domain', weight: 0.23, aliases: ['kubernetes', 'k8s', 'docker'], keywords: ['云原生', '容器'] },
  { name: '安全', category: 'domain', weight: 0.23, aliases: ['security', 'oauth'], keywords: ['安全', '鉴权', '认证'] },
  { name: '测试', category: 'domain', weight: 0.23, aliases: ['testing'], keywords: ['测试'] },
  { name: '爬虫', category: 'domain', weight: 0.23, aliases: ['crawler', 'scraper', 'spider'], keywords: ['爬虫', '抓取', '采集'] },
  { name: '自动化', category: 'domain', weight: 0.23, aliases: ['automation', 'workflow'], keywords: ['自动化', '工作流'] },
  { name: '命令行', category: 'domain', weight: 0.23, aliases: ['cli'], keywords: ['命令行', '终端工具'] },
  { name: '浏览器扩展', category: 'domain', weight: 0.23, aliases: ['browser extension', 'chrome extension'], keywords: ['浏览器扩展'] },
  { name: '开箱即用', category: 'quality', weight: 0.18, aliases: ['out of the box'], keywords: ['开箱即用', '零配置'] },
  { name: '轻量', category: 'quality', weight: 0.18, aliases: ['lightweight'], keywords: ['轻量', '小巧'] },
  { name: '高性能', category: 'quality', weight: 0.18, aliases: ['high performance', 'high-performance'], keywords: ['高性能', '极速'] },
  { name: '可扩展', category: 'quality', weight: 0.18, aliases: ['extensible', 'scalable', 'plugin'], keywords: ['可扩展', '插件化'] },
  { name: '自托管', category: 'quality', weight: 0.18, aliases: ['self-hosted', 'selfhosted'], keywords: ['自托管', '私有化部署', '本地部署'] },
];

/** 标签归一化：去 #、压缩空白、小写。 */
export function normalizeTagKey(name: string): string {
  return (name ?? '')
    .trim()
    .replace(/^#+/, '')
    .trim()
    .replace(/\s+/g, ' ')
    .toLowerCase();
}

/** 稳定建议 id：用户 + 仓库 + 归一化标签（FNV-1a 双 32 位）。 */
export function hashSuggestionId(userId: string, repoId: string, tagName: string): string {
  const input = `${userId}\u0000${repoId}\u0000${normalizeTagKey(tagName)}`;
  let h1 = 0x811c9dc5;
  let h2 = 0x01000193;
  for (let index = 0; index < input.length; index += 1) {
    const code = input.charCodeAt(index);
    h1 ^= code;
    h1 = Math.imul(h1, 16777619) >>> 0;
    h2 = Math.imul(h2 ^ code, 2654435761) >>> 0;
  }
  return `ts_${h1.toString(16).padStart(8, '0')}${h2.toString(16).padStart(8, '0')}`;
}

/** 列表 limit：默认 50，范围 1~200。 */
export function clampLimit(value: unknown, fallback = 50): number {
  const parsed = typeof value === 'number' ? value : Number.parseInt(String(value ?? ''), 10);
  if (!Number.isFinite(parsed) || parsed <= 0) return fallback;
  return Math.min(200, Math.max(1, Math.trunc(parsed)));
}

/** offset：默认 0，范围 0~10000。 */
export function clampOffset(value: unknown): number {
  const parsed = typeof value === 'number' ? value : Number.parseInt(String(value ?? ''), 10);
  if (!Number.isFinite(parsed) || parsed <= 0) return 0;
  return Math.min(10000, Math.trunc(parsed));
}

/** 每仓库建议条数：默认 6，范围 1~10。 */
export function clampPerRepo(value: unknown): number {
  const parsed = typeof value === 'number' ? value : Number.parseInt(String(value ?? ''), 10);
  if (!Number.isFinite(parsed) || parsed <= 0) return 6;
  return Math.min(MAX_PER_REPO, Math.max(1, Math.trunc(parsed)));
}

/** 建议状态过滤：未知值回落到 pending。 */
export function normalizeSuggestionStatus(value: unknown): TagSuggestionStatus | 'all' {
  const normalized = String(value ?? '').trim().toLowerCase();
  if (normalized === 'all' || normalized === 'accepted' || normalized === 'dismissed') {
    return normalized;
  }
  return 'pending';
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function aliasHit(text: string, alias: string): boolean {
  if (!alias.trim()) return false;
  const pattern = new RegExp(`(?<![a-z0-9])${escapeRegExp(alias.toLowerCase())}(?![a-z0-9])`);
  return pattern.test(text);
}

function firstHit(text: string, rule: LocalRule): string | null {
  for (const alias of rule.aliases) {
    if (aliasHit(text, alias)) return alias;
  }
  for (const keyword of rule.keywords) {
    if (text.includes(keyword.toLowerCase())) return keyword;
  }
  return null;
}

function evidenceOf(text: string, needle: string, width = 32): string {
  const index = text.toLowerCase().indexOf(needle.toLowerCase());
  if (index < 0) return text.slice(0, width * 2).trim();
  const start = Math.max(0, index - width);
  const end = Math.min(text.length, index + needle.length + width);
  const snippet = text.slice(start, end).trim();
  return `${start > 0 ? '…' : ''}${snippet}${end < text.length ? '…' : ''}`.slice(0, 160);
}

/** 本地规则兜底：从摘要 + language 字段生成建议。 */
export function localSuggestTags(
  summary: string,
  language = '',
  limit = 6
): GeneratedTag[] {
  const text = (summary ?? '').trim();
  if (!text) return [];
  const normalizedText = text.toLowerCase().replace(/\s+/g, ' ');
  const normalizedLanguage = (language ?? '').trim().toLowerCase();
  const maxItems = clampPerRepo(limit);

  const scored: GeneratedTag[] = [];
  for (const rule of LOCAL_RULES) {
    const hits: string[] = [];
    let reason = '';
    let evidence = '';

    if (rule.category === 'language' && normalizedLanguage) {
      const keys = [rule.name.toLowerCase(), ...rule.aliases.map((alias) => alias.toLowerCase())];
      if (keys.includes(normalizedLanguage)) {
        hits.push(normalizedLanguage);
        reason = `语言字段为 ${rule.name}`;
        evidence = `language 字段：${language}`;
      }
    }

    const hit = firstHit(normalizedText, rule);
    if (hit) {
      hits.push(hit);
      if (!reason) reason = `摘要命中「${hit}」`;
      if (!evidence) evidence = evidenceOf(text, hit);
    }
    if (hits.length === 0) continue;

    const score = Math.round(Math.min(0.98, 0.45 + rule.weight + Math.min(hits.length - 1, 3) * 0.03) * 100) / 100;
    if (score < 0.55) continue;
    scored.push({ name: rule.name, category: rule.category, score, reason, evidence });
  }

  scored.sort(
    (a, b) =>
      b.score - a.score ||
      (CATEGORY_ORDER[a.category] ?? 9) - (CATEGORY_ORDER[b.category] ?? 9) ||
      a.name.localeCompare(b.name)
  );
  return scored.slice(0, maxItems);
}

/** 同一仓库多条结果合并：按归一化标签去重，保留分数更高的一条。 */
export function mergeGeneratedTags(tags: GeneratedTag[]): GeneratedTag[] {
  const merged = new Map<string, GeneratedTag>();
  for (const tag of tags) {
    const key = normalizeTagKey(tag.name);
    if (!key) continue;
    const current = merged.get(key);
    if (!current || tag.score > current.score) merged.set(key, tag);
  }
  return [...merged.values()].sort((a, b) => b.score - a.score);
}

/** VPS 不可用时的批量兜底。 */
export function buildLocalGenerateResult(
  repos: LocalRepoInput[],
  perRepo = 6
): GenerateResult {
  const items: GeneratedRepoItem[] = [];
  let skipped = 0;
  for (const repo of repos) {
    const summary = (repo.summary ?? '').trim();
    if (!summary) {
      skipped += 1;
      continue;
    }
    const tags = mergeGeneratedTags(localSuggestTags(summary, repo.language ?? '', perRepo));
    if (tags.length === 0) {
      skipped += 1;
      continue;
    }
    items.push({ repoId: repo.id, tags });
  }
  return {
    generatedAt: new Date().toISOString(),
    scanned: repos.length,
    suggested: items.length,
    skipped,
    items,
    source: 'local',
  };
}

/** D1 行 → 前端 DTO。 */
export function toTagSuggestionDto(row: TagSuggestionRow): TagSuggestionDto {
  const category = ['language', 'framework', 'domain', 'quality'].includes(row.category)
    ? (row.category as TagSuggestionCategory)
    : 'domain';
  const status = ['pending', 'accepted', 'dismissed'].includes(row.status)
    ? (row.status as TagSuggestionStatus)
    : 'pending';
  return {
    id: row.id,
    repoId: row.repo_id,
    repoName: row.repo_name || row.repo_id,
    repoUrl: row.repo_url || `https://github.com/${row.repo_id}`,
    summary: row.readme_summary ?? '',
    tagName: row.tag_name,
    category,
    score: typeof row.score === 'number' ? row.score : Number(row.score ?? 0),
    reason: row.reason ?? '',
    evidence: row.evidence ?? '',
    status,
    createdAt: row.created_at,
    updatedAt: row.updated_at,
  };
}

/** 校验并裁剪 VPS 返回结果；形状不合法返回 null（触发本地兜底）。 */
export function normalizeGeneratedResult(
  raw: unknown,
  allowedRepoIds: Iterable<string>,
  perRepo = 6
): GenerateResult | null {
  if (!raw || typeof raw !== 'object') return null;
  const data = raw as Record<string, unknown>;
  if (!Array.isArray(data.items)) return null;
  const allowed = new Set(allowedRepoIds);
  const limit = clampPerRepo(perRepo);
  const items: GeneratedRepoItem[] = [];

  for (const entry of data.items) {
    if (!entry || typeof entry !== 'object') continue;
    const item = entry as Record<string, unknown>;
    const repoId = typeof item.repoId === 'string' ? item.repoId.trim() : '';
    if (!repoId || !allowed.has(repoId) || !Array.isArray(item.tags)) continue;
    const tags: GeneratedTag[] = [];
    for (const rawTag of item.tags) {
      if (!rawTag || typeof rawTag !== 'object') continue;
      const tag = rawTag as Record<string, unknown>;
      const name = typeof tag.name === 'string' ? tag.name.trim() : '';
      if (!name) continue;
      const category = ['language', 'framework', 'domain', 'quality'].includes(String(tag.category))
        ? (tag.category as TagSuggestionCategory)
        : 'domain';
      const score = Number(tag.score);
      tags.push({
        name,
        category,
        score: Number.isFinite(score) ? Math.min(1, Math.max(0, score)) : 0,
        reason: typeof tag.reason === 'string' ? tag.reason : '',
        evidence: typeof tag.evidence === 'string' ? tag.evidence : '',
      });
    }
    const merged = mergeGeneratedTags(tags).slice(0, limit);
    if (merged.length > 0) items.push({ repoId, tags: merged });
  }

  const scanned = Number(data.scanned);
  return {
    generatedAt:
      typeof data.generatedAt === 'string' && data.generatedAt ? data.generatedAt : new Date().toISOString(),
    scanned: Number.isFinite(scanned) ? Math.max(0, Math.trunc(scanned)) : allowed.size,
    suggested: items.length,
    skipped: Number.isFinite(scanned) ? Math.max(0, Math.trunc(scanned) - items.length) : 0,
    items,
    source: 'vps',
  };
}
