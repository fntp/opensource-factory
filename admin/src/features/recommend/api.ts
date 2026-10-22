import { apiFetch } from '@/lib/api'

/** 与 edge GET /api/recommendations 返回的 Recommendation 契约一致 */
export interface Recommendation {
  id: string
  owner: string | null
  name: string | null
  description: string | null
  language: string | null
  stars: number
  score: number
  reason: string | null
  basedOn: string[]
  url: string | null
}

/** 当前用户的推荐列表（含全局推荐） */
export function fetchRecommendations(): Promise<Recommendation[]> {
  return apiFetch<Recommendation[]>('/api/recommendations')
}
