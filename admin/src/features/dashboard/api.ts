import { apiFetch } from '@/lib/api'

export interface DashboardStats {
  totalRepos: number
  trendingToday: number
  pendingRecommendations: number
  categoryCount: number
}

export interface TrendingItem {
  id: string
  owner: string
  name: string
  description: string | null
  language: string | null
  stars: number
  starsToday: number
  url: string
}

/** 仪表盘统计 */
export function fetchDashboardStats(): Promise<DashboardStats> {
  return apiFetch<DashboardStats>('/api/dashboard/stats')
}

/** 仪表盘右侧的今日热榜（取前 5） */
export function fetchRecentTrending(): Promise<TrendingItem[]> {
  return apiFetch<TrendingItem[]>('/api/trending?limit=5')
}
