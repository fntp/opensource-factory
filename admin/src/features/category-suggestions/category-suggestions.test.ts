import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  acceptCategorySuggestions,
  dismissCategorySuggestions,
  fetchCategorySuggestions,
  generateCategorySuggestions,
} from './api'
import {
  businessLineLabel,
  formatScore,
  generateSummary,
  groupByRepo,
  scoreTier,
  sourceLabel,
  statusLabel,
  summaryText,
  type CategorySuggestionItem,
} from './utils'

const mocks = vi.hoisted(() => ({
  apiFetch: vi.fn(),
  fetchWithFallback: vi.fn(),
}))

vi.mock('@/lib/api', () => ({
  apiFetch: mocks.apiFetch,
  fetchWithFallback: mocks.fetchWithFallback,
}))

function item(
  overrides: Partial<CategorySuggestionItem> = {}
): CategorySuggestionItem {
  return {
    id: 'cs_1',
    repoId: 'demo/pay',
    repoName: 'pay',
    repoUrl: 'https://github.com/demo/pay',
    summary: '',
    categoryName: '金融 / 支付',
    businessLine: 'fintech',
    score: 0.86,
    reason: '名称命中「payment」',
    evidence: 'payment gateway',
    status: 'pending',
    currentCategory: null,
    updatedAt: null,
    ...overrides,
  }
}

describe('分类建议工具函数', () => {
  it('置信度格式化为百分比并夹取 0~1', () => {
    expect(formatScore(0.8734)).toBe('87%')
    expect(formatScore(-1)).toBe('0%')
    expect(formatScore(2)).toBe('100%')
    expect(formatScore(Number.NaN)).toBe('0%')
  })

  it('分数档位 / 状态 / 来源 / 业务线标签', () => {
    expect(scoreTier(0.9)).toBe('high')
    expect(scoreTier(0.7)).toBe('medium')
    expect(scoreTier(0.5)).toBe('low')
    expect(statusLabel('pending')).toBe('待确认')
    expect(statusLabel('accepted')).toBe('已采纳')
    expect(statusLabel('dismissed')).toBe('已忽略')
    expect(statusLabel('all')).toBe('全部')
    expect(sourceLabel('vps')).toContain('VPS')
    expect(sourceLabel('mixed')).toContain('补扫')
    expect(sourceLabel('local')).toContain('兜底')
    expect(businessLineLabel('fintech')).toBe('金融 / 支付')
    expect(businessLineLabel('unknown-line')).toBe('unknown-line')
  })

  it('汇总文案与生成结果文案', () => {
    expect(
      summaryText({
        total: 4,
        pending: 3,
        accepted: 1,
        dismissed: 0,
        repos: 2,
        avgScore: 0.8,
      })
    ).toContain('待确认 3')
    expect(
      generateSummary({
        generatedAt: '',
        scanned: 10,
        suggested: 6,
        skipped: 4,
        source: 'vps',
      })
    ).toContain('扫描 10 个仓库')
  })

  it('按仓库聚合建议', () => {
    const groups = groupByRepo([
      item(),
      item({
        id: 'cs_2',
        categoryName: '后端与 API',
        businessLine: 'backend-api',
      }),
      item({ id: 'cs_3', repoId: 'demo/llm', repoName: 'llm' }),
    ])
    expect(groups).toHaveLength(2)
    expect(groups[0].items).toHaveLength(2)
    expect(groups[1].repoId).toBe('demo/llm')
  })
})

describe('分类建议 API 客户端', () => {
  beforeEach(() => {
    mocks.apiFetch.mockReset()
    mocks.fetchWithFallback.mockReset()
    mocks.apiFetch.mockResolvedValue({})
    mocks.fetchWithFallback.mockResolvedValue({
      items: [],
      summary: {},
      categories: [],
    })
  })

  it('列表按状态拼 query 并走演示数据兜底', async () => {
    await fetchCategorySuggestions('pending')
    expect(mocks.fetchWithFallback).toHaveBeenCalledWith(
      '/api/category-suggestions?status=pending',
      expect.anything()
    )
  })

  it('生成使用 POST 并携带参数', async () => {
    await generateCategorySuggestions({ limit: 100, perRepo: 2, minScore: 0.6 })
    expect(mocks.apiFetch).toHaveBeenCalledWith(
      '/api/category-suggestions/generate',
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ limit: 100, perRepo: 2, minScore: 0.6 }),
      }
    )
  })

  it('采纳与忽略携带 ids', async () => {
    await acceptCategorySuggestions(['cs_1'])
    expect(mocks.apiFetch).toHaveBeenCalledWith(
      '/api/category-suggestions/accept',
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ids: ['cs_1'] }),
      }
    )

    await dismissCategorySuggestions(['cs_2'])
    expect(mocks.apiFetch).toHaveBeenCalledWith(
      '/api/category-suggestions/dismiss',
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ids: ['cs_2'] }),
      }
    )
  })
})
