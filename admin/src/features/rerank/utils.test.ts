import { describe, expect, it } from 'vitest'
import {
  WEIGHT_PRESETS,
  formatPercent,
  formatRankShift,
  rankShift,
  signalPercent,
  topSignals,
  weightSummary,
} from './utils'

describe('精排工具函数', () => {
  it('格式化百分比并裁剪范围', () => {
    expect(formatPercent(0.876)).toBe('88%')
    expect(formatPercent(1.2)).toBe('100%')
    expect(formatPercent(-0.2)).toBe('0%')
    expect(formatPercent(Number.NaN)).toBe('—')
  })

  it('名次变化方向与文案', () => {
    expect(rankShift({ rankBefore: 3, rankAfter: 1 })).toBe(2)
    expect(formatRankShift({ rankBefore: 3, rankAfter: 1 })).toBe('↑2')
    expect(formatRankShift({ rankBefore: 1, rankAfter: 4 })).toBe('↓3')
    expect(formatRankShift({ rankBefore: 2, rankAfter: 2 })).toBe('—')
  })

  it('信号进度条百分比', () => {
    expect(signalPercent(0.55)).toBe(55)
    expect(signalPercent(2)).toBe(100)
    expect(signalPercent(Number.NaN)).toBe(0)
  })

  it('按贡献取前 N 个信号', () => {
    const signals = topSignals(
      {
        contributions: {
          relevance: 0.3,
          health: 0.1,
          affinity: 0.2,
        },
      },
      2
    )
    expect(signals.map((item) => item.key)).toEqual(['relevance', 'affinity'])
    expect(signals[0].label).toBe('相关性')
  })

  it('权重预设均为六路信号且总和大于 0', () => {
    expect(WEIGHT_PRESETS.length).toBeGreaterThanOrEqual(4)
    for (const preset of WEIGHT_PRESETS) {
      const values = Object.values(preset.weights)
      expect(values).toHaveLength(6)
      expect(values.reduce((sum, value) => sum + value, 0)).toBeGreaterThan(0)
      expect(preset.mmrLambda).toBeGreaterThan(0)
      expect(preset.mmrLambda).toBeLessThanOrEqual(1)
    }
    expect(weightSummary(WEIGHT_PRESETS[0].weights)).toContain('相关性')
  })
})
