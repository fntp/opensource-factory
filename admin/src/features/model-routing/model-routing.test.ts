import { describe, expect, it } from 'vitest'
import { MOCK_MODEL_ROUTE_HEALTH, MOCK_MODEL_ROUTES } from './api'
import {
  STRATEGY_OPTIONS,
  bestUpgrade,
  blockedUpgrades,
  budgetTone,
  eligibleUpgrades,
  embeddingDimensionHint,
  fallbackNames,
  formatBudgetPercent,
  formatCost,
  formatLatency,
  formatMb,
  formatQuality,
  modelOptions,
  providerBadgeVariant,
  providerLabel,
  strategyLabel,
} from './utils'

describe('model routing labels', () => {
  it('maps strategies and providers to Chinese labels', () => {
    expect(STRATEGY_OPTIONS).toHaveLength(4)
    expect(strategyLabel('budget')).toBe('预算优先')
    expect(strategyLabel('balanced')).toBe('均衡')
    expect(strategyLabel('quality')).toBe('质量优先')
    expect(strategyLabel('manual')).toBe('人工指定')
    expect(strategyLabel('unknown')).toBe('unknown')

    expect(providerLabel('ollama')).toBe('本地 Ollama')
    expect(providerLabel('deepseek')).toBe('DeepSeek 云端')
    expect(providerLabel('rules')).toBe('本地规则')
    expect(providerBadgeVariant('deepseek')).toBe('default')
    expect(providerBadgeVariant('ollama')).toBe('secondary')
    expect(providerBadgeVariant('rules')).toBe('outline')
  })
})

describe('model routing formatting', () => {
  it('formats memory, cost, latency and quality', () => {
    expect(formatMb(1300)).toBe('1300 MB')
    expect(formatMb(0)).toBe('0 MB')
    expect(formatMb(null)).toBe('—')
    expect(formatCost(0)).toBe('免费')
    expect(formatCost(0.001)).toBe('$0.0010/千 tokens')
    expect(formatLatency(5)).toBe('5 ms')
    expect(formatLatency(1200)).toBe('1.2 s')
    expect(formatQuality(72)).toBe('72 分')
    expect(formatQuality(Number.NaN)).toBe('—')
  })

  it('calculates budget percentage and tone', () => {
    expect(formatBudgetPercent(1300, 2048)).toBe(63)
    expect(formatBudgetPercent(300, 2048)).toBe(15)
    expect(formatBudgetPercent(10, 0)).toBe(0)
    expect(budgetTone(63)).toBe('ok')
    expect(budgetTone(70)).toBe('warning')
    expect(budgetTone(90)).toBe('danger')
  })
})

describe('model routing task helpers', () => {
  const summary = MOCK_MODEL_ROUTES.tasks[0]!

  it('filters eligible / blocked upgrades and picks the best', () => {
    expect(eligibleUpgrades(summary).map((item) => item.modelId)).toEqual([
      'deepseek-chat',
      'deepseek-r1-1.5b-q4',
    ])
    expect(blockedUpgrades(summary).map((item) => item.modelId)).toContain(
      'qwen2.5-7b-q4'
    )
    expect(bestUpgrade(summary)?.modelId).toBe('deepseek-chat')
  })

  it('only offers budget-safe candidates and renders fallback names', () => {
    expect(modelOptions(summary).every((item) => item.withinBudget)).toBe(true)
    expect(fallbackNames(summary)).toContain('deepseek-chat')
    expect(fallbackNames(summary)).toContain('→')
  })

  it('warns about embedding dimension changes', () => {
    const embedding = MOCK_MODEL_ROUTES.tasks.find(
      (task) => task.task === 'embedding'
    )!
    expect(embeddingDimensionHint(embedding)).toContain('1024')
    expect(embeddingDimensionHint(summary)).toBeNull()
  })
})

describe('mock model routing contract', () => {
  it('keeps six tasks and all selected models within budget', () => {
    expect(MOCK_MODEL_ROUTES.taskCount).toBe(6)
    expect(MOCK_MODEL_ROUTES.tasks).toHaveLength(6)
    for (const task of MOCK_MODEL_ROUTES.tasks) {
      expect(task.candidates.some((item) => item.id === task.modelId)).toBe(
        true
      )
      expect(task.withinBudget).toBe(true)
      expect(task.budgetMb).toBe(2048)
    }
  })

  it('keeps health and catalog contracts aligned', () => {
    expect(MOCK_MODEL_ROUTE_HEALTH.budgetMb).toBe(2048)
    expect(MOCK_MODEL_ROUTE_HEALTH.ollama.models[0]?.withinBudget).toBe(true)
    expect(MOCK_MODEL_ROUTES.models.length).toBeGreaterThanOrEqual(10)
    expect(
      MOCK_MODEL_ROUTES.models.some((item) => item.id === 'deepseek-chat')
    ).toBe(true)
  })
})
