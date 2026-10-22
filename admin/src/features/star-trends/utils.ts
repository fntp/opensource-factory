export interface ChartPoint {
  x: number
  y: number
}

export const TREND_META = {
  new: { label: '新上榜', tone: 'new' },
  up: { label: '上升', tone: 'up' },
  down: { label: '回落', tone: 'down' },
  steady: { label: '持平', tone: 'steady' },
} as const

export type TrendKey = keyof typeof TREND_META

/** 大数字紧凑展示（中文万 / 亿） */
export function formatCompactNumber(value: number): string {
  if (!Number.isFinite(value)) return '0'
  return new Intl.NumberFormat('zh-CN', {
    notation: 'compact',
    maximumFractionDigits: 1,
  }).format(value)
}

/** 带符号的整数展示：+1,234 / -56 */
export function formatSignedNumber(value: number): string {
  if (!Number.isFinite(value)) return '0'
  const formatted = new Intl.NumberFormat('zh-CN', {
    maximumFractionDigits: 0,
  }).format(Math.abs(Math.round(value)))
  if (value > 0) return `+${formatted}`
  if (value < 0) return `-${formatted}`
  return '0'
}

/** 百分比展示：整数不带小数，其余保留一位 */
export function formatPercent(value: number): string {
  if (!Number.isFinite(value)) return '0%'
  return Number.isInteger(value) ? `${value}%` : `${value.toFixed(1)}%`
}

/** 增长率：+5.2% / -1.0% / 0% */
export function formatGrowthRate(value: number): string {
  if (!Number.isFinite(value) || value === 0) return '0%'
  return `${value > 0 ? '+' : ''}${value.toFixed(1)}%`
}

export function trendMeta(trend: string): { label: string; tone: string } {
  return TREND_META[trend as TrendKey] ?? TREND_META.steady
}

/** 把数值序列映射到 SVG 坐标；全等序列居中显示 */
export function buildPolylinePoints(
  values: readonly number[],
  width = 800,
  height = 240,
  padding = 16
): ChartPoint[] {
  if (values.length === 0) return []
  const safe = values.map((value) => (Number.isFinite(value) ? value : 0))
  const min = Math.min(...safe)
  const max = Math.max(...safe)
  const span = max - min
  const innerWidth = Math.max(1, width - padding * 2)
  const innerHeight = Math.max(1, height - padding * 2)
  const step = safe.length > 1 ? innerWidth / (safe.length - 1) : 0

  return safe.map((value, index) => ({
    x: padding + step * index,
    y:
      span === 0
        ? height / 2
        : height - padding - ((value - min) / span) * innerHeight,
  }))
}

export function buildLinePath(points: readonly ChartPoint[]): string {
  if (points.length === 0) return ''
  return points
    .map((point, index) => `${index === 0 ? 'M' : 'L'} ${point.x.toFixed(2)} ${point.y.toFixed(2)}`)
    .join(' ')
}

export function buildAreaPath(
  points: readonly ChartPoint[],
  height = 240,
  padding = 16
): string {
  if (points.length === 0) return ''
  const first = points[0]
  const last = points[points.length - 1]
  if (!first || !last) return ''
  const baseline = height - padding
  return `${buildLinePath(points)} L ${last.x.toFixed(2)} ${baseline} L ${first.x.toFixed(2)} ${baseline} Z`
}

/** 2026-10-22 → 10/22 */
export function dateLabel(value: string): string {
  const parts = value.split('-')
  if (parts.length !== 3) return value
  return `${Number(parts[1])}/${Number(parts[2])}`
}

export function periodLabel(startDate: string | null, endDate: string | null): string {
  if (!startDate || !endDate) return '暂无快照'
  return `${startDate} → ${endDate}`
}

/** 限制窗口选项，避免非法值进入接口 */
export function normalizeDays(value: number, allowed: readonly number[] = [7, 30, 90]): number {
  return allowed.includes(value) ? value : 30
}
