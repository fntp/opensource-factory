import { apiFetch, fetchWithFallback } from '@/lib/api'

/** 任务进度快照（与 edge / VPS 契约一致，camelCase） */
export interface TaskProgress {
  phase?: string
  page?: number
  pagesTotal?: number | null
  fetched?: number
  total?: number | null
  percent?: number
  done?: boolean
}

export interface SyncTask {
  taskId: string
  type: string
  status: string
  progress: TaskProgress | null
  result: Record<string, unknown> | string | null
  error: string | null
  createdAt: string
  updatedAt: string
  finishedAt: string | null
  stale?: boolean
}

export interface SyncTriggerResult {
  status: string
  taskId?: string
  tracked?: boolean
  note?: string
}

const MOCK_CREATED = '2026-10-22T04:00:00.000Z'

export const MOCK_TASKS: SyncTask[] = [
  {
    taskId: 'mock-task-success-0001',
    type: 'sync',
    status: 'success',
    progress: {
      phase: 'done',
      page: 3,
      pagesTotal: 3,
      fetched: 128,
      total: 128,
      percent: 100,
      done: true,
    },
    result: {
      status: 'ok',
      total: 128,
      created: 12,
      updated: 116,
      unchanged: 0,
    },
    error: null,
    createdAt: MOCK_CREATED,
    updatedAt: '2026-10-22T04:01:12.000Z',
    finishedAt: '2026-10-22T04:01:12.000Z',
  },
  {
    taskId: 'mock-task-progress-0002',
    type: 'sync',
    status: 'progress',
    progress: {
      phase: 'fetch',
      page: 2,
      pagesTotal: 5,
      fetched: 200,
      total: null,
      percent: 40,
      done: false,
    },
    result: null,
    error: null,
    createdAt: '2026-10-22T04:05:00.000Z',
    updatedAt: '2026-10-22T04:05:20.000Z',
    finishedAt: null,
  },
  {
    taskId: 'mock-task-failure-0003',
    type: 'sync',
    status: 'failure',
    progress: {
      phase: 'fetch',
      page: 1,
      pagesTotal: 4,
      fetched: 100,
      total: null,
      percent: 25,
      done: false,
    },
    result: {
      status: 'error',
      total: 100,
      created: 7,
      updated: 93,
      partial: true,
    },
    error: 'GitHub API 限流，已保留部分同步结果',
    createdAt: '2026-10-21T09:00:00.000Z',
    updatedAt: '2026-10-21T09:02:30.000Z',
    finishedAt: '2026-10-21T09:02:30.000Z',
  },
]

const STATUS_LABELS: Record<string, string> = {
  pending: '等待中',
  started: '运行中',
  progress: '同步中',
  success: '已完成',
  failure: '失败',
  unknown: '未知',
}

const TYPE_LABELS: Record<string, string> = {
  sync: '仓库同步',
  'sync-starred': 'Starred 全量同步',
}

export function taskStatusLabel(status: string): string {
  return STATUS_LABELS[status] ?? STATUS_LABELS.unknown
}

export function taskTypeLabel(type: string): string {
  return TYPE_LABELS[type] ?? type
}

export function isTaskActive(status: string): boolean {
  return status !== 'success' && status !== 'failure'
}

/** 进度百分比：优先用任务快照，成功任务兜底 100 */
export function taskProgressPercent(task: SyncTask): number {
  const raw = task.progress?.percent
  if (typeof raw === 'number' && Number.isFinite(raw)) {
    return Math.max(0, Math.min(100, Math.round(raw)))
  }
  return task.status === 'success' ? 100 : 0
}

function parseTime(value: string | null): number | null {
  if (!value) return null
  // D1 CURRENT_TIMESTAMP 形如 "2026-10-22 04:00:00"（UTC），补 Z 避免被当作本地时间
  const normalized = /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/.test(value)
    ? `${value.replace(' ', 'T')}Z`
    : value
  const ts = Date.parse(normalized)
  return Number.isFinite(ts) ? ts : null
}

/** 任务耗时（创建 → 结束；运行中按最近刷新时间） */
export function taskDuration(task: SyncTask): string {
  const start = parseTime(task.createdAt)
  const end = parseTime(task.finishedAt ?? task.updatedAt)
  if (start == null || end == null || end < start) return '—'
  const seconds = Math.round((end - start) / 1000)
  if (seconds < 60) return `${seconds}s`
  const minutes = Math.floor(seconds / 60)
  const rest = seconds % 60
  return rest ? `${minutes}m ${rest}s` : `${minutes}m`
}

export function formatTaskTime(value: string | null): string {
  const ts = parseTime(value)
  if (ts == null) return '—'
  return new Date(ts).toLocaleString('zh-CN', { hour12: false })
}

/** 结果摘要：优先展示错误，其次展示同步计数 */
export function taskResultSummary(task: SyncTask): string {
  if (task.error) return task.error
  const result = task.result
  if (!result) return '—'
  if (typeof result === 'string') return result
  if (result.status === 'skipped') return String(result.reason ?? '已跳过')
  if (typeof result.total === 'number') {
    const parts = [`共 ${result.total} 个仓库`]
    if (typeof result.created === 'number') parts.push(`新增 ${result.created}`)
    if (typeof result.updated === 'number') parts.push(`更新 ${result.updated}`)
    if (typeof result.unchanged === 'number')
      parts.push(`未变化 ${result.unchanged}`)
    return parts.join(' · ')
  }
  return JSON.stringify(result)
}

export async function fetchTasks(): Promise<SyncTask[]> {
  const data = await fetchWithFallback<{ tasks: SyncTask[] }>(
    '/api/tasks?limit=20',
    {
      tasks: MOCK_TASKS,
    }
  )
  return data.tasks
}

export function fetchTask(taskId: string): Promise<SyncTask> {
  return fetchWithFallback<SyncTask>(
    `/api/tasks/${encodeURIComponent(taskId)}`,
    MOCK_TASKS.find((task) => task.taskId === taskId) ?? MOCK_TASKS[0]
  )
}

export function triggerSync(): Promise<SyncTriggerResult> {
  return apiFetch<SyncTriggerResult>('/api/sync', { method: 'POST' })
}
