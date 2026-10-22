import { describe, expect, it } from 'vitest'
import {
  buildDemoPersonalData,
  DEMO_PRIVACY_POLICY,
  formatPolicyDate,
  parseFileName,
  personalDataFileName,
  retentionText,
} from './utils'

describe('隐私与数据工具函数', () => {
  it('保留期文案覆盖定期与账号删除两类', () => {
    const account = DEMO_PRIVACY_POLICY.retention.find(
      (item) => item.key === 'account'
    )
    const recommendation = DEMO_PRIVACY_POLICY.retention.find(
      (item) => item.key === 'recommendations'
    )
    expect(account && retentionText(account)).toBe('保留至账号删除')
    expect(recommendation && retentionText(recommendation)).toBe(
      '未收藏 90 天 / 已收藏 365 天'
    )
  })

  it('策略日期格式化为 UTC 日期', () => {
    expect(formatPolicyDate('2026-10-22T00:00:00.000Z')).toBe('2026-10-22')
    expect(formatPolicyDate('not-a-date')).toBe('not-a-date')
  })

  it('解析 Content-Disposition 的 filename 与 filename*', () => {
    expect(
      parseFileName(
        'attachment; filename="openfactory-personal-data-2026-10-22.json"',
        'fallback.json'
      )
    ).toBe('openfactory-personal-data-2026-10-22.json')
    expect(
      parseFileName(
        "attachment; filename*=UTF-8''openfactory-%E6%95%B0%E6%8D%AE.json",
        'fallback.json'
      )
    ).toBe('openfactory-数据.json')
    expect(parseFileName(null, 'fallback.json')).toBe('fallback.json')
  })

  it('个人数据文件名使用 UTC 日期', () => {
    expect(personalDataFileName('2026-10-22T23:59:59.000Z')).toBe(
      'openfactory-personal-data-2026-10-22.json'
    )
  })

  it('演示导出结构带 schemaVersion 与策略版本', () => {
    const parsed = JSON.parse(
      buildDemoPersonalData('2026-10-22T10:00:00.000Z')
    ) as {
      schemaVersion: string
      policyVersion: string
      subject: { login: string }
    }
    expect(parsed.schemaVersion).toBe('openfactory.personal-data.v1')
    expect(parsed.policyVersion).toBe(DEMO_PRIVACY_POLICY.version)
    expect(parsed.subject.login).toBe('demo')
  })

  it('策略包含访问、删除、更正与限制处理四项权利', () => {
    expect(DEMO_PRIVACY_POLICY.rights.map((right) => right.key)).toEqual([
      'access',
      'erasure',
      'rectification',
      'restriction',
    ])
  })
})
