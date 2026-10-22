import { apiFetch, fetchWithFallback } from '@/lib/api'

export type NotificationStatus = 'unread' | 'read' | 'dismissed'
export type NotificationFilter = 'all' | 'unread' | 'read'

export interface NotificationItem {
  id: string
  type: string
  title: string
  body: string | null
  url: string | null
  repoId: string | null
  recommendationId: string | null
  score: number | null
  reason: string | null
  language: string | null
  stars: number
  status: NotificationStatus
  createdAt: string
  readAt: string | null
}

export interface NotificationsPayload {
  items: NotificationItem[]
  total: number
  unread: number
  limit: number
  offset: number
  hasMore: boolean
}

export interface NotificationQuery {
  status?: NotificationFilter
  limit?: number
  offset?: number
}

function minutesAgo(minutes: number): string {
  return new Date(Date.now() - minutes * 60 * 1000).toISOString()
}

export const MOCK_NOTIFICATIONS: NotificationItem[] = [
  {
    id: 'mock-ntf-1',
    type: 'recommendation',
    title: 'huggingface/transformers',
    body: '最流行的预训练模型库，覆盖 NLP、视觉与多模态。',
    url: 'https://github.com/huggingface/transformers',
    repoId: 'huggingface/transformers',
    recommendationId: 'mock-rec-1',
    score: 0.95,
    reason: '与你收藏的 langchain、ollama 同属 AI/LLM 领域，语义相似度极高。',
    language: 'Python',
    stars: 136000,
    status: 'unread',
    createdAt: minutesAgo(18),
    readAt: null,
  },
  {
    id: 'mock-ntf-2',
    type: 'recommendation',
    title: 'modelcontextprotocol/servers',
    body: 'Model Context Protocol 官方服务器集合。',
    url: 'https://github.com/modelcontextprotocol/servers',
    repoId: 'modelcontextprotocol/servers',
    recommendationId: 'mock-rec-2',
    score: 0.92,
    reason: '与你关注的「AI 工具链」方向高度相关。',
    language: 'TypeScript',
    stars: 42800,
    status: 'unread',
    createdAt: minutesAgo(95),
    readAt: null,
  },
  {
    id: 'mock-ntf-3',
    type: 'recommendation',
    title: 'astral-sh/ruff',
    body: '极快的 Python linter 与格式化工具。',
    url: 'https://github.com/astral-sh/ruff',
    repoId: 'astral-sh/ruff',
    recommendationId: 'mock-rec-3',
    score: 0.88,
    reason: '你收藏了多个 Python 项目，ruff 是当前最流行的 Python 开发工具。',
    language: 'Rust',
    stars: 35200,
    status: 'read',
    createdAt: minutesAgo(60 * 26),
    readAt: minutesAgo(60 * 25),
  },
  {
    id: 'mock-ntf-4',
    type: 'system',
    title: '每日评估已完成',
    body: '今天的推荐已完成质量评估，通过门槛的项目已进入通知中心。',
    url: null,
    repoId: null,
    recommendationId: null,
    score: null,
    reason: null,
    language: null,
    stars: 0,
    status: 'unread',
    createdAt: minutesAgo(60 * 2),
    readAt: null,
  },
  {
    id: 'mock-ntf-5',
    type: 'recommendation',
    title: 'vercel/next.js',
    body: '用于生产环境的 React 全栈框架。',
    url: 'https://github.com/vercel/next.js',
    repoId: 'vercel/next.js',
    recommendationId: 'mock-rec-5',
    score: 0.85,
    reason: '你收藏的前端项目较多，推荐同领域热门框架。',
    language: 'TypeScript',
    stars: 127000,
    status: 'read',
    createdAt: minutesAgo(60 * 50),
    readAt: minutesAgo(60 * 49),
  },
]

/** 演示模式：按筛选与分页返回 mock 数据。 */
export function mockNotificationsPayload(
  query: NotificationQuery = {}
): NotificationsPayload {
  const status = query.status ?? 'all'
  const limit = Math.min(Math.max(query.limit ?? 20, 1), 100)
  const offset = Math.max(query.offset ?? 0, 0)
  const filtered = MOCK_NOTIFICATIONS.filter((item) => {
    if (status === 'all') return item.status !== 'dismissed'
    return item.status === status
  })
  return {
    items: filtered.slice(offset, offset + limit),
    total: filtered.length,
    unread: MOCK_NOTIFICATIONS.filter((item) => item.status === 'unread').length,
    limit,
    offset,
    hasMore: offset + limit < filtered.length,
  }
}

export function fetchNotifications(
  query: NotificationQuery = {}
): Promise<NotificationsPayload> {
  const params = new URLSearchParams()
  if (query.status) params.set('status', query.status)
  if (query.limit) params.set('limit', String(query.limit))
  if (query.offset) params.set('offset', String(query.offset))
  const suffix = params.toString() ? `?${params.toString()}` : ''
  return fetchWithFallback<NotificationsPayload>(
    `/api/notifications${suffix}`,
    mockNotificationsPayload(query)
  )
}

export function fetchUnreadCount(): Promise<{ unread: number }> {
  return fetchWithFallback<{ unread: number }>(
    '/api/notifications/unread-count',
    { unread: mockNotificationsPayload().unread }
  )
}

export function markNotificationRead(
  id: string
): Promise<{ id: string; status: 'read'; readAt: string | null }> {
  return apiFetch(`/api/notifications/${encodeURIComponent(id)}/read`, {
    method: 'POST',
  })
}

export function markAllNotificationsRead(): Promise<{
  updated: number
  unread: number
}> {
  return apiFetch('/api/notifications/read-all', { method: 'POST' })
}

export function dismissNotification(
  id: string
): Promise<{ id: string; status: 'dismissed' }> {
  return apiFetch(`/api/notifications/${encodeURIComponent(id)}/dismiss`, {
    method: 'POST',
  })
}

/** 未读数徽标文案：0 不显示，超过 99 显示 99+。 */
export function formatUnreadBadge(count: number): string | null {
  if (!Number.isFinite(count) || count <= 0) return null
  return count > 99 ? '99+' : String(Math.trunc(count))
}

/** 页面标题下的未读摘要。 */
export function formatUnreadLabel(count: number): string {
  if (!Number.isFinite(count) || count <= 0) return '全部已读'
  return `${Math.trunc(count)} 条未读`
}
