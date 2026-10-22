import { describe, expect, it } from 'vitest'
import {
  barWidth,
  ecosystemLabel,
  formatCount,
  formatGeneratedAt,
  formatPercent,
  kindLabel,
  statusLabel,
  statusVariant,
} from './utils'

describe('dependency analysis utils', () => {
  it('formats percentages and counts', () => {
    expect(formatPercent(0.6667)).toBe('66.7%')
    expect(formatPercent(1, 0)).toBe('100%')
    expect(formatPercent(Number.NaN)).toBe('0%')
    expect(formatCount(12345)).toBe('12,345')
    expect(formatCount(Number.NaN)).toBe('0')
  })

  it('maps ecosystem / kind / status labels', () => {
    expect(ecosystemLabel('npm')).toBe('npm')
    expect(ecosystemLabel('pypi')).toBe('PyPI')
    expect(ecosystemLabel('unknown')).toBe('unknown')
    expect(kindLabel('runtime')).toBe('运行时')
    expect(kindLabel('dev')).toBe('开发依赖')
    expect(statusLabel('no_manifest')).toBe('无清单')
    expect(statusVariant('ok')).toBe('default')
    expect(statusVariant('failed')).toBe('destructive')
    expect(statusVariant('pending')).toBe('outline')
  })

  it('formats generated time and clamps bar width', () => {
    const formatted = formatGeneratedAt('2026-10-22T08:30:00Z')
    expect(formatted).toMatch(/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$/)
    expect(formatGeneratedAt('not-a-date')).toBe('—')

    expect(barWidth(0)).toBe('0%')
    expect(barWidth(0.5)).toBe('50%')
    expect(barWidth(1)).toBe('100%')
    expect(barWidth(2)).toBe('100%')
    expect(barWidth(0.001)).toBe('4%')
  })
})
