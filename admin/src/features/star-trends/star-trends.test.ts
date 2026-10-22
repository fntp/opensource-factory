import { describe, expect, it } from 'vitest'
import { mockStarTrends } from './api'
import {
  buildAreaPath,
  buildLinePath,
  buildPolylinePoints,
  dateLabel,
  formatCompactNumber,
  formatGrowthRate,
  formatPercent,
  formatSignedNumber,
  normalizeDays,
  periodLabel,
  trendMeta,
} from './utils'

describe('format helpers', () => {
  it('formats signed numbers', () => {
    expect(formatSignedNumber(1234)).toBe('+1,234')
    expect(formatSignedNumber(-56)).toBe('-56')
    expect(formatSignedNumber(0)).toBe('0')
    expect(formatSignedNumber(Number.NaN)).toBe('0')
  })

  it('formats percentages and growth rates', () => {
    expect(formatPercent(25)).toBe('25%')
    expect(formatPercent(33.3)).toBe('33.3%')
    expect(formatPercent(Number.NaN)).toBe('0%')
    expect(formatGrowthRate(5.24)).toBe('+5.2%')
    expect(formatGrowthRate(-1)).toBe('-1.0%')
    expect(formatGrowthRate(0)).toBe('0%')
  })

  it('formats large numbers compactly', () => {
    expect(formatCompactNumber(624900)).toContain('万')
    expect(formatCompactNumber(0)).toBe('0')
    expect(formatCompactNumber(Number.NaN)).toBe('0')
  })
})

describe('chart geometry', () => {
  it('maps values onto the padded box', () => {
    const points = buildPolylinePoints([0, 10], 100, 100, 10)
    expect(points).toEqual([
      { x: 10, y: 90 },
      { x: 90, y: 10 },
    ])
  })

  it('centers a flat series and single point', () => {
    expect(buildPolylinePoints([5, 5], 100, 100, 10)).toEqual([
      { x: 10, y: 50 },
      { x: 90, y: 50 },
    ])
    expect(buildPolylinePoints([5], 100, 100, 10)).toEqual([{ x: 10, y: 50 }])
    expect(buildPolylinePoints([], 100, 100, 10)).toEqual([])
  })

  it('builds line and closed area paths', () => {
    const points = buildPolylinePoints([1, 2, 3], 100, 100, 10)
    const line = buildLinePath(points)
    expect(line.startsWith('M 10.00')).toBe(true)
    expect(line.split(' L ')).toHaveLength(3)
    const area = buildAreaPath(points, 100, 10)
    expect(area.startsWith(line)).toBe(true)
    expect(area.endsWith('Z')).toBe(true)
    expect(buildLinePath([])).toBe('')
    expect(buildAreaPath([])).toBe('')
  })
})

describe('labels and window options', () => {
  it('formats dates and periods', () => {
    expect(dateLabel('2026-10-22')).toBe('10/22')
    expect(dateLabel('bad')).toBe('bad')
    expect(periodLabel('2026-10-01', '2026-10-22')).toBe('2026-10-01 → 2026-10-22')
    expect(periodLabel(null, null)).toBe('暂无快照')
  })

  it('falls back to 30 days for unsupported windows', () => {
    expect(normalizeDays(7)).toBe(7)
    expect(normalizeDays(90)).toBe(90)
    expect(normalizeDays(15)).toBe(30)
    expect(normalizeDays(0)).toBe(30)
  })

  it('maps trends and falls back to steady', () => {
    expect(trendMeta('new').label).toBe('新上榜')
    expect(trendMeta('up').tone).toBe('up')
    expect(trendMeta('unknown')).toEqual({ label: '持平', tone: 'steady' })
  })
})

describe('mockStarTrends', () => {
  it('keeps series length within the 30-day demo history', () => {
    expect(mockStarTrends(7).series).toHaveLength(7)
    expect(mockStarTrends(30).series).toHaveLength(30)
    expect(mockStarTrends(90).series).toHaveLength(30)
    expect(mockStarTrends(30).period.snapshotDays).toBe(30)
  })

  it('sorts top movers by gain and keeps language shares at 100%', () => {
    const data = mockStarTrends(30, 'trending')
    const gains = data.topMovers.map((item) => item.gain)
    expect(gains).toEqual([...gains].sort((a, b) => b - a))
    const share = data.languages.reduce((sum, item) => sum + item.share, 0)
    expect(share).toBeCloseTo(100, 1)
    expect(data.insights.length).toBeGreaterThan(0)
  })

  it('exposes portfolio coverage for the my scope', () => {
    const data = mockStarTrends(30, 'my')
    expect(data.scope).toBe('my')
    expect(data.summary.portfolioRepos).toBe(24)
    expect(data.summary.trackedRepos).toBe(14)
    expect(data.summary.coverage).toBeCloseTo(58.3, 1)
  })
})
