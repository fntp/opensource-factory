import { describe, expect, it } from 'vitest'
import {
  MOCK_NOTIFICATIONS,
  formatUnreadBadge,
  formatUnreadLabel,
  mockNotificationsPayload,
} from './api'

describe('formatUnreadBadge', () => {
  it('hides the badge when there is nothing unread', () => {
    expect(formatUnreadBadge(0)).toBeNull()
    expect(formatUnreadBadge(-3)).toBeNull()
    expect(formatUnreadBadge(Number.NaN)).toBeNull()
  })

  it('shows the count and caps at 99+', () => {
    expect(formatUnreadBadge(1)).toBe('1')
    expect(formatUnreadBadge(42)).toBe('42')
    expect(formatUnreadBadge(99)).toBe('99')
    expect(formatUnreadBadge(100)).toBe('99+')
  })
})

describe('formatUnreadLabel', () => {
  it('summarises the unread count', () => {
    expect(formatUnreadLabel(0)).toBe('全部已读')
    expect(formatUnreadLabel(3)).toBe('3 条未读')
  })
})

describe('mockNotificationsPayload', () => {
  const unread = MOCK_NOTIFICATIONS.filter((item) => item.status === 'unread').length

  it('returns every non-dismissed notification by default', () => {
    const payload = mockNotificationsPayload()
    expect(payload.total).toBe(MOCK_NOTIFICATIONS.length)
    expect(payload.unread).toBe(unread)
    expect(payload.hasMore).toBe(false)
  })

  it('filters by unread and read', () => {
    const unreadPayload = mockNotificationsPayload({ status: 'unread' })
    expect(unreadPayload.items.every((item) => item.status === 'unread')).toBe(true)
    expect(unreadPayload.total).toBe(unread)

    const readPayload = mockNotificationsPayload({ status: 'read' })
    expect(readPayload.items.every((item) => item.status === 'read')).toBe(true)
    expect(readPayload.total).toBe(MOCK_NOTIFICATIONS.length - unread)
  })

  it('paginates and reports hasMore', () => {
    const first = mockNotificationsPayload({ limit: 2, offset: 0 })
    expect(first.items).toHaveLength(2)
    expect(first.hasMore).toBe(true)

    const last = mockNotificationsPayload({
      limit: 2,
      offset: first.total - 1,
    })
    expect(last.items).toHaveLength(1)
    expect(last.hasMore).toBe(false)
  })

  it('clamps invalid limit and offset values', () => {
    const payload = mockNotificationsPayload({ limit: 0, offset: -10 })
    expect(payload.limit).toBe(1)
    expect(payload.offset).toBe(0)
    expect(payload.items).toHaveLength(1)
  })
})
