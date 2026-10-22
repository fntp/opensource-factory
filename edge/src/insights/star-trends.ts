/**
 * Star 趋势与洞察聚合（M7-05）。
 *
 * 输入：M2-05 `trending_snapshots` 的按日快照行，以及（可选）当前用户收藏库。
 * 输出：KPI、每日序列、Top Movers、新上榜、语言贡献与确定性洞察文案。
 *
 * 口径：
 * - 仓库净增 = 窗口内首个快照与最后一个快照的 `stars` 差；只有一天快照时使用该日 `star_delta`；
 * - 每日 `starGain` 使用快照自带的 `star_delta`（相对上一有效快照），可能包含窗口外增长；
 * - `scope=my` 的总 Star 使用收藏库当前值，覆盖率 = 有快照仓库数 / 收藏总数；
 * - 所有聚合均为纯函数，不访问 D1 / 网络，便于单测与后续复用。
 */

export interface StarSnapshotRow {
  snapshot_date: string;
  repo_id: string;
  owner: string | null;
  name: string;
  html_url: string;
  description: string | null;
  language: string | null;
  stars: number | null;
  stars_today: number | null;
  rank: number | null;
  language_rank: number | null;
  star_delta: number | null;
  rank_delta: number | null;
  appearances: number | null;
  is_new: number | null;
  trend: string | null;
}

export interface PortfolioRepoRow {
  id: string;
  name: string;
  stars: number | null;
  language: string | null;
}

export type StarTrendScope = 'trending' | 'my';

export interface StarTrendPoint {
  date: string;
  trackedRepos: number;
  totalStars: number;
  starGain: number;
  newRepos: number;
}

export interface StarMover {
  repoId: string;
  name: string;
  owner: string;
  url: string;
  language: string | null;
  stars: number;
  gain: number;
  growthRate: number;
  appearances: number;
  trend: 'new' | 'up' | 'down' | 'steady';
  sparkline: number[];
  firstDate: string;
  lastDate: string;
}

export interface StarLanguageInsight {
  language: string;
  repoCount: number;
  starGain: number;
  share: number;
  topRepo: string | null;
}

export type StarInsightKind =
  | 'growth'
  | 'language'
  | 'new'
  | 'concentration'
  | 'cooling';

export interface StarInsight {
  kind: StarInsightKind;
  title: string;
  description: string;
  repoId?: string;
}

export interface StarTrendSummary {
  trackedRepos: number;
  totalStars: number;
  starGain: number;
  averageDailyGain: number;
  fastestGrowing: {
    repoId: string;
    name: string;
    gain: number;
    growthRate: number;
  } | null;
  newEntries: number;
  risingRepos: number;
  fallingRepos: number;
  portfolioRepos?: number;
  coverage?: number;
}

export interface StarTrendsResponse {
  scope: StarTrendScope;
  period: {
    days: number;
    startDate: string | null;
    endDate: string | null;
    snapshotDays: number;
  };
  summary: StarTrendSummary;
  series: StarTrendPoint[];
  topMovers: StarMover[];
  newEntries: StarMover[];
  languages: StarLanguageInsight[];
  insights: StarInsight[];
  generatedAt: string;
}

export interface BuildStarTrendsOptions {
  days: number;
  scope: StarTrendScope;
  language?: string | null;
  portfolio?: readonly PortfolioRepoRow[];
  now?: Date;
}

interface RepoSeries {
  repoId: string;
  owner: string;
  name: string;
  url: string;
  language: string | null;
  rows: StarSnapshotRow[];
  first: StarSnapshotRow;
  last: StarSnapshotRow;
  gain: number;
  growthRate: number;
  appearances: number;
  trend: StarMover['trend'];
  sparkline: number[];
  firstDate: string;
  lastDate: string;
}

function num(value: number | null | undefined): number {
  return Number.isFinite(value) ? Number(value) : 0;
}

function round1(value: number): number {
  return Math.round(value * 10) / 10;
}

function formatInt(value: number): string {
  return new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 0 }).format(
    Math.round(value)
  );
}

function normalizeRows(rows: readonly StarSnapshotRow[]): StarSnapshotRow[] {
  const byDate = new Map<string, StarSnapshotRow>();
  for (const row of rows) {
    if (!row.snapshot_date || !row.repo_id) continue;
    byDate.set(row.snapshot_date, row);
  }
  return [...byDate.values()].sort((a, b) =>
    a.snapshot_date.localeCompare(b.snapshot_date)
  );
}

function buildRepoSeries(
  repoId: string,
  rows: readonly StarSnapshotRow[]
): RepoSeries | null {
  const normalized = normalizeRows(rows);
  const first = normalized[0];
  const last = normalized[normalized.length - 1];
  if (!first || !last) return null;

  const firstStars = num(first.stars);
  const lastStars = num(last.stars);
  const gain =
    normalized.length === 1 ? num(last.star_delta) : lastStars - firstStars;
  const baseStars =
    normalized.length === 1 ? Math.max(0, lastStars - gain) : firstStars;
  const growthRate =
    baseStars > 0
      ? round1((gain / baseStars) * 100)
      : gain > 0
        ? 100
        : 0;

  const appearances = normalized.reduce(
    (max, row) => Math.max(max, num(row.appearances)),
    normalized.length
  );
  const trend: StarMover['trend'] = first.is_new
    ? 'new'
    : gain > 0
      ? 'up'
      : gain < 0
        ? 'down'
        : 'steady';

  return {
    repoId,
    owner: last.owner ?? repoId.split('/')[0] ?? '',
    name: last.name || repoId.split('/')[1] || repoId,
    url: last.html_url,
    language: last.language,
    rows: normalized,
    first,
    last,
    gain,
    growthRate,
    appearances,
    trend,
    sparkline: normalized.slice(-30).map((row) => num(row.stars)),
    firstDate: first.snapshot_date,
    lastDate: last.snapshot_date,
  };
}

function toMover(series: RepoSeries): StarMover {
  return {
    repoId: series.repoId,
    name: series.name,
    owner: series.owner,
    url: series.url,
    language: series.language,
    stars: num(series.last.stars),
    gain: series.gain,
    growthRate: series.growthRate,
    appearances: series.appearances,
    trend: series.trend,
    sparkline: series.sparkline,
    firstDate: series.firstDate,
    lastDate: series.lastDate,
  };
}

function buildSeries(
  rows: readonly StarSnapshotRow[],
  dates: readonly string[]
): StarTrendPoint[] {
  const byDate = new Map<string, StarSnapshotRow[]>();
  const firstByRepo = new Map<string, StarSnapshotRow>();
  for (const row of rows) {
    const list = byDate.get(row.snapshot_date) ?? [];
    list.push(row);
    byDate.set(row.snapshot_date, list);
    const first = firstByRepo.get(row.repo_id);
    if (!first || row.snapshot_date < first.snapshot_date) {
      firstByRepo.set(row.repo_id, row);
    }
  }

  return dates.map((date) => {
    const dayRows = byDate.get(date) ?? [];
    return {
      date,
      trackedRepos: dayRows.length,
      totalStars: dayRows.reduce((sum, row) => sum + num(row.stars), 0),
      starGain: dayRows.reduce((sum, row) => sum + num(row.star_delta), 0),
      newRepos: dayRows.filter((row) => {
        const first = firstByRepo.get(row.repo_id);
        return first?.snapshot_date === date && Boolean(first.is_new);
      }).length,
    };
  });
}

function buildLanguages(series: readonly RepoSeries[]): StarLanguageInsight[] {
  const groups = new Map<
    string,
    { repoCount: number; starGain: number; topRepo: string | null; topGain: number }
  >();

  for (const repo of series) {
    const language = repo.language?.trim();
    if (!language) continue;
    const current = groups.get(language) ?? {
      repoCount: 0,
      starGain: 0,
      topRepo: null,
      topGain: Number.NEGATIVE_INFINITY,
    };
    current.repoCount += 1;
    if (repo.gain > 0) current.starGain += repo.gain;
    if (repo.gain > current.topGain) {
      current.topGain = repo.gain;
      current.topRepo = repo.repoId;
    }
    groups.set(language, current);
  }

  const totalGain = [...groups.values()].reduce(
    (sum, group) => sum + group.starGain,
    0
  );
  return [...groups.entries()]
    .map(([language, group]) => ({
      language,
      repoCount: group.repoCount,
      starGain: group.starGain,
      share: totalGain > 0 ? round1((group.starGain / totalGain) * 100) : 0,
      topRepo: group.topRepo,
    }))
    .sort(
      (a, b) =>
        b.starGain - a.starGain ||
        b.repoCount - a.repoCount ||
        a.language.localeCompare(b.language, 'zh-Hans-CN')
    )
    .slice(0, 8);
}

function buildInsights(
  series: readonly RepoSeries[],
  topMovers: readonly StarMover[],
  newEntries: readonly StarMover[],
  languages: readonly StarLanguageInsight[],
  days: number,
  totalNewEntries: number
): StarInsight[] {
  if (series.length === 0) return [];
  const insights: StarInsight[] = [];
  const fastest = topMovers[0];

  if (fastest && fastest.gain > 0) {
    insights.push({
      kind: 'growth',
      title: '增长冠军',
      description: `近 ${days} 天 ${fastest.repoId} Star 增长 ${formatInt(fastest.gain)}（+${fastest.growthRate}%），连续上榜 ${fastest.appearances} 天。`,
      repoId: fastest.repoId,
    });
  }

  const topLanguage = languages[0];
  if (topLanguage && topLanguage.starGain > 0 && topLanguage.share >= 25) {
    insights.push({
      kind: 'language',
      title: '语言升温',
      description: `${topLanguage.language} 贡献了 ${topLanguage.share}% 的 Star 增量（${formatInt(topLanguage.starGain)}），共有 ${topLanguage.repoCount} 个项目上榜。`,
    });
  }

  if (newEntries.length > 0) {
    insights.push({
      kind: 'new',
      title: '新面孔',
      description: `本期有 ${totalNewEntries} 个新上榜项目，${newEntries[0]?.repoId ?? ''} 以 ${formatInt(newEntries[0]?.gain ?? 0)} Star 增量领跑。`,
      ...(newEntries[0] ? { repoId: newEntries[0].repoId } : {}),
    });
  }

  const positive = series
    .filter((repo) => repo.gain > 0)
    .sort((a, b) => b.gain - a.gain);
  const totalPositive = positive.reduce((sum, repo) => sum + repo.gain, 0);
  if (positive.length >= 5 && totalPositive > 0) {
    const top3 = positive
      .slice(0, 3)
      .reduce((sum, repo) => sum + repo.gain, 0);
    const share = round1((top3 / totalPositive) * 100);
    if (share >= 50) {
      insights.push({
        kind: 'concentration',
        title: '头部集中',
        description: `Star 增量集中在头部 3 个项目，合计贡献 ${share}%（${formatInt(top3)} / ${formatInt(totalPositive)}）。`,
      });
    }
  }

  const cooling = [...series]
    .filter((repo) => repo.gain < 0)
    .sort((a, b) => a.gain - b.gain)[0];
  if (cooling) {
    insights.push({
      kind: 'cooling',
      title: '降温提醒',
      description: `${cooling.repoId} 本期 Star 减少 ${formatInt(Math.abs(cooling.gain))}，建议复核项目活跃度。`,
      repoId: cooling.repoId,
    });
  }

  return insights.slice(0, 5);
}

export function buildStarTrends(
  rows: readonly StarSnapshotRow[],
  options: BuildStarTrendsOptions
): StarTrendsResponse {
  const days = Math.min(365, Math.max(1, Math.round(options.days || 30)));
  const language = options.language?.trim().toLowerCase() || null;
  const portfolio = options.portfolio ?? [];
  const allowed =
    options.scope === 'my'
      ? new Set(portfolio.map((repo) => repo.id))
      : null;
  const filteredRows = rows.filter((row) => {
    if (allowed && !allowed.has(row.repo_id)) return false;
    if (language && (row.language ?? '').toLowerCase() !== language) return false;
    return true;
  });

  const grouped = new Map<string, StarSnapshotRow[]>();
  for (const row of filteredRows) {
    const list = grouped.get(row.repo_id) ?? [];
    list.push(row);
    grouped.set(row.repo_id, list);
  }

  const series: RepoSeries[] = [];
  for (const [repoId, repoRows] of grouped) {
    const built = buildRepoSeries(repoId, repoRows);
    if (built) series.push(built);
  }

  const dates = [
    ...new Set(filteredRows.map((row) => row.snapshot_date)),
  ].sort((a, b) => a.localeCompare(b));
  const startDate = dates[0] ?? null;
  const endDate = dates[dates.length - 1] ?? null;

  const daily = buildSeries(filteredRows, dates);
  const topMovers = series
    .filter((repo) => repo.gain > 0)
    .sort(
      (a, b) =>
        b.gain - a.gain ||
        b.growthRate - a.growthRate ||
        a.repoId.localeCompare(b.repoId)
    )
    .slice(0, 10)
    .map(toMover);

  const newSeries = series
    .filter((repo) => repo.first.is_new)
    .sort((a, b) => b.gain - a.gain || a.repoId.localeCompare(b.repoId));
  const newEntries = newSeries.slice(0, 5).map(toMover);

  const languages = buildLanguages(series);
  const starGain = series.reduce((sum, repo) => sum + repo.gain, 0);
  const fastest = series
    .filter((repo) => repo.gain > 0)
    .sort((a, b) => b.gain - a.gain || a.repoId.localeCompare(b.repoId))[0];

  const isMy = options.scope === 'my';
  const totalStars = isMy
    ? portfolio.reduce((sum, repo) => sum + num(repo.stars), 0)
    : series.reduce((sum, repo) => sum + num(repo.last.stars), 0);
  const coverage =
    isMy && portfolio.length > 0
      ? round1((series.length / portfolio.length) * 100)
      : isMy
        ? 0
        : undefined;

  return {
    scope: options.scope,
    period: {
      days,
      startDate,
      endDate,
      snapshotDays: dates.length,
    },
    summary: {
      trackedRepos: series.length,
      totalStars,
      starGain,
      averageDailyGain: round1(starGain / Math.max(1, dates.length - 1)),
      fastestGrowing: fastest
        ? {
            repoId: fastest.repoId,
            name: fastest.name,
            gain: fastest.gain,
            growthRate: fastest.growthRate,
          }
        : null,
      newEntries: newSeries.length,
      risingRepos: series.filter((repo) => repo.gain > 0).length,
      fallingRepos: series.filter((repo) => repo.gain < 0).length,
      ...(isMy
        ? { portfolioRepos: portfolio.length, coverage: coverage ?? 0 }
        : {}),
    },
    series: daily,
    topMovers,
    newEntries,
    languages,
    insights: buildInsights(
      series,
      topMovers,
      newEntries,
      languages,
      days,
      newSeries.length
    ),
    generatedAt: (options.now ?? new Date()).toISOString(),
  };
}
