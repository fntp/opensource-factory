/**
 * 技术栈图谱聚合（M6-04）。
 *
 * 输入：当前用户 D1 `my_repositories` 行 + `repo_tags` 标签行。
 * 输出：语言分布、框架分布、语言 × 框架关系图，供 admin「技术栈图谱」页渲染。
 *
 * 口径：
 * - 语言取仓库 `language` 字段，缺失的仓库计入 `unknownLanguage`，不进入语言榜；
 * - 框架由「标签精确命中 + 简介 / 摘要关键词命中」启发式识别，同一仓库同一框架只计一次；
 * - `share` 统一以全部收藏仓库数为分母，便于横向比较覆盖率；
 * - 图谱只保留 Top N 语言与框架，避免前端节点过多不可读。
 */
import { FRAMEWORK_CATALOG, type FrameworkSpec } from './catalog.ts';

export interface TechStackRepoRow {
  id: string;
  name: string;
  language: string | null;
  stars: number | null;
  description: string | null;
  readme_summary: string | null;
}

export interface TechStackTagRow {
  repo_id: string;
  name: string;
}

export interface TechStackLanguage {
  name: string;
  repoCount: number;
  starCount: number;
  share: number;
  frameworks: string[];
}

export interface TechStackFramework {
  name: string;
  category: string;
  repoCount: number;
  starCount: number;
  share: number;
  languages: string[];
}

export interface TechStackGraphNode {
  id: string;
  label: string;
  kind: 'language' | 'framework';
  category?: string;
  weight: number;
}

export interface TechStackGraphLink {
  source: string;
  target: string;
  weight: number;
}

export interface TechStackSummary {
  totalRepos: number;
  withLanguage: number;
  withFramework: number;
  languageCount: number;
  frameworkCount: number;
  topLanguage: string | null;
  topFramework: string | null;
  coverage: number;
  totalStars: number;
}

export interface TechStackResponse {
  summary: TechStackSummary;
  languages: TechStackLanguage[];
  frameworks: TechStackFramework[];
  graph: {
    nodes: TechStackGraphNode[];
    links: TechStackGraphLink[];
  };
  generatedAt: string;
}

export interface BuildTechStackOptions {
  maxLanguages?: number;
  maxFrameworks?: number;
  now?: Date;
}

const LANGUAGE_DISPLAY: Record<string, string> = {
  typescript: 'TypeScript',
  javascript: 'JavaScript',
  python: 'Python',
  go: 'Go',
  golang: 'Go',
  rust: 'Rust',
  java: 'Java',
  kotlin: 'Kotlin',
  swift: 'Swift',
  'c++': 'C++',
  cpp: 'C++',
  'c#': 'C#',
  csharp: 'C#',
  ruby: 'Ruby',
  php: 'PHP',
  scala: 'Scala',
  dart: 'Dart',
  elixir: 'Elixir',
  lua: 'Lua',
  html: 'HTML',
  css: 'CSS',
  scss: 'SCSS',
  shell: 'Shell',
  bash: 'Shell',
  vue: 'Vue',
  svelte: 'Svelte',
  'jupyter notebook': 'Jupyter Notebook',
  'objective-c': 'Objective-C',
  r: 'R',
  matlab: 'MATLAB',
  haskell: 'Haskell',
  clojure: 'Clojure',
  zig: 'Zig',
  nim: 'Nim',
  perl: 'Perl',
  powershell: 'PowerShell',
  dockerfile: 'Dockerfile',
  makefile: 'Makefile',
};

/** 把标签 / 别名归一为小写、空格分隔的稳定键 */
export function normalizeToken(value: string): string {
  return value
    .trim()
    .toLowerCase()
    .replace(/[\s._/-]+/g, ' ')
    .trim();
}

/** 归一语言名；空值返回 null，未知语言保留原样（去首尾空格） */
export function normalizeLanguage(value: string | null | undefined): string | null {
  const raw = (value ?? '').trim();
  if (!raw) return null;
  return LANGUAGE_DISPLAY[raw.toLowerCase()] ?? raw;
}

const ALIAS_TO_SPEC = new Map<string, FrameworkSpec>();
const SPEC_BY_NAME = new Map<string, FrameworkSpec>();
const SPEC_ORDER = new Map<string, number>();
const TEXT_MATCHERS: Array<{ spec: FrameworkSpec; pattern: RegExp }> = [];

for (const [index, spec] of FRAMEWORK_CATALOG.entries()) {
  SPEC_BY_NAME.set(spec.name, spec);
  SPEC_ORDER.set(spec.name, index);
  for (const alias of spec.aliases) {
    ALIAS_TO_SPEC.set(normalizeToken(alias), spec);
    const escaped = alias.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    // 英文 / 数字别名使用词边界，避免 react 命中 reactive、vite 命中 invite
    TEXT_MATCHERS.push({
      spec,
      pattern: new RegExp(`(^|[^a-z0-9])${escaped}([^a-z0-9]|$)`, 'i'),
    });
  }
}

/**
 * 识别单个仓库的框架集合。
 *
 * 先按标签精确命中（用户手工标注优先），再对简介 + 摘要做关键词扫描；
 * 返回按词表顺序排序的 canonical 名称。
 */
export function matchFrameworks(
  repo: TechStackRepoRow,
  tags: readonly string[] = []
): string[] {
  const found = new Set<string>();

  for (const tag of tags) {
    const spec = ALIAS_TO_SPEC.get(normalizeToken(tag));
    if (spec) found.add(spec.name);
  }

  const text = `${repo.description ?? ''} ${repo.readme_summary ?? ''}`
    .toLowerCase()
    .slice(0, 8000);
  if (text.trim()) {
    for (const { spec, pattern } of TEXT_MATCHERS) {
      if (found.has(spec.name)) continue;
      if (pattern.test(text)) found.add(spec.name);
    }
  }

  return [...found].sort(
    (a, b) => (SPEC_ORDER.get(a) ?? Number.MAX_SAFE_INTEGER) - (SPEC_ORDER.get(b) ?? Number.MAX_SAFE_INTEGER)
  );
}

interface LanguageAcc {
  name: string;
  repoCount: number;
  starCount: number;
}

interface FrameworkAcc {
  spec: FrameworkSpec;
  repoCount: number;
  starCount: number;
  languages: Set<string>;
}

function percent(part: number, total: number): number {
  if (total <= 0) return 0;
  return Math.round((part / total) * 1000) / 10;
}

/**
 * 聚合技术栈图谱。
 *
 * 纯函数，不访问 D1 / 网络；`now` 仅用于测试固定 `generatedAt`。
 */
export function buildTechStackGraph(
  repos: readonly TechStackRepoRow[],
  tagRows: readonly TechStackTagRow[] = [],
  options: BuildTechStackOptions = {}
): TechStackResponse {
  const maxLanguages = Math.max(1, options.maxLanguages ?? 8);
  const maxFrameworks = Math.max(1, options.maxFrameworks ?? 16);
  const totalRepos = repos.length;

  const tagsByRepo = new Map<string, string[]>();
  for (const row of tagRows) {
    const list = tagsByRepo.get(row.repo_id);
    if (list) list.push(row.name);
    else tagsByRepo.set(row.repo_id, [row.name]);
  }

  const languageAgg = new Map<string, LanguageAcc>();
  const frameworkAgg = new Map<string, FrameworkAcc>();
  const pairCounts = new Map<string, number>();
  let withLanguage = 0;
  let withFramework = 0;
  let withCoverage = 0;
  let totalStars = 0;

  for (const repo of repos) {
    const language = normalizeLanguage(repo.language);
    const stars = Number(repo.stars ?? 0) || 0;
    totalStars += stars;
    if (language) withLanguage += 1;

    const frameworks = matchFrameworks(repo, tagsByRepo.get(repo.id) ?? []);
    if (frameworks.length > 0) withFramework += 1;
    if (language || frameworks.length > 0) withCoverage += 1;

    if (language) {
      const acc = languageAgg.get(language) ?? {
        name: language,
        repoCount: 0,
        starCount: 0,
      };
      acc.repoCount += 1;
      acc.starCount += stars;
      languageAgg.set(language, acc);
    }

    for (const name of frameworks) {
      const spec = SPEC_BY_NAME.get(name);
      if (!spec) continue;
      const acc = frameworkAgg.get(name) ?? {
        spec,
        repoCount: 0,
        starCount: 0,
        languages: new Set<string>(),
      };
      acc.repoCount += 1;
      acc.starCount += stars;
      if (language) acc.languages.add(language);
      frameworkAgg.set(name, acc);

      if (language) {
        const key = `${language}\u0000${name}`;
        pairCounts.set(key, (pairCounts.get(key) ?? 0) + 1);
      }
    }
  }

  const languages: TechStackLanguage[] = [...languageAgg.values()]
    .sort(
      (a, b) =>
        b.repoCount - a.repoCount ||
        b.starCount - a.starCount ||
        a.name.localeCompare(b.name)
    )
    .map((acc) => ({
      name: acc.name,
      repoCount: acc.repoCount,
      starCount: acc.starCount,
      share: percent(acc.repoCount, totalRepos),
      frameworks: [...frameworkAgg.values()]
        .filter((fw) => fw.languages.has(acc.name))
        .sort((a, b) => b.repoCount - a.repoCount || a.spec.name.localeCompare(b.spec.name))
        .slice(0, 6)
        .map((fw) => fw.spec.name),
    }));

  const frameworks: TechStackFramework[] = [...frameworkAgg.values()]
    .sort(
      (a, b) =>
        b.repoCount - a.repoCount ||
        b.starCount - a.starCount ||
        a.spec.name.localeCompare(b.spec.name)
    )
    .map((acc) => ({
      name: acc.spec.name,
      category: acc.spec.category,
      repoCount: acc.repoCount,
      starCount: acc.starCount,
      share: percent(acc.repoCount, totalRepos),
      languages: [...acc.languages].sort((a, b) => {
        const left = languageAgg.get(a)?.repoCount ?? 0;
        const right = languageAgg.get(b)?.repoCount ?? 0;
        return right - left || a.localeCompare(b);
      }),
    }));

  const topLanguages = languages.slice(0, maxLanguages);
  const topFrameworks = frameworks.slice(0, maxFrameworks);
  const languageIds = new Set(topLanguages.map((item) => `lang:${item.name}`));
  const frameworkIds = new Set(topFrameworks.map((item) => `fw:${item.name}`));

  const nodes: TechStackGraphNode[] = [
    ...topLanguages.map((item) => ({
      id: `lang:${item.name}`,
      label: item.name,
      kind: 'language' as const,
      weight: item.repoCount,
    })),
    ...topFrameworks.map((item) => ({
      id: `fw:${item.name}`,
      label: item.name,
      kind: 'framework' as const,
      category: item.category,
      weight: item.repoCount,
    })),
  ];

  const links: TechStackGraphLink[] = [];
  for (const [key, weight] of pairCounts) {
    const [language, framework] = key.split('\u0000');
    if (!language || !framework) continue;
    const source = `lang:${language}`;
    const target = `fw:${framework}`;
    if (!languageIds.has(source) || !frameworkIds.has(target)) continue;
    links.push({ source, target, weight });
  }
  links.sort((a, b) => b.weight - a.weight || a.target.localeCompare(b.target));

  return {
    summary: {
      totalRepos,
      withLanguage,
      withFramework,
      languageCount: languages.length,
      frameworkCount: frameworks.length,
      topLanguage: languages[0]?.name ?? null,
      topFramework: frameworks[0]?.name ?? null,
      coverage: percent(withCoverage, totalRepos),
      totalStars,
    },
    languages,
    frameworks,
    graph: { nodes, links },
    generatedAt: (options.now ?? new Date()).toISOString(),
  };
}
