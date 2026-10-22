import { DEFAULT_RERANK_WEIGHTS, type RerankItem, type RerankWeights } from './api'

export const SIGNAL_LABELS: Record<string, string> = {
  relevance: '相关性',
  affinity: '画像亲和',
  freshness: '时效',
  momentum: '动量',
  popularity: '人气',
  health: '健康度',
}

export interface WeightPreset {
  value: string
  label: string
  description: string
  weights: RerankWeights
  mmrLambda: number
}

export const WEIGHT_PRESETS: WeightPreset[] = [
  {
    value: 'balanced',
    label: '均衡（默认）',
    description: '相关性优先，兼顾画像、时效、热度与健康度',
    weights: DEFAULT_RERANK_WEIGHTS,
    mmrLambda: 0.75,
  },
  {
    value: 'relevance',
    label: '相关性优先',
    description: '提高语义相关性权重，适合目标非常明确的收藏库',
    weights: {
      relevance: 0.7,
      affinity: 0.1,
      freshness: 0.06,
      momentum: 0.06,
      popularity: 0.04,
      health: 0.04,
    },
    mmrLambda: 0.9,
  },
  {
    value: 'diversity',
    label: '多样性优先',
    description: '降低 MMR λ，主动压制同语言 / 同技术栈重复项',
    weights: {
      relevance: 0.35,
      affinity: 0.15,
      freshness: 0.12,
      momentum: 0.1,
      popularity: 0.08,
      health: 0.1,
    },
    mmrLambda: 0.45,
  },
  {
    value: 'freshness',
    label: '新鲜度优先',
    description: '提高时效与动量权重，优先发现近期活跃项目',
    weights: {
      relevance: 0.3,
      affinity: 0.1,
      freshness: 0.3,
      momentum: 0.15,
      popularity: 0.05,
      health: 0.1,
    },
    mmrLambda: 0.75,
  },
]

/** 0~1 比例 → 百分比文本。 */
export function formatPercent(value: number, digits = 0): string {
  if (!Number.isFinite(value)) return '—'
  return `${(Math.max(0, Math.min(1, value)) * 100).toFixed(digits)}%`
}

/** 0~1 信号值 → 进度条百分比（0~100 整数）。 */
export function signalPercent(value: number): number {
  if (!Number.isFinite(value)) return 0
  return Math.round(Math.max(0, Math.min(1, value)) * 100)
}

/** 名次变化：正数表示上升，负数表示下降。 */
export function rankShift(item: Pick<RerankItem, 'rankBefore' | 'rankAfter'>): number {
  return item.rankBefore - item.rankAfter
}

/** 名次变化文本：↑2 / ↓1 / —。 */
export function formatRankShift(item: Pick<RerankItem, 'rankBefore' | 'rankAfter'>): string {
  const shift = rankShift(item)
  if (shift > 0) return `↑${shift}`
  if (shift < 0) return `↓${Math.abs(shift)}`
  return '—'
}

/** 名次变化配色。 */
export function rankShiftClass(item: Pick<RerankItem, 'rankBefore' | 'rankAfter'>): string {
  const shift = rankShift(item)
  if (shift > 0) return 'text-emerald-600'
  if (shift < 0) return 'text-rose-600'
  return 'text-muted-foreground'
}

/** 信号贡献排序，用于展示前 N 个理由。 */
export function topSignals(
  item: Pick<RerankItem, 'contributions'>,
  limit = 3
): Array<{ key: string; label: string; value: number }> {
  return Object.entries(item.contributions ?? {})
    .filter(([, value]) => Number.isFinite(value))
    .sort((a, b) => b[1] - a[1])
    .slice(0, Math.max(1, limit))
    .map(([key, value]) => ({
      key,
      label: SIGNAL_LABELS[key] ?? key,
      value,
    }))
}

/** 权重摘要：按从高到低输出前 3 项。 */
export function weightSummary(weights: RerankWeights): string {
  return Object.entries(weights)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 3)
    .map(([key, value]) => `${SIGNAL_LABELS[key] ?? key} ${formatPercent(value)}`)
    .join(' · ')
}

/** 生成时间展示。 */
export function formatGeneratedAt(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '—'
  return date.toLocaleString('zh-CN', { hour12: false })
}
