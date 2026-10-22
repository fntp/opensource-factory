import { apiFetch } from '@/lib/api'

/** 与 edge GET /api/trending 返回的 TrendingRepo 契约一致 */
export interface TrendingRepo {
  id: string
  owner: string
  name: string
  description: string | null
  language: string | null
  stars: number
  starsToday: number
  url: string
}

/** 今日热榜 */
export function fetchTrending(): Promise<TrendingRepo[]> {
  return apiFetch<TrendingRepo[]>('/api/trending')
}
