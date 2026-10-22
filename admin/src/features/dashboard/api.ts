import { fetchWithFallback } from '@/lib/api'

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
  description: string
  language: string
  stars: number
  starsToday: number
  url: string
}

export const MOCK_DASHBOARD_STATS: DashboardStats = {
  totalRepos: 128,
  trendingToday: 24,
  pendingRecommendations: 12,
  categoryCount: 9,
}

export const MOCK_TRENDING: TrendingItem[] = [
  {
    id: '1',
    owner: 'langchain-ai',
    name: 'langchain',
    description: '构建上下文感知推理应用的开源框架',
    language: 'Python',
    stars: 94000,
    starsToday: 512,
    url: 'https://github.com/langchain-ai/langchain',
  },
  {
    id: '2',
    owner: 'microsoft',
    name: 'autogen',
    description: '面向多智能体应用的编程框架',
    language: 'Python',
    stars: 38000,
    starsToday: 402,
    url: 'https://github.com/microsoft/autogen',
  },
  {
    id: '3',
    owner: 'shadcn-ui',
    name: 'ui',
    description: '设计精美的组件集合，可复制到你的应用中',
    language: 'TypeScript',
    stars: 78000,
    starsToday: 366,
    url: 'https://github.com/shadcn-ui/ui',
  },
  {
    id: '4',
    owner: 'ollama',
    name: 'ollama',
    description: '在本地轻松运行大语言模型',
    language: 'Go',
    stars: 102000,
    starsToday: 298,
    url: 'https://github.com/ollama/ollama',
  },
  {
    id: '5',
    owner: 'lobehub',
    name: 'lobe-chat',
    description: '开源的现代 AI 聊天应用框架',
    language: 'TypeScript',
    stars: 55000,
    starsToday: 254,
    url: 'https://github.com/lobehub/lobe-chat',
  },
]

export function fetchDashboardStats(): Promise<DashboardStats> {
  return fetchWithFallback<DashboardStats>('/api/dashboard/stats', MOCK_DASHBOARD_STATS)
}

export function fetchRecentTrending(): Promise<TrendingItem[]> {
  return fetchWithFallback<TrendingItem[]>(
    '/api/trending?limit=5',
    MOCK_TRENDING
  )
}
