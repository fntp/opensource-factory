import { describe, expect, it } from 'vitest'
import { formatSnapshotDate, trendBadge, trendToneClass } from './trend'

describe('trendBadge', () => {
  it('marks new entries', () => {
    expect(trendBadge('new', null)).toEqual({ label: '新上榜', tone: 'new' })
  })

  it('renders rank gains and drops', () => {
    expect(trendBadge('up', 3)).toEqual({ label: '↑3', tone: 'up' })
    expect(trendBadge('down', -2)).toEqual({ label: '↓2', tone: 'down' })
  })

  it('falls back to a neutral badge for unchanged or inconsistent data', () => {
    expect(trendBadge('same', 0)).toEqual({ label: '—', tone: 'same' })
    expect(trendBadge('up', null)).toEqual({ label: '—', tone: 'same' })
    expect(trendBadge('down', 1)).toEqual({ label: '—', tone: 'same' })
  })
})

describe('trendToneClass', () => {
  it('returns distinct colour classes per tone', () => {
    const classes = new Set(
      (['up', 'down', 'new', 'same'] as const).map(trendToneClass)
    )
    expect(classes.size).toBe(4)
    expect(trendToneClass('up')).toContain('emerald')
    expect(trendToneClass('down')).toContain('rose')
    expect(trendToneClass('new')).toContain('amber')
  })
})

describe('formatSnapshotDate', () => {
  it('formats ISO dates in Chinese', () => {
    expect(formatSnapshotDate('2026-10-22')).toBe('2026年10月22日')
    expect(formatSnapshotDate('2026-01-05')).toBe('2026年1月5日')
  })

  it('handles empty and unexpected values', () => {
    expect(formatSnapshotDate(null)).toBe('—')
    expect(formatSnapshotDate('')).toBe('—')
    expect(formatSnapshotDate('unknown')).toBe('unknown')
  })
})
