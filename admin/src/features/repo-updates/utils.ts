import type {
  RepoUpdateStatus,
  RepoUpdateStatusFilter,
  RepoUpdateSummary,
  RepoUpdateType,
  RepoUpdateTypeFilter,
} from './api'

export const REPO_UPDATE_STATUS_FILTERS: RepoUpdateStatusFilter[] = [
  'all',
  'unread',
  'read',
  'dismissed',
]

export const REPO_UPDATE_TYPE_FILTERS: RepoUpdateTypeFilter[] = [
  'all',
  'major',
  'release',
]

const TYPE_LABELS: Record<RepoUpdateType, string> = {
  major: '重大变更',
  release: '新版本',
}

const STATUS_LABELS: Record<RepoUpdateStatus, string> = {
  unread: '未读',
  read: '已读',
  dismissed: '已忽略',
}

export function updateTypeLabel(type: RepoUpdateType | string): string {
  return TYPE_LABELS[type as RepoUpdateType] ?? String(type)
}

export function updateStatusLabel(status: RepoUpdateStatus | string): string {
  return STATUS_LABELS[status as RepoUpdateStatus] ?? String(status)
}

export function updateStatusFilterLabel(filter: RepoUpdateStatusFilter): string {
  if (filter === 'unread') return '未读'
  if (filter === 'read') return '已读'
  if (filter === 'dismissed') return '已忽略'
  return '全部'
}

export function updateTypeFilterLabel(filter: RepoUpdateTypeFilter): string {
  if (filter === 'major') return '重大变更'
  if (filter === 'release') return '新版本'
  return '全部类型'
}

/** 时间展示：非法值显示破折号。 */
export function formatUpdateTime(value: string | null | undefined): string {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '—'
  return date.toLocaleString('zh-CN', { hour12: false })
}

export interface UpdateStatCard {
  title: string
  value: string
  hint: string
}

/** 页面顶部统计卡（纯函数，便于测试口径）。 */
export function updateStatCards(summary: RepoUpdateSummary): UpdateStatCard[] {
  return [
    {
      title: '全部提醒',
      value: String(summary.total),
      hint: `已读 ${summary.read} · 已忽略 ${summary.dismissed}`,
    },
    {
      title: '未读',
      value: String(summary.unread),
      hint: summary.unread > 0 ? '等待查看' : '已全部处理',
    },
    {
      title: '重大变更',
      value: String(summary.major),
      hint: `${summary.majorUnread} 条未读，建议优先处理`,
    },
    {
      title: '新版本',
      value: String(summary.release),
      hint: '常规 Release / Tag 更新',
    },
  ]
}

/** 列表空态文案。 */
export function emptyUpdateLabel(
  status: RepoUpdateStatusFilter,
  type: RepoUpdateTypeFilter
): string {
  if (status === 'all' && type === 'all') return '暂时没有收藏项目更新。'
  const parts: string[] = []
  if (status !== 'all') parts.push(updateStatusFilterLabel(status))
  if (type !== 'all') parts.push(updateTypeLabel(type))
  return `没有符合条件的${parts.join(' · ')}提醒。`
}
