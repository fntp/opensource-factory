import type { TrendingTrend } from './api'

export interface TrendBadge {
  label: string
  tone: 'up' | 'down' | 'new' | 'same'
}

/** 趋势徽标文案：新上榜 / ↑N / ↓N / —。 */
export function trendBadge(
  trend: TrendingTrend,
  rankChange: number | null
): TrendBadge {
  if (trend === 'new') return { label: '新上榜', tone: 'new' }
  if (trend === 'up' && rankChange && rankChange > 0) {
    return { label: `↑${rankChange}`, tone: 'up' }
  }
  if (trend === 'down' && rankChange && rankChange < 0) {
    return { label: `↓${Math.abs(rankChange)}`, tone: 'down' }
  }
  return { label: '—', tone: 'same' }
}

/** 趋势徽标的 Tailwind 颜色类。 */
export function trendToneClass(tone: TrendBadge['tone']): string {
  switch (tone) {
    case 'up':
      return 'border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-900 dark:bg-emerald-950 dark:text-emerald-300'
    case 'down':
      return 'border-rose-200 bg-rose-50 text-rose-700 dark:border-rose-900 dark:bg-rose-950 dark:text-rose-300'
    case 'new':
      return 'border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-300'
    default:
      return 'text-muted-foreground'
  }
}

/** 日期展示：2026-10-22 → 2026年10月22日。 */
export function formatSnapshotDate(value: string | null): string {
  if (!value) return '—'
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value)
  if (!match) return value
  return `${match[1]}年${Number(match[2])}月${Number(match[3])}日`
}
