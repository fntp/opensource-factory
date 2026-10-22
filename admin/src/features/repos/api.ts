import { apiFetch } from '@/lib/api'

/** 与 edge GET /api/repos 返回的 RepoItem 契约一致 */
export interface RepoItem {
  id: string
  fullName: string
  description: string | null
  language: string | null
  stars: number
  forks: number
  category: string | null
  tags: string[]
  updatedAt: string | null
  url: string
}

/** POST /api/sync 的返回 */
export interface SyncTriggerResult {
  status: string
  taskId?: string
  tracked?: boolean
  note?: string
}

/** 当前用户的仓库列表 */
export function fetchRepos(): Promise<RepoItem[]> {
  return apiFetch<RepoItem[]>('/api/repos')
}

/** 触发一次 GitHub 仓库同步 */
export function triggerSync(): Promise<SyncTriggerResult> {
  return apiFetch<SyncTriggerResult>('/api/sync', { method: 'POST' })
}
