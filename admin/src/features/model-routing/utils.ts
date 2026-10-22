import type {
  ModelRouteModel,
  ModelRouteProvider,
  ModelRouteStrategy,
  ModelRouteTask,
} from './api'

export const STRATEGY_OPTIONS: { value: ModelRouteStrategy; label: string }[] =
  [
    { value: 'budget', label: '预算优先' },
    { value: 'balanced', label: '均衡' },
    { value: 'quality', label: '质量优先' },
    { value: 'manual', label: '人工指定' },
  ]

export function strategyLabel(strategy: ModelRouteStrategy | string): string {
  return (
    STRATEGY_OPTIONS.find((item) => item.value === strategy)?.label ?? strategy
  )
}

export function providerLabel(provider: ModelRouteProvider | string): string {
  if (provider === 'ollama') return '本地 Ollama'
  if (provider === 'deepseek') return 'DeepSeek 云端'
  if (provider === 'rules') return '本地规则'
  return provider
}

export function providerBadgeVariant(
  provider: ModelRouteProvider | string
): 'default' | 'secondary' | 'outline' {
  if (provider === 'deepseek') return 'default'
  if (provider === 'ollama') return 'secondary'
  return 'outline'
}

export function formatMb(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return '—'
  return `${Math.round(value)} MB`
}

export function formatCost(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value) || value <= 0) return '免费'
  return `$${value.toFixed(4)}/千 tokens`
}

export function formatLatency(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return '—'
  if (value < 1000) return `${Math.round(value)} ms`
  return `${(value / 1000).toFixed(1)} s`
}

export function formatQuality(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return '—'
  return `${Math.round(value)} 分`
}

export function formatBudgetPercent(
  residentMb: number,
  budgetMb: number
): number {
  if (
    !Number.isFinite(residentMb) ||
    !Number.isFinite(budgetMb) ||
    budgetMb <= 0
  ) {
    return 0
  }
  return Math.max(0, Math.min(100, Math.round((residentMb / budgetMb) * 100)))
}

export function budgetTone(percent: number): 'ok' | 'warning' | 'danger' {
  if (percent >= 90) return 'danger'
  if (percent >= 70) return 'warning'
  return 'ok'
}

export function budgetToneClass(percent: number): string {
  const tone = budgetTone(percent)
  if (tone === 'danger') return 'bg-red-500'
  if (tone === 'warning') return 'bg-amber-500'
  return 'bg-emerald-500'
}

export function eligibleUpgrades(task: ModelRouteTask) {
  return task.upgrades.filter((item) => item.eligible)
}

export function blockedUpgrades(task: ModelRouteTask) {
  return task.upgrades.filter((item) => !item.eligible)
}

export function bestUpgrade(task: ModelRouteTask) {
  return eligibleUpgrades(task)[0] ?? null
}

export function modelOptions(task: ModelRouteTask): ModelRouteModel[] {
  return task.candidates.filter((item) => item.withinBudget)
}

export function fallbackNames(task: ModelRouteTask): string {
  if (task.fallbackModels.length === 0) return '无（最终截断 / hash 兜底）'
  return task.fallbackModels
    .map((id) => task.candidates.find((item) => item.id === id)?.name ?? id)
    .join(' → ')
}

export function embeddingDimensionHint(task: ModelRouteTask): string | null {
  if (task.task !== 'embedding' || task.dimension == null) return null
  return `当前向量维度 ${task.dimension}；切换不同维度模型后需要重建向量索引。`
}
