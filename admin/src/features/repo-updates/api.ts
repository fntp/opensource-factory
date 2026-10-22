import { apiFetch, fetchWithFallback } from '@/lib/api'

export type RepoUpdateType = 'release' | 'major'
export type RepoUpdateStatus = 'unread' | 'read' | 'dismissed'
export type RepoUpdateStatusFilter = 'all' | 'unread' | 'read' | 'dismissed'
export type RepoUpdateTypeFilter = 'all' | 'release' | 'major'

export interface RepoUpdateItem {
  id: string
  repoId: string
  repoName: string
  repoUrl: string
  type: RepoUpdateType
  version: string
  title: string
  summary: string
  url: string
  publishedAt: string | null
  detectedAt: string | null
  status: RepoUpdateStatus
  readAt: string | null
}

export interface RepoUpdateSummary {
  total: number
  unread: number
  read: number
  dismissed: number
  release: number
  major: number
  majorUnread: number
}

export interface RepoUpdatesPayload {
  items: RepoUpdateItem[]
  total: number
  limit: number
  offset: number
  hasMore: boolean
  summary: RepoUpdateSummary
}

export interface RepoUpdateQuery {
  status?: RepoUpdateStatusFilter
  type?: RepoUpdateTypeFilter
  limit?: number
  offset?: number
}

function hoursAgo(hours: number): string {
  return new Date(Date.now() - hours * 60 * 60 * 1000).toISOString()
}

export const MOCK_REPO_UPDATES: RepoUpdateItem[] = [
  {
    id: 'mock-update-1',
    repoId: 'langgenius/dify',
    repoName: 'langgenius/dify',
    repoUrl: 'https://github.com/langgenius/dify',
    type: 'major',
    version: 'v2.0.0',
    title: 'Dify 2.0：全新的 Agent 编排引擎',
    summary:
      '本版本重构了工作流引擎，插件协议与旧版不兼容，升级前请阅读迁移指南。新增多模态节点与团队空间。',
    url: 'https://github.com/langgenius/dify/releases/tag/v2.0.0',
    publishedAt: hoursAgo(20),
    detectedAt: hoursAgo(18),
    status: 'unread',
    readAt: null,
  },
  {
    id: 'mock-update-2',
    repoId: 'astral-sh/uv',
    repoName: 'astral-sh/uv',
    repoUrl: 'https://github.com/astral-sh/uv',
    type: 'release',
    version: 'v0.9.2',
    title: 'uv 0.9.2',
    summary: '修复 Windows 下的锁文件解析问题，提升依赖解析速度，新增 --no-build-isolation 选项。',
    url: 'https://github.com/astral-sh/uv/releases/tag/v0.9.2',
    publishedAt: hoursAgo(40),
    detectedAt: hoursAgo(38),
    status: 'unread',
    readAt: null,
  },
  {
    id: 'mock-update-3',
    repoId: 'vercel/next.js',
    repoName: 'vercel/next.js',
    repoUrl: 'https://github.com/vercel/next.js',
    type: 'release',
    version: 'v16.1.0',
    title: 'Next.js 16.1',
    summary: '新增缓存调试工具，改进 Turbopack 构建性能，修复若干 App Router 边界问题。',
    url: 'https://github.com/vercel/next.js/releases/tag/v16.1.0',
    publishedAt: hoursAgo(96),
    detectedAt: hoursAgo(94),
    status: 'read',
    readAt: hoursAgo(90),
  },
  {
    id: 'mock-update-4',
    repoId: 'open-webui/open-webui',
    repoName: 'open-webui/open-webui',
    repoUrl: 'https://github.com/open-webui/open-webui',
    type: 'major',
    version: 'v0.7.0',
    title: 'Open WebUI 0.7.0（breaking changes）',
    summary: '数据库结构升级，需先备份；旧版插件需要按新接口适配。新增多模型路由与审计日志。',
    url: 'https://github.com/open-webui/open-webui/releases/tag/v0.7.0',
    publishedAt: hoursAgo(120),
    detectedAt: hoursAgo(118),
    status: 'read',
    readAt: hoursAgo(110),
  },
  {
    id: 'mock-update-5',
    repoId: 'astral-sh/ruff',
    repoName: 'astral-sh/ruff',
    repoUrl: 'https://github.com/astral-sh/ruff',
    type: 'release',
    version: 'v0.14.3',
    title: 'Ruff 0.14.3',
    summary: '新增 6 条规则，修复格式化器在 f-string 中的边界情况。',
    url: 'https://github.com/astral-sh/ruff/releases/tag/v0.14.3',
    publishedAt: hoursAgo(160),
    detectedAt: hoursAgo(158),
    status: 'dismissed',
    readAt: hoursAgo(150),
  },
]

function summarize(items: RepoUpdateItem[]): RepoUpdateSummary {
  return {
    total: items.length,
    unread: items.filter((item) => item.status === 'unread').length,
    read: items.filter((item) => item.status === 'read').length,
    dismissed: items.filter((item) => item.status === 'dismissed').length,
    release: items.filter((item) => item.type === 'release').length,
    major: items.filter((item) => item.type === 'major').length,
    majorUnread: items.filter((item) => item.type === 'major' && item.status === 'unread').length,
  }
}

/** 演示模式：按筛选与分页返回 mock 数据。 */
export function mockRepoUpdatesPayload(
  query: RepoUpdateQuery = {}
): RepoUpdatesPayload {
  const status = query.status ?? 'all'
  const type = query.type ?? 'all'
  const limit = Math.min(Math.max(query.limit ?? 20, 1), 100)
  const offset = Math.max(query.offset ?? 0, 0)
  const filtered = MOCK_REPO_UPDATES.filter((item) => {
    const statusOk = status === 'all' ? item.status !== 'dismissed' : item.status === status
    const typeOk = type === 'all' || item.type === type
    return statusOk && typeOk
  })
  return {
    items: filtered.slice(offset, offset + limit),
    total: filtered.length,
    limit,
    offset,
    hasMore: offset + limit < filtered.length,
    summary: summarize(MOCK_REPO_UPDATES),
  }
}

export function fetchRepoUpdates(
  query: RepoUpdateQuery = {}
): Promise<RepoUpdatesPayload> {
  const params = new URLSearchParams()
  if (query.status) params.set('status', query.status)
  if (query.type) params.set('type', query.type)
  if (query.limit) params.set('limit', String(query.limit))
  if (query.offset) params.set('offset', String(query.offset))
  const suffix = params.toString() ? `?${params.toString()}` : ''
  return fetchWithFallback<RepoUpdatesPayload>(
    `/api/repo-updates${suffix}`,
    mockRepoUpdatesPayload(query)
  )
}

export function fetchRepoUpdateUnreadCount(): Promise<{
  unread: number
  majorUnread: number
}> {
  const summary = summarize(MOCK_REPO_UPDATES)
  return fetchWithFallback<{ unread: number; majorUnread: number }>(
    '/api/repo-updates/unread-count',
    { unread: summary.unread, majorUnread: summary.majorUnread }
  )
}

export function markRepoUpdateRead(
  id: string
): Promise<{ id: string; status: 'read'; readAt: string | null }> {
  return apiFetch(`/api/repo-updates/${encodeURIComponent(id)}/read`, {
    method: 'POST',
  })
}

export function markAllRepoUpdatesRead(): Promise<{
  updated: number
  unread: number
}> {
  return apiFetch('/api/repo-updates/read-all', { method: 'POST' })
}

export function dismissRepoUpdate(
  id: string
): Promise<{ id: string; status: 'dismissed' }> {
  return apiFetch(`/api/repo-updates/${encodeURIComponent(id)}/dismiss`, {
    method: 'POST',
  })
}

export function scanRepoUpdates(): Promise<{
  status: string
  taskId?: string | null
  note?: string
}> {
  return apiFetch('/api/repo-updates/scan', { method: 'POST' })
}

/** 未读数徽标文案：0 不显示，超过 99 显示 99+。 */
export function formatRepoUpdateBadge(count: number): string | null {
  if (!Number.isFinite(count) || count <= 0) return null
  return count > 99 ? '99+' : String(Math.trunc(count))
}
