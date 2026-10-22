import { beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({ apiFetch: vi.fn() }))

vi.mock('@/lib/api', () => ({
  apiFetch: mocks.apiFetch,
  DEMO_MODE: false,
}))

import {
  dismissRecommendation,
  fetchRecommendationStats,
  fetchRecommendations,
  saveRecommendation,
  trackRecommendationClick,
} from './api'

describe('推荐 API 客户端', () => {
  beforeEach(() => {
    mocks.apiFetch.mockReset()
    mocks.apiFetch.mockResolvedValue([])
  })

  it('按状态拉取推荐列表', async () => {
    await fetchRecommendations('saved')
    expect(mocks.apiFetch).toHaveBeenCalledWith(
      '/api/recommendations?status=saved&limit=50'
    )
  })

  it('拉取推荐统计', async () => {
    await fetchRecommendationStats()
    expect(mocks.apiFetch).toHaveBeenCalledWith('/api/recommendations/stats')
  })

  it('收藏使用 POST', async () => {
    await saveRecommendation('rec/1')
    expect(mocks.apiFetch).toHaveBeenCalledWith(
      '/api/recommendations/rec%2F1/save',
      { method: 'POST' }
    )
  })

  it('忽略携带原因', async () => {
    await dismissRecommendation('rec-1', '技术栈不匹配')
    expect(mocks.apiFetch).toHaveBeenCalledWith(
      '/api/recommendations/rec-1/dismiss',
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reason: '技术栈不匹配' }),
      }
    )
  })

  it('点击反馈使用 POST', async () => {
    await trackRecommendationClick('rec-1')
    expect(mocks.apiFetch).toHaveBeenCalledWith(
      '/api/recommendations/rec-1/click',
      { method: 'POST' }
    )
  })
})
