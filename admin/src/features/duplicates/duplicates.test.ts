import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  dismissDuplicate,
  fetchDismissedDuplicates,
  restoreDuplicate,
  scanDuplicates,
} from './api'
import {
  actionLabel,
  fieldLabel,
  formatConfidence,
  formatFieldValue,
  kindLabel,
  memberRoleLabel,
  modeLabel,
  scanSummary,
  scopeLabel,
  sourceLabel,
} from './utils'

const mocks = vi.hoisted(() => ({ apiFetch: vi.fn() }))

vi.mock('@/lib/api', () => ({
  apiFetch: mocks.apiFetch,
}))

describe('重复检测工具函数', () => {
  it('置信度格式化为百分比并夹取 0~1', () => {
    expect(formatConfidence(0.8734)).toBe('87%')
    expect(formatConfidence(-1)).toBe('0%')
    expect(formatConfidence(2)).toBe('100%')
    expect(formatConfidence(Number.NaN)).toBe('0%')
  })

  it('类型 / 范围 / 模式 / 来源标签', () => {
    expect(kindLabel('exact')).toContain('地址')
    expect(kindLabel('name')).toContain('名称')
    expect(kindLabel('semantic')).toContain('语义')
    expect(kindLabel('mixed')).toContain('混合')
    expect(scopeLabel('my')).toBe('我的仓库')
    expect(scopeLabel('trending')).toBe('每日热榜')
    expect(scopeLabel('all')).toBe('全部来源')
    expect(modeLabel('vps')).toContain('VPS')
    expect(modeLabel('hybrid')).toContain('补扫')
    expect(modeLabel('local')).toContain('兜底')
    expect(sourceLabel('my')).toBe('我的仓库')
    expect(sourceLabel('trending')).toBe('每日热榜')
    expect(memberRoleLabel('canonical')).toBe('保留')
    expect(memberRoleLabel('merge')).toBe('合并')
    expect(actionLabel('merge')).toContain('合并')
    expect(actionLabel('review')).toContain('复核')
  })

  it('字段名与建议值展示', () => {
    expect(fieldLabel('description')).toBe('项目简介')
    expect(fieldLabel('readmeSummary')).toBe('README 摘要')
    expect(fieldLabel('techStack')).toBe('技术栈')
    expect(fieldLabel('unknown')).toBe('unknown')
    expect(formatFieldValue(['NestJS', 'React'])).toBe('NestJS、React')
    expect(formatFieldValue(2100)).toBe('2100')
    expect(formatFieldValue(null)).toBe('—')
  })

  it('扫描概览包含仓库数与簇数', () => {
    expect(
      scanSummary({
        scanId: 'x',
        scope: 'all',
        mode: 'vps',
        count: 3,
        scanned: 128,
        compared: 8128,
        tookMs: 10,
        dismissedCount: 0,
        thresholds: {
          minScore: 0.7,
          nameThreshold: 0.86,
          descriptionThreshold: 0.75,
          vectorThreshold: 0.88,
          maxRepos: 500,
          maxClusters: 50,
        },
        clusters: [],
      })
    ).toContain('128')
  })
})

describe('重复检测 API 客户端', () => {
  beforeEach(() => {
    mocks.apiFetch.mockReset()
    mocks.apiFetch.mockResolvedValue({})
  })

  it('扫描使用 POST 并携带范围 / 阈值', async () => {
    await scanDuplicates({ scope: 'my', minScore: 0.8, maxClusters: 10 })
    expect(mocks.apiFetch).toHaveBeenCalledWith('/api/duplicates/scan', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ scope: 'my', minScore: 0.8, maxClusters: 10 }),
    })
  })

  it('忽略携带簇 id 与成员', async () => {
    mocks.apiFetch.mockResolvedValue({ dismissed: true, clusterId: 'dup_1' })
    await dismissDuplicate({
      clusterId: 'dup_1',
      repoIds: ['my:demo/a', 'trending:demo/a'],
      reason: '误报',
    })
    expect(mocks.apiFetch).toHaveBeenCalledWith('/api/duplicates/dismiss', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        clusterId: 'dup_1',
        repoIds: ['my:demo/a', 'trending:demo/a'],
        reason: '误报',
      }),
    })
  })

  it('已忽略列表使用 GET', async () => {
    mocks.apiFetch.mockResolvedValue({ count: 0, items: [] })
    await fetchDismissedDuplicates()
    expect(mocks.apiFetch).toHaveBeenCalledWith('/api/duplicates/dismissed')
  })

  it('恢复接口对 clusterId 做 URL 编码', async () => {
    mocks.apiFetch.mockResolvedValue({ removed: true, clusterId: 'dup/1' })
    await restoreDuplicate('dup/1')
    expect(mocks.apiFetch).toHaveBeenCalledWith(
      '/api/duplicates/dismiss/dup%2F1',
      { method: 'DELETE' }
    )
  })

  it('接口失败时扫描回退演示数据', async () => {
    mocks.apiFetch.mockRejectedValue(new Error('offline'))
    const result = await scanDuplicates({ scope: 'trending' })
    expect(result.scope).toBe('trending')
    expect(result.clusters.length).toBeGreaterThan(0)
  })
})
