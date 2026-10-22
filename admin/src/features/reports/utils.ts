import type {
  ReportItemSource,
  ReportKind,
  ReportStats,
  ReportStatus,
  ReportSummary,
} from './api'

export const REPORT_KINDS: ReportKind[] = ['weekly', 'monthly']

const KIND_LABELS: Record<ReportKind, string> = {
  weekly: '周报',
  monthly: '月报',
}

const STATUS_LABELS: Record<ReportStatus, string> = {
  ready: '已生成',
  empty: '暂无数据',
}

const SOURCE_LABELS: Record<ReportItemSource, string> = {
  collection: '收藏',
  recommendation: '推荐',
  trending: '热榜',
}

export function reportKindLabel(kind: ReportKind): string {
  return KIND_LABELS[kind] ?? kind
}

export function reportStatusLabel(status: ReportStatus): string {
  return STATUS_LABELS[status] ?? status
}

export function reportSourceLabel(source: ReportItemSource): string {
  return SOURCE_LABELS[source] ?? source
}

/** 数字展示：非法值显示破折号，其余按千分位。 */
export function formatReportCount(value: number): string {
  if (!Number.isFinite(value)) return '—'
  return new Intl.NumberFormat('zh-CN').format(Math.round(value))
}

/** 周期日期只保留 YYYY-MM-DD，避免时区把日期偏移一天。 */
export function formatReportDate(value: string | null | undefined): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec((value ?? '').trim())
  return match ? `${match[1]}-${match[2]}-${match[3]}` : '—'
}

export function formatReportPeriod(
  report: Pick<ReportSummary, 'periodStart' | 'periodEnd'>
): string {
  return `${formatReportDate(report.periodStart)} ~ ${formatReportDate(report.periodEnd)}`
}

export function formatReportGeneratedAt(value: string | null | undefined): string {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '—'
  return date.toLocaleString('zh-CN', { hour12: false })
}

export function filterReportsByKind(
  reports: readonly ReportSummary[],
  kind: ReportKind
): ReportSummary[] {
  return reports.filter((report) => report.kind === kind)
}

/** 列表默认选中：优先本期最新的一份报告。 */
export function pickDefaultReport(
  reports: readonly ReportSummary[],
  kind: ReportKind
): ReportSummary | null {
  return filterReportsByKind(reports, kind)[0] ?? null
}

export function reportFilename(
  report: Pick<ReportSummary, 'kind' | 'periodStart'>
): string {
  return `openfactory-${report.kind}-${report.periodStart}.md`
}

export interface ReportStatCard {
  title: string
  value: string
  hint: string
}

/** 报告详情顶部的四张统计卡（纯函数，便于测试口径）。 */
export function reportStatCards(stats: ReportStats): ReportStatCard[] {
  return [
    {
      title: '收藏总数',
      value: formatReportCount(stats.totalRepos),
      hint: `本期新增 ${formatReportCount(stats.newRepos)} 个`,
    },
    {
      title: 'Star 合计',
      value: formatReportCount(stats.totalStars),
      hint: `本期新增 ${formatReportCount(stats.newStars)} Star`,
    },
    {
      title: '推荐 / 热榜',
      value: `${formatReportCount(stats.recommendationCount)} / ${formatReportCount(stats.trendingCount)}`,
      hint: '本期精选条目数',
    },
    {
      title: '主要语言',
      value: stats.topLanguage ?? '—',
      hint: `${formatReportCount(stats.languageCount)} 种语言 · ${formatReportCount(stats.categoryCount)} 个分类`,
    },
  ]
}
