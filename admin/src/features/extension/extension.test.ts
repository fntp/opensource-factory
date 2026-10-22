import { describe, expect, it } from 'vitest'
import {
  DEMO_TOKENS,
  EXTENSION_INSTALL_STEPS,
  formatTokenDate,
  tokenStatusLabel,
  tokenUsageLabel,
  type ExtensionToken,
} from './api'

describe('extension token helpers', () => {
  it('格式化令牌时间，空值给出占位文案', () => {
    expect(formatTokenDate(null)).toBe('尚未使用')
    expect(formatTokenDate('not-a-date')).toBe('—')
    expect(formatTokenDate('2026-10-22T08:05:00.000Z')).toMatch(
      /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$/
    )
  })

  it('映射令牌状态', () => {
    expect(tokenStatusLabel('active')).toBe('有效')
    expect(tokenStatusLabel('revoked')).toBe('已撤销')
  })

  it('根据最近使用与撤销状态生成说明', () => {
    const active: ExtensionToken = {
      ...DEMO_TOKENS[0],
      lastUsedAt: null,
    }
    expect(tokenUsageLabel(active)).toBe('尚未使用')

    const revoked: ExtensionToken = {
      ...DEMO_TOKENS[0],
      status: 'revoked',
      revokedAt: '2026-10-20T10:00:00.000Z',
    }
    expect(tokenUsageLabel(revoked)).toMatch(/^撤销于 \d{4}-\d{2}-\d{2}/)
  })

  it('安装步骤覆盖加载、令牌与使用', () => {
    expect(EXTENSION_INSTALL_STEPS).toHaveLength(4)
    expect(EXTENSION_INSTALL_STEPS.join('')).toContain('chrome://extensions')
    expect(EXTENSION_INSTALL_STEPS.join('')).toContain('Ctrl+Shift+O')
  })
})
