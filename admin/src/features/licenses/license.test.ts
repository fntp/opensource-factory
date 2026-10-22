import { describe, expect, it } from 'vitest'
import {
  MOCK_LICENSE_CATALOG,
  MOCK_LICENSE_SUMMARY,
  type LicenseInfo,
} from './api'
import {
  formatLicenseCheckedAt,
  licenseBadgeLabel,
  licenseCoverage,
  licenseShare,
  licenseSourceLabel,
  licenseToneClass,
  riskLabel,
  riskToneClass,
} from './utils'

const mit: LicenseInfo = {
  spdxId: 'MIT',
  name: 'MIT License',
  category: 'permissive',
  categoryLabel: '宽松许可',
  riskLevel: 'low',
  riskLabel: '低风险',
  summary: '允许商用、修改、再分发与闭源衍生。',
  obligations: ['保留版权声明'],
  warnings: [],
  source: 'github',
  checkedAt: '2026-10-22T08:00:00',
}

describe('license helpers', () => {
  it('maps risk labels and tones', () => {
    expect(riskLabel('low')).toBe('低风险')
    expect(riskLabel('medium')).toBe('中风险')
    expect(riskLabel('high')).toBe('高风险')
    expect(riskLabel('unknown')).toBe('未知风险')
    expect(riskToneClass('high')).toContain('red')
    expect(licenseToneClass(mit)).toContain('emerald')
    expect(licenseToneClass(null)).toContain('slate')
  })

  it('formats badge labels and sources', () => {
    expect(licenseBadgeLabel(mit)).toBe('MIT')
    expect(licenseBadgeLabel(null)).toBe('未识别')
    expect(licenseBadgeLabel({ ...mit, spdxId: null })).toBe('未识别')
    expect(licenseSourceLabel('github')).toBe('GitHub 元数据')
    expect(licenseSourceLabel('readme')).toBe('README 识别')
    expect(licenseSourceLabel('none')).toBe('无许可证')
    expect(licenseSourceLabel(null)).toBe('尚未识别')
  })

  it('formats checked time and computes coverage', () => {
    expect(formatLicenseCheckedAt('2026-10-22T08:00:00')).toBe(
      '2026-10-22 08:00'
    )
    expect(formatLicenseCheckedAt(null)).toBe('尚未识别')
    expect(licenseCoverage(MOCK_LICENSE_SUMMARY)).toBe(89)
    expect(licenseCoverage({ ...MOCK_LICENSE_SUMMARY, total: 0 })).toBe(0)
    expect(licenseShare(2, 8)).toBe(25)
    expect(licenseShare(2, 0)).toBe(0)
  })

  it('keeps demo catalog and summary consistent', () => {
    const spdxIds = MOCK_LICENSE_CATALOG.licenses.map((item) => item.spdxId)
    expect(spdxIds).toContain('MIT')
    expect(spdxIds).toContain('AGPL-3.0')
    expect(MOCK_LICENSE_CATALOG.categories.map((item) => item.key)).toContain(
      'strong-copyleft'
    )

    const summary = MOCK_LICENSE_SUMMARY
    expect(summary.known + summary.unknown).toBe(summary.total)
    expect(
      summary.riskCounts.low +
        summary.riskCounts.medium +
        summary.riskCounts.high +
        summary.riskCounts.unknown
    ).toBe(summary.total)
    expect(summary.licenses.reduce((sum, item) => sum + item.count, 0)).toBe(
      summary.total
    )
  })
})
