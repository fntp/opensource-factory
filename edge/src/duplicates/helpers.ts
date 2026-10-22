/**
 * 重复 / 相似项目检测纯函数（M6-03）。
 *
 * edge 侧的本地规则：地址归一化、名称相似、保守聚类与合并建议。
 * VPS 不可达时用它兜底；VPS 可用时用它补上 D1 中尚未镜像到 VPS 的仓库。
 * 不访问 D1 / 网络，便于 node:test 直接覆盖。
 */

export type DuplicateScope = 'my' | 'trending' | 'all';
export type DuplicateKind = 'exact' | 'name' | 'semantic' | 'mixed';
export type DuplicateSource = 'my' | 'trending';

export interface DuplicateRepoInput {
  source: DuplicateSource;
  repoId: string;
  platform?: string | null;
  name: string;
  description?: string | null;
  htmlUrl?: string | null;
  stars?: number | null;
  language?: string | null;
  readmeSummary?: string | null;
  categoryId?: string | null;
  techStack?: string[] | null;
}

export interface DuplicateSignals {
  nameSimilarity: number;
  descriptionSimilarity: number;
  vectorSimilarity: number | null;
  exactKey: boolean;
}

export interface DuplicateMember {
  source: DuplicateSource;
  repoId: string;
  fullName: string;
  name: string;
  description: string;
  language: string;
  stars: number;
  url: string;
  platform: string;
  categoryId: string;
  readmeSummary: string;
  techStack: string[];
  role: 'canonical' | 'merge';
  signals: DuplicateSignals;
}

export interface DuplicateFieldSuggestion {
  field: string;
  value: unknown;
  from: { source: DuplicateSource; repoId: string };
  reason: string;
}

export interface DuplicateSuggestion {
  action: 'merge' | 'review';
  keep: { source: DuplicateSource; repoId: string };
  mergeTargets: Array<{ source: DuplicateSource; repoId: string }>;
  fields: DuplicateFieldSuggestion[];
  notes: string;
}

export interface DuplicateCluster {
  id: string;
  kind: DuplicateKind;
  confidence: number;
  reasons: string[];
  members: DuplicateMember[];
  suggestion: DuplicateSuggestion;
}

const CJK = /[一-鿿]+/g;
const ASCII_WORD = /[0-9a-z]+/g;

const STOPWORDS = new Set([
  'a', 'an', 'and', 'are', 'as', 'at', 'be', 'by', 'for', 'from', 'in', 'is', 'it',
  'of', 'on', 'or', 'the', 'to', 'with', 'app', 'apps', 'demo', 'docs', 'example',
  'examples', 'lib', 'library', 'project', 'repo', 'repository', 'sdk', 'template',
  'tool', 'tools', 'ui', 'web',
]);

const CJK_STOPWORDS = new Set([
  '支持', '一个', '以及', '使用', '基于', '可以', '工具', '开源', '我们', '我的',
  '提供', '方便', '项目', '仓库', '管理', '系统', '平台',
]);

export function normalizeDuplicateScope(value: unknown): DuplicateScope | null {
  if (value === undefined || value === null || value === '') return 'all';
  return value === 'my' || value === 'trending' || value === 'all' ? value : null;
}

function parseUrl(value: string): URL | null {
  const raw = value.trim();
  if (!raw) return null;
  try {
    return new URL(raw.includes('://') ? raw : `https://${raw}`);
  } catch {
    return null;
  }
}

/** 地址归一化为 `platform:owner/repo`。 */
export function normalizeRepoKey(
  platform: string | null | undefined,
  repoId: string,
  htmlUrl?: string | null
): string {
  let platformValue = (platform ?? 'github').trim().toLowerCase() || 'github';
  let candidate = '';
  const parsed = parseUrl(htmlUrl ?? '');
  if (parsed) {
    const host = parsed.hostname.toLowerCase();
    const parts = parsed.pathname.split('/').filter(Boolean);
    if (host === 'github.com' || host === 'www.github.com') platformValue = 'github';
    if (host === 'gitee.com' || host === 'www.gitee.com') platformValue = 'gitee';
    if (
      (host === 'github.com' || host === 'www.github.com' || host === 'gitee.com' || host === 'www.gitee.com') &&
      parts.length >= 2
    ) {
      candidate = `${parts[0]}/${parts[1]}`;
    }
  }
  if (!candidate) candidate = (repoId ?? '').trim();
  candidate = candidate.replace(/\\/g, '/').trim().replace(/^\/+|\/+$/g, '');
  if (candidate.toLowerCase().endsWith('.git')) candidate = candidate.slice(0, -4);
  candidate = candidate.replace(/\s+/g, '');
  return `${platformValue}:${candidate.toLowerCase()}`;
}

export function normalizeName(value: string): string {
  const raw = (value ?? '').replace(/([a-z0-9])([A-Z])/g, '$1 $2').toLowerCase();
  return (raw.match(/[0-9a-z一-鿿]+/g) ?? []).join(' ');
}

export function textTokens(value: string): string[] {
  const raw = (value ?? '').replace(/([a-z0-9])([A-Z])/g, '$1 $2').toLowerCase();
  const tokens = new Set<string>();
  for (const chunk of raw.split(/[^0-9a-z一-鿿]+/)) {
    if (!chunk) continue;
    for (const cjk of chunk.match(CJK) ?? []) {
      if (cjk.length === 1) {
        if (!CJK_STOPWORDS.has(cjk)) tokens.add(cjk);
        continue;
      }
      for (let index = 0; index < cjk.length - 1; index += 1) {
        const bigram = cjk.slice(index, index + 2);
        if (!CJK_STOPWORDS.has(bigram)) tokens.add(bigram);
      }
    }
    for (const word of chunk.match(ASCII_WORD) ?? []) {
      if (word.length >= 2 && !STOPWORDS.has(word)) tokens.add(word);
    }
  }
  return [...tokens];
}

export function tokenJaccard(left: string[], right: string[]): number {
  if (left.length === 0 || right.length === 0) return 0;
  const a = new Set(left);
  const b = new Set(right);
  let shared = 0;
  for (const item of a) if (b.has(item)) shared += 1;
  return shared / (a.size + b.size - shared);
}

function bigramDice(left: string, right: string): number {
  if (left === right) return 1;
  if (left.length < 2 || right.length < 2) return 0;
  const grams = (value: string) => {
    const set = new Set<string>();
    for (let index = 0; index < value.length - 1; index += 1) set.add(value.slice(index, index + 2));
    return set;
  };
  const a = grams(left);
  const b = grams(right);
  let shared = 0;
  for (const item of a) if (b.has(item)) shared += 1;
  return (2 * shared) / (a.size + b.size);
}

export function nameSimilarity(left: string, right: string): number {
  const a = normalizeName(left);
  const b = normalizeName(right);
  if (!a || !b) return 0;
  if (a === b) return 1;
  return Math.max(bigramDice(a, b), tokenJaccard(textTokens(a), textTokens(b)));
}

function toMember(repo: DuplicateRepoInput): DuplicateMember {
  return {
    source: repo.source,
    repoId: repo.repoId,
    fullName: repo.repoId,
    name: repo.name || repo.repoId.split('/').pop() || repo.repoId,
    description: repo.description ?? '',
    language: repo.language ?? '',
    stars: repo.stars ?? 0,
    url: repo.htmlUrl ?? '',
    platform: repo.platform ?? 'github',
    categoryId: repo.categoryId ?? '',
    readmeSummary: repo.readmeSummary ?? '',
    techStack: repo.techStack ?? [],
    role: 'merge',
    signals: {
      nameSimilarity: 0,
      descriptionSimilarity: 0,
      vectorSimilarity: null,
      exactKey: false,
    },
  };
}

function metadataScore(member: DuplicateMember): number {
  let score = 0;
  if (member.description) score += 1;
  if (member.readmeSummary) score += 1;
  if (member.language) score += 0.5;
  if (member.categoryId) score += 0.5;
  if (member.techStack.length > 0) score += 0.5;
  return score;
}

function pickCanonical(members: DuplicateMember[]): DuplicateMember {
  const [canonical] = [...members].sort((a, b) => {
    if (a.source !== b.source) return a.source === 'my' ? -1 : 1;
    const scoreDiff = metadataScore(b) - metadataScore(a);
    if (scoreDiff !== 0) return scoreDiff;
    if (a.stars !== b.stars) return b.stars - a.stars;
    return a.repoId.localeCompare(b.repoId);
  });
  if (!canonical) throw new Error('duplicate cluster requires at least one member');
  return canonical;
}

function buildSuggestion(members: DuplicateMember[], confidence: number): DuplicateSuggestion {
  const canonical = pickCanonical(members);
  const others = members.filter((member) => member !== canonical);
  const crossSource = others.some((member) => member.source !== canonical.source);
  const action: 'merge' | 'review' = confidence >= 0.85 && others.length <= 5 ? 'merge' : 'review';
  const fields: DuplicateFieldSuggestion[] = [];
  const addField = (field: string, value: unknown, from: DuplicateMember, reason: string) => {
    if (value === null || value === undefined || value === '') return;
    fields.push({ field, value, from: { source: from.source, repoId: from.repoId }, reason });
  };

  const bestDescription = [...members].sort(
    (a, b) => b.description.length - a.description.length
  )[0]!;
  if (bestDescription.description.length > canonical.description.length) {
    addField('description', bestDescription.description, bestDescription, '取最完整的项目简介');
  }

  const bestSummary = [...members].sort(
    (a, b) => b.readmeSummary.length - a.readmeSummary.length
  )[0]!;
  if (bestSummary.readmeSummary.length > canonical.readmeSummary.length) {
    addField('readmeSummary', bestSummary.readmeSummary, bestSummary, '取最完整的 README 摘要');
  }

  if (!canonical.language) {
    const withLanguage = members.find((member) => member.language);
    if (withLanguage) addField('language', withLanguage.language, withLanguage, '补充主语言');
  }

  const maxStars = [...members].sort((a, b) => b.stars - a.stars)[0]!;
  if (maxStars.stars > canonical.stars) {
    addField('stars', maxStars.stars, maxStars, '取最大的 Star 数');
  }

  if (!canonical.categoryId) {
    const withCategory = members.find((member) => member.categoryId);
    if (withCategory) {
      addField('categoryId', withCategory.categoryId, withCategory, '补充收藏库分类');
    }
  }

  const mergedTech: string[] = [];
  for (const member of members) {
    for (const tech of member.techStack) {
      if (!mergedTech.some((item) => item.toLowerCase() === tech.toLowerCase())) mergedTech.push(tech);
    }
  }
  if (mergedTech.length > 0 && mergedTech.join('|') !== canonical.techStack.join('|')) {
    const source = members.find((member) => member.techStack.length > 0) ?? canonical;
    addField('techStack', mergedTech, source, '合并技术栈标签');
  }

  let notes = crossSource
    ? '收藏库与热榜命中同一项目，建议保留收藏库条目，将热榜的摘要 / 技术栈并入后归档。'
    : '建议保留元数据更完整的条目，合并其余重复项后归档。';
  if (action === 'review') {
    notes += ` 当前置信度 ${Math.round(confidence * 100)}%，请人工确认后再合并。`;
  }

  return {
    action,
    keep: { source: canonical.source, repoId: canonical.repoId },
    mergeTargets: others.map((member) => ({ source: member.source, repoId: member.repoId })),
    fields,
    notes,
  };
}

function buildCluster(members: DuplicateMember[], confidence: number, kind: DuplicateKind, reasons: string[]): DuplicateCluster {
  const canonical = pickCanonical(members);
  const withRoles = members.map((member) => ({
    ...member,
    role: member.repoId === canonical.repoId && member.source === canonical.source
      ? ('canonical' as const)
      : ('merge' as const),
  }));
  return {
    id: clusterSignature(withRoles),
    kind,
    confidence,
    reasons,
    members: withRoles,
    suggestion: buildSuggestion(withRoles, confidence),
  };
}

export function clusterSignature(members: Array<{ source: DuplicateSource; repoId: string }>): string {
  const raw = members
    .map((member) => `${member.source}:${member.repoId}`)
    .sort()
    .join('|');
  let hash = 5381;
  for (let index = 0; index < raw.length; index += 1) {
    hash = ((hash << 5) + hash + raw.charCodeAt(index)) >>> 0;
  }
  return `dup_${hash.toString(36)}`;
}

class UnionFind {
  private parent: number[];

  constructor(size: number) {
    this.parent = Array.from({ length: size }, (_, index) => index);
  }

  find(index: number): number {
    let current = index;
    while (this.parent[current] !== current) {
      this.parent[current] = this.parent[this.parent[current]!]!;
      current = this.parent[current]!;
    }
    return current;
  }

  union(left: number, right: number): void {
    const a = this.find(left);
    const b = this.find(right);
    if (a !== b) this.parent[b] = a;
  }
}

/** 本地名称 / 地址规则检测（保守：只做 exact 与高相似名称）。 */
export function detectNameDuplicates(
  repos: DuplicateRepoInput[],
  threshold = 0.86
): DuplicateCluster[] {
  if (repos.length < 2) return [];
  const sorted = [...repos].sort(
    (a, b) => a.source.localeCompare(b.source) || a.repoId.localeCompare(b.repoId)
  );
  const keys = sorted.map((repo) => normalizeRepoKey(repo.platform, repo.repoId, repo.htmlUrl));
  const union = new UnionFind(sorted.length);
  const scores: Array<{ left: number; right: number; score: number; exact: boolean }> = [];

  for (let left = 0; left < sorted.length; left += 1) {
    for (let right = left + 1; right < sorted.length; right += 1) {
      const a = sorted[left]!;
      const b = sorted[right]!;
      if ((a.platform ?? 'github').toLowerCase() !== (b.platform ?? 'github').toLowerCase()) continue;
      const exact = keys[left] === keys[right];
      const score = exact ? 1 : nameSimilarity(a.name, b.name);
      const descScore = tokenJaccard(
        textTokens(`${a.description ?? ''} ${a.readmeSummary ?? ''}`),
        textTokens(`${b.description ?? ''} ${b.readmeSummary ?? ''}`)
      );
      const accepted = exact || (score >= threshold && (descScore >= 0.05 || score >= 0.96));
      if (!accepted) continue;
      union.union(left, right);
      scores.push({ left, right, score, exact });
    }
  }

  const groups = new Map<number, number[]>();
  for (let index = 0; index < sorted.length; index += 1) {
    const root = union.find(index);
    groups.set(root, [...(groups.get(root) ?? []), index]);
  }

  const clusters: DuplicateCluster[] = [];
  for (const indexes of groups.values()) {
    if (indexes.length < 2) continue;
    const groupScores = scores.filter(
      (item) => indexes.includes(item.left) && indexes.includes(item.right)
    );
    if (groupScores.length === 0) continue;
    const exact = groupScores.every((item) => item.exact);
    const confidence = Math.max(...groupScores.map((item) => item.score));
    const members = indexes.map((index) => toMember(sorted[index]!));
    const reasons = exact
      ? ['仓库地址归一化后完全一致（同一项目）']
      : [`仓库名相似度 ${Math.round(confidence * 100)}%`];
    clusters.push(
      buildCluster(members, confidence, exact ? 'exact' : 'name', reasons)
    );
  }
  return clusters.sort((a, b) => b.confidence - a.confidence);
}

/** 合并多批簇：成员有交集的簇取并集，保留最高置信度与全部证据。 */
export function mergeDuplicateClusters(clusters: DuplicateCluster[]): DuplicateCluster[] {
  if (clusters.length <= 1) return clusters;
  const union = new UnionFind(clusters.length);
  const memberSets = clusters.map(
    (cluster) => new Set(cluster.members.map((member) => `${member.source}:${member.repoId}`))
  );
  for (let left = 0; left < clusters.length; left += 1) {
    for (let right = left + 1; right < clusters.length; right += 1) {
      let overlap = false;
      for (const key of memberSets[left]!) {
        if (memberSets[right]!.has(key)) {
          overlap = true;
          break;
        }
      }
      if (overlap) union.union(left, right);
    }
  }

  const groups = new Map<number, number[]>();
  for (let index = 0; index < clusters.length; index += 1) {
    const root = union.find(index);
    groups.set(root, [...(groups.get(root) ?? []), index]);
  }

  const merged: DuplicateCluster[] = [];
  for (const indexes of groups.values()) {
    if (indexes.length === 1) {
      merged.push(clusters[indexes[0]!]!);
      continue;
    }
    const group = indexes.map((index) => clusters[index]!);
    const memberMap = new Map<string, DuplicateMember>();
    for (const cluster of group) {
      for (const member of cluster.members) {
        const key = `${member.source}:${member.repoId}`;
        const existing = memberMap.get(key);
        if (!existing || existing.description.length < member.description.length) {
          memberMap.set(key, member);
        }
      }
    }
    const members = [...memberMap.values()];
    const confidence = Math.max(...group.map((cluster) => cluster.confidence));
    const reasons = [...new Set(group.flatMap((cluster) => cluster.reasons))];
    const kinds = new Set(group.map((cluster) => cluster.kind));
    const kind: DuplicateKind = kinds.size === 1 ? ([...kinds][0] ?? 'mixed') : 'mixed';
    const canonical = pickCanonical(members);
    const withRoles = members.map((member) => ({
      ...member,
      role: member.repoId === canonical.repoId && member.source === canonical.source
        ? ('canonical' as const)
        : ('merge' as const),
    }));
    merged.push({
      id: clusterSignature(withRoles),
      kind,
      confidence,
      reasons,
      members: withRoles,
      suggestion: buildSuggestion(withRoles, confidence),
    });
  }
  return merged.sort((a, b) => b.confidence - a.confidence);
}
