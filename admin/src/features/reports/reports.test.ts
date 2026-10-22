import { describe, expect, it } from 'vitest'
import { MOCK_REPORTS, MOCK_REPORT_DETAILS } from './api'
import {
  filterReportsByKind,
  formatReportCount,
  formatReportDate,
  formatReportGeneratedAt,
  formatReportPeriod,
  pickDefaultReport,
  reportFilename,
  reportKindLabel,
  reportSourceLabel,
  reportStatCards,
  reportStatusLabel,
} from './utils'

describe('report labels', () => {
  it('maps kinds, statuses and sources to Chinese labels', () => {
    expect(reportKindLabel('weekly')).toBe('周报')
    expect(reportKindLabel('monthly')).toBe('月报')
    expect(reportStatusLabel('ready')).toBe('已生成')
    expect(reportStatusLabel('empty')).toBe('暂无数据')
    expect(reportSourceLabel('collection')).toBe('收藏')
    expect(reportSourceLabel('recommendation')).toBe('推荐')
    expect(reportSourceLabel('trending')).toBe('热榜')
  })
})

describe('report formatting', () => {
  it('formats counts with thousands separators', () => {
    expect(formatReportCount(1234567)).toBe('1,234,567')
    expect(formatReportCount(0)).toBe('0')
    expect(formatReportCount(Number.NaN)).toBe('—')
  })

  it('formats period dates without timezone drift', () => {
    expect(formatReportDate('2026-10-19')).toBe('2026-10-19')
    expect(formatReportDate('2026-10-19 08:00:00')).toBe('2026-10-19')
    expect(formatReportDate(null)).toBe('—')
    expect(formatReportDate('not-a-date')).toBe('—')
    expect(formatReportPeriod({ periodStart: '2026-10-19', periodEnd: '2026-10-25' })).toBe(
      '2026-10-19 ~ 2026-10-25'
    )
  })

  it('formats generatedAt and tolerates invalid values', () => {
    expect(formatReportGeneratedAt('2026-10-26T00:30:00.000Z')).not.toBe('—')
    expect(formatReportGeneratedAt('bad')).toBe('—')
    expect(formatReportGeneratedAt(null)).toBe('—')
  })

  it('builds download filenames from kind and period', () => {
    expect(reportFilename({ kind: 'weekly', periodStart: '2026-10-19' })).toBe(
      'openfactory-weekly-2026-10-19.md'
    )
  })
})

describe('report selection', () => {
  it('filters reports by kind and picks the first as default', () => {
    const weekly = filterReportsByKind(MOCK_REPORTS, 'weekly')
    expect(weekly).toHaveLength(1)
    expect(weekly[0]?.kind).toBe('weekly')
    expect(pickDefaultReport(MOCK_REPORTS, 'monthly')?.kind).toBe('monthly')
    expect(pickDefaultReport([], 'weekly')).toBeNull()
  })

  it('builds four stat cards with the expected values', () => {
    const report = MOCK_REPORT_DETAILS[MOCK_REPORTS[0]!.id]!
    const cards = reportStatCards(report.stats)
    expect(cards).toHaveLength(4)
    expect(cards[0]).toMatchObject({ title: '收藏总数', value: '24' })
    expect(cards[1]?.value).toBe('624,900')
    expect(cards[2]?.value).toBe('4 / 3')
    expect(cards[3]?.value).toBe('TypeScript')
  })
})

describe('mock report data', () => {
  it('keeps list and detail contracts aligned', () => {
    expect(MOCK_REPORTS.map((item) => item.kind)).toEqual(['weekly', 'monthly'])
    for (const summary of MOCK_REPORTS) {
      const detail = MOCK_REPORT_DETAILS[summary.id]
      expect(detail).toBeDefined()
      expect(detail?.title).toBe(summary.title)
      expect(detail?.sections).toHaveLength(4)
      expect(detail?.markdown).toContain(summary.title)
    }
  })
})
