/**
 * Agent 工作流纯函数（REQ-202610-0968 / M7-09）。
 *
 * 模板、参数归一化、本地计划 / 草稿生成与 DTO 映射；不访问 D1 / 网络，
 * 便于 node:test 直接覆盖，也作为 VPS 不可达时的本地兜底。
 */
import type {
  AgentAction,
  AgentDraft,
  AgentDraftMetadata,
  AgentDraftRow,
  AgentDraftStatus,
  AgentMode,
  AgentPlanStep,
  AgentRunDetail,
  AgentRunResult,
  AgentRunRow,
  AgentRunSummary,
  AgentTemplate,
} from '../types';

export interface AgentRepoSnapshot {
  repoId: string;
  name: string;
  description: string;
  language: string;
  stars: number;
  category: string;
  tags: string[];
  summary: string;
}

export interface AgentTemplateDefinition {
  key: AgentTemplate;
  title: string;
  description: string;
  defaultMode: AgentMode;
  defaultThreshold: number;
}

export const AGENT_TEMPLATES: AgentTemplateDefinition[] = [
  {
    key: 'organize',
    title: '自动整理',
    description: '汇总待处理的标签 / 分类建议，按阈值生成整理计划，可选择直接应用。',
    defaultMode: 'preview',
    defaultThreshold: 0.75,
  },
  {
    key: 'draft',
    title: '收藏草稿',
    description: '基于当前收藏、分类与标签，生成一份可编辑的 Markdown 精选草稿。',
    defaultMode: 'preview',
    defaultThreshold: 0.75,
  },
  {
    key: 'full',
    title: '整理 + 草稿',
    description: '先整理标签 / 分类，再把本次变更写进收藏草稿，一次完成维护与输出。',
    defaultMode: 'apply',
    defaultThreshold: 0.75,
  },
];

export const AGENT_TEMPLATE_KEYS = AGENT_TEMPLATES.map((item) => item.key);

export function normalizeAgentTemplate(value: unknown, fallback: AgentTemplate = 'draft'): AgentTemplate {
  const text = String(value ?? '').trim().toLowerCase();
  return (AGENT_TEMPLATE_KEYS as string[]).includes(text) ? (text as AgentTemplate) : fallback;
}

export function normalizeAgentMode(value: unknown, fallback: AgentMode = 'preview'): AgentMode {
  return String(value ?? '').trim().toLowerCase() === 'apply' ? 'apply' : fallback;
}

/** 阈值：默认 0.75，范围 0.5~1.0，保留两位小数。 */
export function clampAgentThreshold(value: unknown, fallback = 0.75): number {
  const parsed = typeof value === 'number' ? value : Number.parseFloat(String(value ?? ''));
  if (!Number.isFinite(parsed)) return fallback;
  return Math.round(Math.min(1, Math.max(0.5, parsed)) * 100) / 100;
}

/** repoIds：去重、去空、最多 200 条。 */
export function normalizeAgentRepoIds(value: unknown, max = 200): string[] {
  if (!Array.isArray(value)) return [];
  const result: string[] = [];
  for (const item of value) {
    if (typeof item !== 'string') continue;
    const trimmed = item.trim();
    if (trimmed && !result.includes(trimmed)) result.push(trimmed);
    if (result.length >= max) break;
  }
  return result;
}

export function normalizeAgentFocus(value: unknown, max = 120): string | null {
  if (typeof value !== 'string') return null;
  const trimmed = value.trim().slice(0, max);
  return trimmed || null;
}

export function normalizeAgentDraftStatus(
  value: unknown,
  fallback: AgentDraftStatus = 'draft'
): AgentDraftStatus {
  const text = String(value ?? '').trim().toLowerCase();
  if (text === 'draft' || text === 'applied' || text === 'discarded') return text;
  return fallback;
}

function fnvHash(input: string): string {
  let h1 = 0x811c9dc5;
  let h2 = 0x01000193;
  for (let index = 0; index < input.length; index += 1) {
    const code = input.charCodeAt(index);
    h1 ^= code;
    h1 = Math.imul(h1, 16777619) >>> 0;
    h2 = Math.imul(h2 ^ code, 2654435761) >>> 0;
  }
  return `${h1.toString(16).padStart(8, '0')}${h2.toString(16).padStart(8, '0')}`;
}

export function makeAgentRunId(userId: string, now = new Date()): string {
  return `run_${now.getTime().toString(36)}_${fnvHash(`${userId}|${now.toISOString()}`).slice(0, 8)}`;
}

export function makeAgentDraftId(userId: string, now = new Date()): string {
  return `draft_${now.getTime().toString(36)}_${fnvHash(`draft|${userId}|${now.toISOString()}`).slice(0, 8)}`;
}

export function computeAgentStats(repos: AgentRepoSnapshot[]): AgentRunResult['stats'] {
  const categories = new Set<string>();
  const languages = new Set<string>();
  const tags = new Set<string>();
  const languageCounts = new Map<string, number>();
  let totalStars = 0;

  for (const repo of repos) {
    totalStars += Math.max(0, Number(repo.stars) || 0);
    const category = repo.category.trim();
    if (category) categories.add(category);
    const language = repo.language.trim();
    if (language) {
      languages.add(language);
      languageCounts.set(language, (languageCounts.get(language) ?? 0) + 1);
    }
    for (const tag of repo.tags) {
      const name = tag.trim();
      if (name) tags.add(name);
    }
  }

  const topLanguage =
    [...languageCounts.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))[0]?.[0] ??
    null;
  const topCategory = [...categories].sort((a, b) => a.localeCompare(b))[0] ?? null;

  return {
    totalRepos: repos.length,
    totalStars,
    categoryCount: categories.size,
    languageCount: languages.size,
    tagCount: tags.size,
    topLanguage,
    topCategory,
  };
}

/** 本地计划：与 VPS plan_workflow 保持相同的步骤 key / 状态语义。 */
export function buildLocalPlan(input: {
  template: AgentTemplate;
  mode: AgentMode;
  threshold: number;
  repoCount: number;
  pendingTags: number;
  pendingCategories: number;
}): AgentPlanStep[] {
  const { template, mode, threshold, repoCount, pendingTags, pendingCategories } = input;
  const organize = template === 'organize' || template === 'full';
  const steps: AgentPlanStep[] = [
    {
      key: 'inventory',
      title: '盘点收藏',
      detail: `扫描 ${repoCount} 个收藏仓库，读取分类、标签与摘要覆盖。`,
      count: repoCount,
      status: repoCount > 0 ? 'ready' : 'skipped',
    },
  ];

  if (organize) {
    steps.push(
      {
        key: 'tags',
        title: '整理标签',
        detail: `${pendingTags} 条标签建议达到阈值 ${threshold.toFixed(2)}，${
          mode === 'apply' ? '将写入 tags / repo_tags。' : '先生成预览，不写入。'
        }`,
        count: pendingTags,
        status: pendingTags > 0 ? 'ready' : 'skipped',
      },
      {
        key: 'categories',
        title: '整理分类',
        detail: `${pendingCategories} 条分类建议达到阈值 ${threshold.toFixed(2)}，${
          mode === 'apply' ? '将写入仓库分类。' : '先生成预览，不写入。'
        }`,
        count: pendingCategories,
        status: pendingCategories > 0 ? 'ready' : 'skipped',
      }
    );
  } else {
    steps.push({
      key: 'organize',
      title: '整理建议',
      detail: '当前模板只生成草稿，不处理标签 / 分类建议。',
      count: 0,
      status: 'skipped',
    });
  }

  steps.push({
    key: 'draft',
    title: '生成草稿',
    detail: `基于 ${repoCount} 个收藏生成一份可编辑的 Markdown 精选草稿。`,
    count: repoCount,
    status: repoCount > 0 ? 'ready' : 'skipped',
  });
  return steps;
}

function formatStars(value: number): string {
  const number = Math.max(0, Math.trunc(Number(value) || 0));
  if (number >= 10000) return `${(number / 10000).toFixed(1)} 万`;
  if (number >= 1000) return `${(number / 1000).toFixed(1)}k`;
  return String(number);
}

function escapeMarkdown(text: string): string {
  return text
    .replace(/\\/g, '\\\\')
    .replace(/[[\]#*_|`()]/g, (char) => `\\${char}`)
    .trim();
}

function repoLine(repo: AgentRepoSnapshot): string {
  const name = escapeMarkdown(repo.name || repo.repoId);
  const meta = [repo.language, `⭐ ${formatStars(repo.stars)}`].filter(Boolean).join(' · ');
  const description = escapeMarkdown(repo.description || repo.summary || '暂无简介');
  const tags = repo.tags
    .slice(0, 4)
    .filter(Boolean)
    .map((tag) => `#${escapeMarkdown(tag)}`)
    .join(' ');
  return `- [${name}](https://github.com/${repo.repoId}) — ${description}（${meta}）${
    tags ? ` ${tags}` : ''
  }`;
}

export interface LocalDraftResult {
  title: string;
  markdown: string;
  highlights: string[];
  stats: AgentRunResult['stats'];
}

/** 本地草稿：结构与 VPS 响应一致，VPS 不可达时使用。 */
export function buildLocalDraft(input: {
  template: AgentTemplate;
  repos: AgentRepoSnapshot[];
  appliedTags?: AgentAction[];
  appliedCategories?: AgentAction[];
  focus?: string | null;
  generatedAt?: Date;
}): LocalDraftResult {
  const { template, repos, appliedTags = [], appliedCategories = [], focus } = input;
  const now = input.generatedAt ?? new Date();
  const dateText = now.toISOString().slice(0, 10);
  const stats = computeAgentStats(repos);
  const sorted = [...repos].sort((a, b) => b.stars - a.stars || a.repoId.localeCompare(b.repoId));
  const title = focus ? `${focus} · 收藏精选草稿` : `我的开源收藏精选 · ${dateText}`;

  const lines: string[] = [
    `# ${title}`,
    '',
    `> 由 OpenFactory Agent 基于 ${repos.length} 个收藏生成于 ${dateText}；模板 \`${template}\`，可在发布前自由编辑。`,
    '',
    '## 概览',
    '',
    `- 收藏总数：${stats.totalRepos}`,
    `- Star 合计：${formatStars(stats.totalStars)}`,
    `- 分类数：${stats.categoryCount}`,
    `- 语言数：${stats.languageCount}`,
    `- 标签数：${stats.tagCount}`,
    '',
    '## 本期亮点',
    '',
  ];

  if (sorted.length === 0) {
    lines.push('- 收藏库还是空的，先同步一些项目再来生成草稿。', '');
  } else {
    sorted.slice(0, 3).forEach((repo, index) => {
      lines.push(
        `${index + 1}. **${escapeMarkdown(repo.name || repo.repoId)}** — ${escapeMarkdown(
          repo.description || repo.summary || '暂无简介'
        )}`
      );
    });
    lines.push('');
  }

  lines.push('## 分类精选', '');
  const grouped = new Map<string, AgentRepoSnapshot[]>();
  for (const repo of sorted) {
    const key = repo.category.trim() || '未分类';
    grouped.set(key, [...(grouped.get(key) ?? []), repo]);
  }
  if (grouped.size === 0) {
    lines.push('暂无收藏项目。', '');
  } else {
    const categories = [...grouped.keys()].sort(
      (a, b) => (grouped.get(b)?.length ?? 0) - (grouped.get(a)?.length ?? 0) || a.localeCompare(b)
    );
    for (const category of categories) {
      const items = grouped.get(category) ?? [];
      lines.push(`### ${escapeMarkdown(category)}（${items.length}）`, '');
      for (const repo of items.slice(0, 8)) lines.push(repoLine(repo));
      if (items.length > 8) lines.push(`- …另有 ${items.length - 8} 个项目`);
      lines.push('');
    }
  }

  lines.push('## 本次整理', '');
  if (appliedTags.length > 0 || appliedCategories.length > 0) {
    lines.push(`- 应用标签建议 ${appliedTags.length} 条`);
    for (const action of appliedTags.slice(0, 10)) {
      lines.push(`  - \`${action.repoId}\` → #${escapeMarkdown(action.value)}`);
    }
    lines.push(`- 应用分类建议 ${appliedCategories.length} 条`);
    for (const action of appliedCategories.slice(0, 10)) {
      lines.push(`  - \`${action.repoId}\` → ${escapeMarkdown(action.value)}`);
    }
  } else {
    lines.push('- 本次未自动应用标签 / 分类建议（预览模式或没有达到阈值的建议）。');
  }
  lines.push('', '## 发布清单', '', '- [ ] 核对项目描述与链接', '- [ ] 补充一段个人点评', '- [ ] 选择发布渠道（博客 / 周报 / 社群）', '');

  return {
    title,
    markdown: `${lines.join('\n').trim()}\n`,
    highlights: [
      `收藏 ${stats.totalRepos} 个项目，累计 ${formatStars(stats.totalStars)} Star`,
      `覆盖 ${stats.categoryCount} 个分类、${stats.languageCount} 种语言`,
      `整理动作：标签 ${appliedTags.length} 条、分类 ${appliedCategories.length} 条`,
    ],
    stats,
  };
}

function parseJson<T>(value: string | null | undefined, fallback: T): T {
  if (!value) return fallback;
  try {
    return (JSON.parse(value) as T) ?? fallback;
  } catch {
    return fallback;
  }
}

const EMPTY_RESULT: AgentRunResult = {
  appliedTags: [],
  appliedCategories: [],
  pendingTags: 0,
  pendingCategories: 0,
  stats: {
    totalRepos: 0,
    totalStars: 0,
    categoryCount: 0,
    languageCount: 0,
    tagCount: 0,
    topLanguage: null,
    topCategory: null,
  },
  source: 'local',
};

const EMPTY_METADATA: AgentDraftMetadata = {
  highlights: [],
  stats: EMPTY_RESULT.stats,
  template: 'draft',
  mode: 'preview',
  focus: null,
};

export function toAgentRunSummary(row: AgentRunRow): AgentRunSummary {
  return {
    id: row.id,
    template: normalizeAgentTemplate(row.template),
    mode: normalizeAgentMode(row.mode),
    status: row.status === 'failed' ? 'failed' : 'completed',
    threshold: Number(row.threshold ?? 0.75),
    repoCount: Number(row.repo_count ?? 0),
    draftId: row.draft_id ?? null,
    createdAt: row.created_at,
    finishedAt: row.finished_at,
    error: row.error,
  };
}

export function toAgentDraft(row: AgentDraftRow): AgentDraft {
  return {
    id: row.id,
    runId: row.run_id,
    kind: row.kind,
    title: row.title,
    content: row.content,
    status: normalizeAgentDraftStatus(row.status),
    metadata: parseJson<AgentDraftMetadata>(row.metadata, EMPTY_METADATA),
    createdAt: row.created_at,
    updatedAt: row.updated_at,
  };
}

export function toAgentRunDetail(row: AgentRunRow, draft: AgentDraft | null): AgentRunDetail {
  return {
    ...toAgentRunSummary(row),
    plan: parseJson<AgentPlanStep[]>(row.plan, []),
    result: parseJson<AgentRunResult>(row.result, EMPTY_RESULT),
    draft,
  };
}
