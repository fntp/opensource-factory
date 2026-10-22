import type { RepoItem } from './api'

export type RepoSortField = 'stars' | 'updated' | 'created' | 'name'
export type SortOrder = 'asc' | 'desc'
export type StarRange = 'all' | 'lt1k' | '1k-10k' | '10k-50k' | 'gte50k'
export type TimeRange = 'all' | '7d' | '30d' | '90d' | '1y'

export interface RepoFilters {
  keyword: string
  categoryId: string
  tagNames: string[]
  languages: string[]
  starRange: StarRange
  timeRange: TimeRange
  sort: RepoSortField
  order: SortOrder
}

export const DEFAULT_REPO_FILTERS: RepoFilters = {
  keyword: '',
  categoryId: '',
  tagNames: [],
  languages: [],
  starRange: 'all',
  timeRange: 'all',
  sort: 'stars',
  order: 'desc',
}

export const STAR_RANGE_OPTIONS: Array<{ value: StarRange; label: string }> = [
  { value: 'all', label: '全部 Star' },
  { value: 'lt1k', label: '少于 1k' },
  { value: '1k-10k', label: '1k – 10k' },
  { value: '10k-50k', label: '10k – 50k' },
  { value: 'gte50k', label: '50k 以上' },
]

export const TIME_RANGE_OPTIONS: Array<{ value: TimeRange; label: string }> = [
  { value: 'all', label: '全部时间' },
  { value: '7d', label: '近 7 天' },
  { value: '30d', label: '近 30 天' },
  { value: '90d', label: '近 90 天' },
  { value: '1y', label: '近一年' },
]

export const SORT_OPTIONS: Array<{ value: RepoSortField; label: string }> = [
  { value: 'stars', label: 'Star 数' },
  { value: 'updated', label: '最近更新' },
  { value: 'created', label: '收录时间' },
  { value: 'name', label: '名称' },
]

/** Star 预设区间 → 查询参数边界（无间隙、无重叠）。 */
export function starRangeToBounds(range: StarRange): {
  min?: number
  max?: number
} {
  switch (range) {
    case 'lt1k':
      return { max: 999 }
    case '1k-10k':
      return { min: 1000, max: 9999 }
    case '10k-50k':
      return { min: 10000, max: 49999 }
    case 'gte50k':
      return { min: 50000 }
    case 'all':
    default:
      return {}
  }
}

const TIME_RANGE_DAYS: Record<Exclude<TimeRange, 'all'>, number> = {
  '7d': 6,
  '30d': 29,
  '90d': 89,
  '1y': 364,
}

/** 时间预设 → 起始日期（YYYY-MM-DD，UTC；含当天）。 */
export function timeRangeToAfter(
  range: TimeRange,
  now: Date = new Date()
): string | undefined {
  if (range === 'all') return undefined
  const start = new Date(
    Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate())
  )
  start.setUTCDate(start.getUTCDate() - TIME_RANGE_DAYS[range])
  return start.toISOString().slice(0, 10)
}

/** 生成 GET /api/repos 查询串；默认排序不写入，便于与 facet 查询复用缓存。 */
export function buildReposQuery(
  filters: RepoFilters,
  now: Date = new Date()
): string {
  const params = new URLSearchParams()
  const keyword = filters.keyword.trim()
  if (keyword) params.set('q', keyword)
  if (filters.categoryId) params.set('categoryId', filters.categoryId)
  if (filters.tagNames.length > 0)
    params.set('tags', filters.tagNames.join(','))
  if (filters.languages.length > 0) {
    params.set('languages', filters.languages.join(','))
  }

  const { min, max } = starRangeToBounds(filters.starRange)
  if (min !== undefined) params.set('starsMin', String(min))
  if (max !== undefined) params.set('starsMax', String(max))

  const updatedAfter = timeRangeToAfter(filters.timeRange, now)
  if (updatedAfter) params.set('updatedAfter', updatedAfter)

  if (filters.sort !== 'stars') params.set('sort', filters.sort)
  if (filters.order !== 'desc') params.set('order', filters.order)
  return params.toString()
}

/** 演示模式下的本地筛选 / 排序，与服务端语义保持一致。 */
export function filterAndSortRepos(
  repos: RepoItem[],
  filters: RepoFilters,
  now: Date = new Date()
): RepoItem[] {
  const keyword = filters.keyword.trim().toLowerCase()
  const { min, max } = starRangeToBounds(filters.starRange)
  const updatedAfter = timeRangeToAfter(filters.timeRange, now)

  const filtered = repos.filter((repo) => {
    if (keyword) {
      const haystack = [
        repo.fullName,
        repo.description ?? '',
        repo.language ?? '',
        repo.category ?? '',
        ...repo.tags,
      ]
        .join(' ')
        .toLowerCase()
      if (!haystack.includes(keyword)) return false
    }
    if (filters.categoryId && repo.categoryId !== filters.categoryId) {
      return false
    }
    if (
      filters.tagNames.length > 0 &&
      !filters.tagNames.every((tag) => repo.tags.includes(tag))
    ) {
      return false
    }
    if (
      filters.languages.length > 0 &&
      !filters.languages.includes(repo.language ?? '')
    ) {
      return false
    }
    if (min !== undefined && repo.stars < min) return false
    if (max !== undefined && repo.stars > max) return false
    if (updatedAfter) {
      const updated = repo.updatedAt?.slice(0, 10) ?? ''
      if (!updated || updated < updatedAfter) return false
    }
    return true
  })

  const direction = filters.order === 'asc' ? 1 : -1
  return [...filtered].sort((a, b) => {
    let result = 0
    switch (filters.sort) {
      case 'stars':
        result = a.stars - b.stars
        break
      case 'updated':
        result = (a.updatedAt ?? '').localeCompare(b.updatedAt ?? '')
        break
      case 'created':
        result = (a.createdAt ?? '').localeCompare(b.createdAt ?? '')
        break
      case 'name':
        result = a.fullName.localeCompare(b.fullName)
        break
    }
    if (result === 0) result = a.id.localeCompare(b.id)
    return result * direction
  })
}

/** 当前生效的筛选条件组数（排序不算筛选）。 */
export function countActiveFilters(filters: RepoFilters): number {
  let count = 0
  if (filters.keyword.trim()) count += 1
  if (filters.categoryId) count += 1
  if (filters.tagNames.length > 0) count += 1
  if (filters.languages.length > 0) count += 1
  if (filters.starRange !== 'all') count += 1
  if (filters.timeRange !== 'all') count += 1
  return count
}
