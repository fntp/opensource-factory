import { apiFetch, fetchWithFallback } from '@/lib/api'

export interface Tag {
  id: number
  name: string
  count: number
}

export interface TagListPayload {
  items: Tag[]
  total: number
}

export interface TagQuery {
  q?: string
  sort?: 'name' | 'count'
  order?: 'asc' | 'desc'
}

export interface MergeResult {
  sourceId: number
  target: Tag
  moved: number
  deduplicated: number
}

export interface DeleteResult {
  deleted: boolean
  id: number
  detached: number
}

export interface RecountResult {
  total: number
  mismatched: number
}

/** 演示数据：与分类页保持一致的标签集合 */
export const MOCK_TAGS: Tag[] = [
  { id: 1, name: 'LLM', count: 18 },
  { id: 2, name: 'Python', count: 16 },
  { id: 3, name: 'TypeScript', count: 14 },
  { id: 4, name: '框架', count: 12 },
  { id: 5, name: '组件', count: 9 },
  { id: 6, name: 'Rust', count: 7 },
  { id: 7, name: 'Go', count: 7 },
  { id: 8, name: '工具', count: 6 },
  { id: 9, name: '设计', count: 5 },
  { id: 10, name: '跨平台', count: 4 },
  { id: 11, name: '推荐', count: 3 },
  { id: 12, name: '资产', count: 2 },
]

/** 标签列表（失败时回退演示数据） */
export function fetchTags(query: TagQuery = {}): Promise<TagListPayload> {
  const params = new URLSearchParams()
  if (query.q?.trim()) params.set('q', query.q.trim())
  if (query.sort) params.set('sort', query.sort)
  if (query.order) params.set('order', query.order)
  const suffix = params.size > 0 ? `?${params.toString()}` : ''
  return fetchWithFallback<TagListPayload>(`/api/tags${suffix}`, {
    items: MOCK_TAGS,
    total: MOCK_TAGS.length,
  })
}

/** 新建标签 */
export function createTag(name: string): Promise<Tag> {
  return apiFetch<Tag>('/api/tags', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name }),
  })
}

/** 重命名标签 */
export function renameTag(id: number, name: string): Promise<Tag> {
  return apiFetch<Tag>(`/api/tags/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name }),
  })
}

/** 删除标签（服务端会解除仓库关联） */
export function deleteTag(id: number): Promise<DeleteResult> {
  return apiFetch<DeleteResult>(`/api/tags/${id}`, { method: 'DELETE' })
}

/** 合并标签：把 sourceId 的仓库关联迁移到 targetId，并删除源标签 */
export function mergeTags(
  sourceId: number,
  targetId: number
): Promise<MergeResult> {
  return apiFetch<MergeResult>(`/api/tags/${sourceId}/merge`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ targetId }),
  })
}

/** 全量重算标签引用计数 */
export function recountTags(): Promise<RecountResult> {
  return apiFetch<RecountResult>('/api/tags/recount', { method: 'POST' })
}
