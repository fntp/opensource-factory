import { describe, expect, it } from 'vitest'
import {
  MOCK_MONITORING_OVERVIEW,
  activeAlerts,
  checkLabel,
  formatMb,
  formatPercent,
  severityLabel,
  statusBadgeClass,
  statusLabel,
  usageBarClass,
} from './api'

describe('formatMb', () => {
  it('formats megabytes and switches to gigabytes', () => {
    expect(formatMb(0)).toBe('0 MB')
    expect(formatMb(512)).toBe('512 MB')
    expect(formatMb(1023)).toBe('1023 MB')
    expect(formatMb(1024)).toBe('1.0 GB')
    expect(formatMb(15360)).toBe('15.0 GB')
  })

  it('handles missing or invalid values', () => {
    expect(formatMb(null)).toBe('—')
    expect(formatMb(undefined)).toBe('—')
    expect(formatMb(Number.NaN)).toBe('—')
  })
})

describe('formatPercent', () => {
  it('keeps one decimal by default and supports custom precision', () => {
    expect(formatPercent(0)).toBe('0.0%')
    expect(formatPercent(88.94)).toBe('88.9%')
    expect(formatPercent(3.14159, 2)).toBe('3.14%')
    expect(formatPercent(Number.NaN)).toBe('—')
  })
})

describe('status labels and tones', () => {
  it('maps every status to Chinese text', () => {
    expect(statusLabel('ok')).toBe('正常')
    expect(statusLabel('warning')).toBe('预警')
    expect(statusLabel('critical')).toBe('严重')
    expect(statusLabel('unknown')).toBe('未知')
  })

  it('maps severities to Chinese text', () => {
    expect(severityLabel('critical')).toBe('严重')
    expect(severityLabel('warning')).toBe('预警')
    expect(severityLabel('info')).toBe('提示')
  })

  it('returns distinct badge and progress colors', () => {
    expect(statusBadgeClass('ok')).toContain('emerald')
    expect(statusBadgeClass('warning')).toContain('amber')
    expect(statusBadgeClass('critical')).toContain('red')
    expect(usageBarClass(10)).toContain('emerald')
    expect(usageBarClass(90)).toContain('amber')
    expect(usageBarClass(100)).toContain('red')
  })
})

describe('activeAlerts', () => {
  it('filters resolved alerts', () => {
    const alerts = MOCK_MONITORING_OVERVIEW.vps?.alerts ?? []
    expect(alerts.length).toBe(2)
    expect(activeAlerts(alerts)).toHaveLength(1)
  })
})

describe('checkLabel', () => {
  it('translates known checks and falls back to raw names', () => {
    expect(checkLabel('database')).toBe('数据库')
    expect(checkLabel('runtime_home')).toBe('运行目录')
    expect(checkLabel('redis')).toBe('Redis')
    expect(checkLabel('custom_check')).toBe('custom_check')
  })
})

describe('MOCK_MONITORING_OVERVIEW', () => {
  it('keeps totals consistent with daily metrics', () => {
    const workers = MOCK_MONITORING_OVERVIEW.workers
    expect(workers).not.toBeNull()
    const total = workers?.daily.reduce((sum, item) => sum + item.requests, 0)
    expect(workers?.totals.requests).toBe(total)
    expect(MOCK_MONITORING_OVERVIEW.status).toBe('warning')
  })

  it('includes VPS resources at the 4G / 15G red lines', () => {
    const resources = MOCK_MONITORING_OVERVIEW.vps?.resources
    expect(resources?.memory.budgetMb).toBe(4096)
    expect(resources?.disk.budgetMb).toBe(15360)
    expect(resources?.memory.percent).toBeGreaterThan(87.5)
  })
})
