import { beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({ apiFetch: vi.fn() }))

vi.mock('@/lib/api', () => ({
  apiFetch: mocks.apiFetch,
  DEMO_MODE: false,
}))

import { applyRerank, fetchRerankPreview } from './api'

describe('精排 API 客户端', () => {
  beforeEach(() => {
    mocks.apiFetch.mockReset()
    mocks.apiFetch.mockResolvedValue({ status: 'ok', items: [] })
  })

  it('预览走 POST 并携带参数', async () => {
    await fetchRerankPreview({ topK: 10, mmrLambda: 0.6 })
    expect(mocks.apiFetch).toHaveBeenCalledWith('/api/rerank/preview', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ topK: 10, mmrLambda: 0.6 }),
    })
  })

  it('应用走 POST /apply', async () => {
    await applyRerank({ topK: 20 })
    expect(mocks.apiFetch).toHaveBeenCalledWith('/api/rerank/apply', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ topK: 20 }),
    })
  })
})
