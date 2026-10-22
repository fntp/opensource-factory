/**
 * 精选报告生成（M7-03）。
 *
 * 纯函数模块：周期解析、数据聚合、统计口径、分节、摘要与 Markdown 渲染。
 * 不访问 D1 / 网络，便于 node:test 直接覆盖；持久化在 routes/reports.ts。
 */
import type {
  ReportItem,
  ReportKind,
  ReportSection,
  ReportStats,
  ReportStatus,
} from '../types';

const DAY_MS = 86_400_000;

/** 推荐中不应出现在报告里的状态：已忽略 / 已过期 / 已收藏（已在收藏库） */
const EXCLUDED_RECOMMENDATION_STATUSES = new Set(['dismissed', 'expired', 'saved']);

/** D1 查询出的仓库行（仅报告需要的列） */
export interface ReportRepoInput {
  id: string;
  name: string | null;
  description: string | null;
  html_url: string | null;
  stars: number | null;
  language: string | null;
  category_id: string | null;
  created_at: string | null;
  owner?: string | null;
}

export interface ReportCategoryInput {
  id: string;
  name: string;
}

export interface ReportRecommendationInput {
  id: string;
  user_id?: string | null;
  repo_id: string | null;
  owner: string | null;
  name: string | null;
  description: string | null;
  language: string | null;
  stars: number | null;
  score: number | null;
  reason: string | null;
  url: string | null;
  status: string | null;
  created_at: string | null;
}

export interface ReportTrendingInput {
  snapshot_date: string;
  repo_id: string;
  owner: string | null;
  name: string | null;
  html_url: string | null;
  description: string | null;
  language: string | null;
  stars: number | null;
  star_delta: number | null;
  rank: number | null;
}

export interface ReportTagInput {
  repo_id: string;
  name: string;
}

export interface ReportSourceData {
  repos: ReportRepoInput[];
  categories: ReportCategoryInput[];
  recommendations: ReportRecommendationInput[];
  trending: ReportTrendingInput[];
  tags?: ReportTagInput[];
}

export interface ReportPeriod {
  start: string;
  end: string;
  label: string;
  title: string;
}

export interface BuiltReport {
  id: string;
  kind: ReportKind;
  periodStart: string;
  periodEnd: string;
  title: string;
  summary: string;
  stats: ReportStats;
  sections: ReportSection[];
  markdown: string;
  status: ReportStatus;
  generatedAt: string;
}

function pad2(value: number): string {
  return String(value).padStart(2, '0');
}

/** 输出 YYYY-MM-DD（UTC）。 */
export function formatDateOnly(date: Date): string {
  return `${date.getUTCFullYear()}-${pad2(date.getUTCMonth() + 1)}-${pad2(date.getUTCDate())}`;
}

function formatMonthDay(date: Date): string {
  return `${pad2(date.getUTCMonth() + 1)}-${pad2(date.getUTCDate())}`;
}

/** 解析 YYYY-MM-DD（也接受带时间后缀的 SQLite 时间串）；非法返回 null。 */
export function parseDateOnly(value: string | null | undefined): Date | null {
  if (!value) return null;
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(value.trim());
  if (!match) return null;
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  if (!Number.isFinite(year) || !Number.isFinite(month) || !Number.isFinite(day)) return null;
  const date = new Date(Date.UTC(year, month - 1, day));
  if (
    date.getUTCFullYear() !== year ||
    date.getUTCMonth() !== month - 1 ||
    date.getUTCDate() !== day
  ) {
    return null;
  }
  return date;
}

/**
 * 解析报告周期。
 *
 * - weekly：自然周（周一 00:00 UTC 至周日 23:59 UTC）；
 * - monthly：自然月（1 日至月末，UTC）；
 * - mode=current：截至 now 的当前周期；mode=previous：上一个完整周期。
 */
export function resolveReportPeriod(
  kind: ReportKind,
  now: Date = new Date(),
  mode: 'current' | 'previous' = 'current'
): ReportPeriod {
  const base = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate()));

  if (kind === 'monthly') {
    const start =
      mode === 'previous'
        ? new Date(Date.UTC(base.getUTCFullYear(), base.getUTCMonth() - 1, 1))
        : new Date(Date.UTC(base.getUTCFullYear(), base.getUTCMonth(), 1));
    const end =
      mode === 'previous'
        ? new Date(Date.UTC(base.getUTCFullYear(), base.getUTCMonth(), 0))
        : base;
    const label = `${start.getUTCFullYear()} 年 ${pad2(start.getUTCMonth() + 1)} 月`;
    return {
      start: formatDateOnly(start),
      end: formatDateOnly(end),
      label,
      title: `月度精选报告 · ${label}`,
    };
  }

  const weekday = (base.getUTCDay() + 6) % 7; // 周一 = 0
  const monday = new Date(base.getTime() - weekday * DAY_MS);
  const start = mode === 'previous' ? new Date(monday.getTime() - 7 * DAY_MS) : monday;
  const end = mode === 'previous' ? new Date(monday.getTime() - DAY_MS) : base;
  const label = `${formatMonthDay(start)} ~ ${formatMonthDay(end)}`;
  return {
    start: formatDateOnly(start),
    end: formatDateOnly(end),
    label,
    title: `每周精选报告 · ${label}`,
  };
}

/** 判断时间串是否落在周期内（按日期比较，忽略时分秒）。 */
export function isWithinPeriod(
  value: string | null | undefined,
  period: Pick<ReportPeriod, 'start' | 'end'>
): boolean {
  const date = parseDateOnly(value);
  if (!date) return false;
  const text = formatDateOnly(date);
  return text >= period.start && text <= period.end;
}

/** 数字归一化：D1 可能返回 number / string / null。 */
export function toNumber(value: unknown): number {
  const parsed = typeof value === 'number' ? value : Number(value ?? 0);
  return Number.isFinite(parsed) ? parsed : 0;
}

/** 千分位格式化（不依赖 ICU，测试稳定）。 */
export function formatCount(value: number): string {
  return String(Math.round(toNumber(value))).replace(/\B(?=(\d{3})+(?!\d))/g, ',');
}

function cleanText(value: string | null | undefined): string | null {
  const text = (value ?? '').trim();
  return text ? text : null;
}

function fullName(
  owner: string | null | undefined,
  name: string | null | undefined,
  fallback: string
): string {
  const cleanName = cleanText(name) ?? fallback;
  const cleanOwner = cleanText(owner);
  if (!cleanOwner || cleanName.includes('/')) return cleanName;
  return `${cleanOwner}/${cleanName}`;
}

function repoUrl(row: ReportRepoInput): string {
  return cleanText(row.html_url) ?? `https://github.com/${row.id}`;
}

function mostCommon(values: string[]): string | null {
  if (values.length === 0) return null;
  const counts = new Map<string, number>();
  for (const value of values) {
    counts.set(value, (counts.get(value) ?? 0) + 1);
  }
  const sorted = [...counts.entries()].sort((a, b) => {
    if (b[1] !== a[1]) return b[1] - a[1];
    return a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : 0;
  });
  return sorted[0]?.[0] ?? null;
}

function repoToItem(
  row: ReportRepoInput,
  categoryName: string | null,
  tags: string[]
): ReportItem {
  return {
    id: row.id,
    name: fullName(row.owner, row.name, row.id),
    url: repoUrl(row),
    description: cleanText(row.description),
    language: cleanText(row.language),
    stars: toNumber(row.stars),
    starsDelta: 0,
    reason: null,
    source: 'collection',
    category: categoryName,
    tags,
  };
}

function recommendationToItem(
  row: ReportRecommendationInput,
  categoryName: string | null = null
): ReportItem {
  const repoId = cleanText(row.repo_id) ?? cleanText(row.name) ?? row.id;
  return {
    id: repoId,
    name: fullName(row.owner, row.name, repoId),
    url: cleanText(row.url) ?? `https://github.com/${repoId}`,
    description: cleanText(row.description),
    language: cleanText(row.language),
    stars: toNumber(row.stars),
    starsDelta: 0,
    reason: cleanText(row.reason),
    source: 'recommendation',
    category: categoryName,
    tags: [],
  };
}

function trendingToItem(row: ReportTrendingInput): ReportItem {
  return {
    id: row.repo_id,
    name: fullName(row.owner, row.name, row.repo_id),
    url: cleanText(row.html_url) ?? `https://github.com/${row.repo_id}`,
    description: cleanText(row.description),
    language: cleanText(row.language),
    stars: toNumber(row.stars),
    starsDelta: toNumber(row.star_delta),
    reason: null,
    source: 'trending',
    category: null,
    tags: [],
  };
}

function byStarsDesc(a: ReportItem, b: ReportItem): number {
  if (b.stars !== a.stars) return b.stars - a.stars;
  return a.name < b.name ? -1 : a.name > b.name ? 1 : 0;
}

function byDeltaDesc(a: ReportItem, b: ReportItem): number {
  if (b.starsDelta !== a.starsDelta) return b.starsDelta - a.starsDelta;
  return byStarsDesc(a, b);
}

function buildStats(
  repos: ReportItem[],
  newItems: ReportItem[],
  recommendationCount: number,
  trendingCount: number
): ReportStats {
  const categories = repos
    .map((item) => item.category)
    .filter((value): value is string => Boolean(value));
  const languages = repos
    .map((item) => item.language)
    .filter((value): value is string => Boolean(value));

  return {
    totalRepos: repos.length,
    newRepos: newItems.length,
    totalStars: repos.reduce((sum, item) => sum + item.stars, 0),
    newStars: newItems.reduce((sum, item) => sum + item.stars, 0),
    categoryCount: new Set(categories).size,
    languageCount: new Set(languages).size,
    recommendationCount,
    trendingCount,
    topLanguage: mostCommon(languages),
    topCategory: mostCommon(categories),
  };
}

function buildSummary(kind: ReportKind, stats: ReportStats): string {
  const range = kind === 'weekly' ? '本周' : '本月';
  const hasAny =
    stats.totalRepos > 0 || stats.recommendationCount > 0 || stats.trendingCount > 0;
  if (!hasAny) {
    return `${range}还没有可汇总的数据：先同步收藏或生成推荐，下一期报告会更丰富。`;
  }

  const parts: string[] = [];
  if (stats.newRepos > 0) {
    parts.push(
      `${range}新增 ${stats.newRepos} 个收藏${
        stats.newStars > 0 ? `（+${formatCount(stats.newStars)} Star）` : ''
      }`
    );
  } else {
    parts.push(`${range}收藏库没有新增项目`);
  }
  if (stats.totalRepos > 0) {
    parts.push(`当前共收藏 ${stats.totalRepos} 个项目、累计 ${formatCount(stats.totalStars)} Star`);
  }
  if (stats.recommendationCount > 0) {
    parts.push(`为你精选 ${stats.recommendationCount} 个推荐`);
  }
  if (stats.trendingCount > 0) {
    parts.push(`捕捉 ${stats.trendingCount} 个热榜项目`);
  }
  return `${parts.join('；')}。`;
}

function escapeLinkText(value: string): string {
  return value.replace(/\\/g, '\\\\').replace(/\[/g, '\\[').replace(/\]/g, '\\]');
}

function escapeUrl(value: string): string {
  return value.replace(/\)/g, '%29').replace(/\s/g, '%20');
}

function renderItem(item: ReportItem, index: number): string {
  const meta = [`⭐ ${formatCount(item.stars)}`];
  if (item.starsDelta > 0) meta.push(`本期 +${formatCount(item.starsDelta)}`);
  if (item.language) meta.push(item.language);
  if (item.category) meta.push(item.category);
  if (item.tags.length > 0) {
    meta.push(item.tags.slice(0, 3).map((tag) => `#${tag}`).join(' '));
  }

  const lines = [`${index}. [${escapeLinkText(item.name)}](${escapeUrl(item.url)}) — ${meta.join(' · ')}`];
  if (item.description) lines.push(`   ${item.description}`);
  if (item.reason) lines.push(`   推荐理由：${item.reason}`);
  return lines.join('\n');
}

/** 渲染 Markdown（确定性输出，供下载 / 归档）。 */
export function renderReportMarkdown(input: {
  title: string;
  period: ReportPeriod;
  summary: string;
  stats: ReportStats;
  sections: ReportSection[];
  generatedAt: string;
}): string {
  const { title, period, summary, stats, sections, generatedAt } = input;
  const lines: string[] = [
    `# ${title}`,
    '',
    `> 周期：${period.start} ~ ${period.end}（UTC）｜生成时间：${generatedAt}`,
    '',
    summary,
    '',
    '## 数据概览',
    '',
    `- 收藏总数：${formatCount(stats.totalRepos)}`,
    `- 本期新增收藏：${formatCount(stats.newRepos)}`,
    `- Star 合计：${formatCount(stats.totalStars)}`,
    `- 本期新增 Star：${formatCount(stats.newStars)}`,
    `- 分类 / 语言：${formatCount(stats.categoryCount)} / ${formatCount(stats.languageCount)}`,
    `- 推荐 / 热榜：${formatCount(stats.recommendationCount)} / ${formatCount(stats.trendingCount)}`,
  ];
  if (stats.topLanguage) lines.push(`- 主要语言：${stats.topLanguage}`);
  if (stats.topCategory) lines.push(`- 主要分类：${stats.topCategory}`);

  for (const section of sections) {
    lines.push('', `## ${section.title}`, '');
    if (section.items.length === 0) {
      lines.push('本周期暂无内容。');
      continue;
    }
    lines.push(section.description, '');
    section.items.forEach((item, index) => {
      lines.push(renderItem(item, index + 1));
    });
  }

  lines.push('');
  return lines.join('\n');
}

/** 稳定报告 id：同一用户 + 周期重复生成时保持不变。 */
export function buildReportId(userId: string, kind: ReportKind, periodStart: string): string {
  let hash = 2_166_136_261;
  const seed = `${userId}:${kind}:${periodStart}`;
  for (let i = 0; i < seed.length; i += 1) {
    hash ^= seed.charCodeAt(i);
    hash = Math.imul(hash, 16_777_619);
  }
  const suffix = (hash >>> 0).toString(36).padStart(6, '0');
  return `rpt_${kind}_${periodStart.replace(/-/g, '')}_${suffix}`;
}

export interface BuildReportInput {
  userId: string;
  kind: ReportKind;
  period: ReportPeriod;
  data: ReportSourceData;
  generatedAt?: Date;
}

/** 把原始数据聚合为一份完整报告（纯函数）。 */
export function buildReport(input: BuildReportInput): BuiltReport {
  const { userId, kind, period, data } = input;
  const generatedAt = (input.generatedAt ?? new Date()).toISOString();

  const categoryNames = new Map<string, string>();
  for (const category of data.categories) {
    if (category.id && category.name) categoryNames.set(category.id, category.name);
  }

  const tagsByRepo = new Map<string, string[]>();
  for (const tag of data.tags ?? []) {
    if (!tag.repo_id || !tag.name) continue;
    const list = tagsByRepo.get(tag.repo_id) ?? [];
    list.push(tag.name);
    tagsByRepo.set(tag.repo_id, list);
  }

  const repoItems = data.repos.map((row) =>
    repoToItem(
      row,
      row.category_id ? (categoryNames.get(row.category_id) ?? null) : null,
      (tagsByRepo.get(row.id) ?? []).slice().sort()
    )
  );

  const allNewItems = data.repos
    .filter((row) => isWithinPeriod(row.created_at, period))
    .map((row) =>
      repoToItem(
        row,
        row.category_id ? (categoryNames.get(row.category_id) ?? null) : null,
        (tagsByRepo.get(row.id) ?? []).slice().sort()
      )
    );
  const newItems = allNewItems.slice().sort(byStarsDesc).slice(0, 6);

  const topItems = repoItems.slice().sort(byStarsDesc).slice(0, 6);

  const recommendationByRepo = new Map<string, ReportRecommendationInput>();
  for (const row of data.recommendations) {
    if (!isWithinPeriod(row.created_at, period)) continue;
    if (EXCLUDED_RECOMMENDATION_STATUSES.has((row.status ?? 'new').trim().toLowerCase())) continue;
    const key = cleanText(row.repo_id) ?? row.id;
    const existing = recommendationByRepo.get(key);
    if (!existing || toNumber(row.score) > toNumber(existing.score)) {
      recommendationByRepo.set(key, row);
    }
  }
  const eligibleRecommendations = [...recommendationByRepo.values()].sort((a, b) => {
    const scoreDiff = toNumber(b.score) - toNumber(a.score);
    if (scoreDiff !== 0) return scoreDiff;
    return a.id < b.id ? -1 : a.id > b.id ? 1 : 0;
  });
  const recommendationItems = eligibleRecommendations
    .slice(0, 5)
    .map((row) => recommendationToItem(row));

  const periodTrending = data.trending.filter((row) => isWithinPeriod(row.snapshot_date, period));
  const trendingByRepo = new Map<string, ReportTrendingInput>();
  for (const row of periodTrending) {
    const existing = trendingByRepo.get(row.repo_id);
    if (!existing || toNumber(row.star_delta) > toNumber(existing.star_delta)) {
      trendingByRepo.set(row.repo_id, row);
    }
  }
  const trendingItems = [...trendingByRepo.values()]
    .map((row) => trendingToItem(row))
    .sort(byDeltaDesc)
    .slice(0, 5);

  const stats = buildStats(
    repoItems,
    allNewItems,
    eligibleRecommendations.length,
    new Set(periodTrending.map((row) => row.repo_id)).size
  );

  const sections: ReportSection[] = [
    {
      key: 'new',
      title: '本期新增收藏',
      description: '本周期加入收藏库的项目，按 Star 排序。',
      items: newItems,
    },
    {
      key: 'top',
      title: '收藏库之星',
      description: '当前收藏中 Star 最高的项目，值得回看。',
      items: topItems,
    },
    {
      key: 'recommendations',
      title: '推荐关注',
      description: '结合你的收藏与偏好生成的推荐。',
      items: recommendationItems,
    },
    {
      key: 'trending',
      title: '热榜精选',
      description: '本周期 Star 增长最快的开源项目。',
      items: trendingItems,
    },
  ];

  const summary = buildSummary(kind, stats);
  const title = period.title;
  const status: ReportStatus = sections.every((section) => section.items.length === 0)
    ? 'empty'
    : 'ready';
  const markdown = renderReportMarkdown({
    title,
    period,
    summary,
    stats,
    sections,
    generatedAt,
  });

  return {
    id: buildReportId(userId, kind, period.start),
    kind,
    periodStart: period.start,
    periodEnd: period.end,
    title,
    summary,
    stats,
    sections,
    markdown,
    status,
    generatedAt,
  };
}
