import { describe, expect, it } from 'vitest'
import { MOCK_REPO_UPDATES, formatRepoUpdateBadge, mockRepoUpdatesPayload } from './api'
import {
  emptyUpdateLabel,
  formatUpdateTime,
  updateStatCards,
  updateStatusFilterLabel,
  updateStatusLabel,
  updateTypeFilterLabel,
  updateTypeLabel,
} from './utils'

describe('repo update labels', () => {
  it('maps types and statuses to Chinese labels', () => {
    expect(updateTypeLabel('major')).toBe('重大变更')
    expect(updateTypeLabel('release')).toBe('新版本')
    expect(updateStatusLabel('unread')).toBe('未读')
    expect(updateStatusLabel('read')).toBe('已读')
    expect(updateStatusLabel('dismissed')).toBe('已忽略')
    expect(updateStatusFilterLabel('all')).toBe('全部')
    expect(updateTypeFilterLabel('all')).toBe('全部类型')
  })
})

describe('repo update formatting', () => {
  it('formats times and tolerates invalid values', () => {
    expect(formatUpdateTime('2026-10-22T06:37:00.000Z')).not.toBe('—')
    expect(formatUpdateTime('bad')).toBe('—')
    expect(formatUpdateTime(null)).toBe('—')
  })

  it('formats unread badges', () => {
    expect(formatRepoUpdateBadge(0)).toBeNull()
    expect(formatRepoUpdateBadge(3)).toBe('3')
    expect(formatRepoUpdateBadge(120)).toBe('99+')
  })

  it('builds empty state labels', () => {
    expect(emptyUpdateLabel('all', 'all')).toBe('暂时没有收藏项目更新。')
    expect(emptyUpdateLabel('unread', 'major')).toContain('未读')
    expect(emptyUpdateLabel('unread', 'major')).toContain('重大变更')
  })
})

describe('repo update summary', () => {
  it('builds four stat cards from summary counts', () => {
    const payload = mockRepoUpdatesPayload()
    const cards = updateStatCards(payload.summary)
    expect(cards).toHaveLength(4)
    expect(cards[0]?.title).toBe('全部提醒')
    expect(cards[0]?.value).toBe(String(MOCK_REPO_UPDATES.length))
    expect(cards[2]?.title).toBe('重大变更')
    expect(cards[3]?.title).toBe('新版本')
  })

  it('filters mock data by status and type', () => {
    const unreadMajor = mockRepoUpdatesPayload({ status: 'unread', type: 'major' })
    expect(unreadMajor.items.every((item) => item.status === 'unread' && item.type === 'major')).toBe(
      true
    )
    expect(unreadMajor.summary.total).toBe(MOCK_REPO_UPDATES.length)

    const all = mockRepoUpdatesPayload()
    expect(all.items.every((item) => item.status !== 'dismissed')).toBe(true)
    expect(all.summary.dismissed).toBeGreaterThan(0)
  })
})
