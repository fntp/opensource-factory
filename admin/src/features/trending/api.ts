import { apiFetch, DEMO_MODE, fetchWithFallback } from '@/lib/api'

export type SummarySource = 'readme' | 'description' | 'tech' | 'empty'

export type TrendingTrend = 'up' | 'down' | 'new' | 'same'

export interface TrendingRepo {
  id: string
  owner: string
  name: string
  description: string
  language: string
  stars: number
  starsToday: number
  url: string
  /** 快照日期（YYYY-MM-DD） */
  snapshotDate: string | null
  /** 当日排名（从 1 开始） */
  rank: number
  /** 相对上一快照日的排名变化（正数 = 上升，null = 新上榜） */
  rankChange: number | null
  trend: TrendingTrend
}

export interface TrendingQuery {
  date?: string
  language?: string
  limit?: number
}

export interface TrendingDatesResponse {
  dates: string[]
  latest: string | null
}

export interface TrendingLanguage {
  language: string
  count: number
}

export interface TrendingLanguagesResponse {
  date: string | null
  languages: TrendingLanguage[]
}

export const MOCK_TRENDING_DATES = ['2026-10-22', '2026-10-21', '2026-10-20']

export interface TrendingRepoDetail extends TrendingRepo {
  platform: string
  techStack: string[]
  summary: string | null
  summarySource: SummarySource
  crawledAt: string | null
  isFavorited: boolean
}

export interface FavoriteResult {
  favorited: boolean
  created?: boolean
  removed?: boolean
  repoId: string
}
export const MOCK_TRENDING_REPOS: TrendingRepo[] = [
  {
    id: '1',
    owner: 'langchain-ai',
    name: 'langchain',
    description: '构建上下文感知推理应用的开源框架',
    language: 'Python',
    stars: 94210,
    starsToday: 512,
    url: 'https://github.com/langchain-ai/langchain',
    snapshotDate: '2026-10-22',
    rank: 1,
    rankChange: 2,
    trend: 'up',
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
    snapshotDate: '2026-10-22',
    rank: 2,
    rankChange: -1,
    trend: 'down',
  },
  {
    id: '3',
    owner: 'shadcn-ui',
    name: 'ui',
    description: '设计精美的组件集合，可复制到你的应用中',
    language: 'TypeScript',
    stars: 78120,
    starsToday: 366,
    url: 'https://github.com/shadcn-ui/ui',
    snapshotDate: '2026-10-22',
    rank: 3,
    rankChange: 0,
    trend: 'same',
  },
  {
    id: '4',
    owner: 'ollama',
    name: 'ollama',
    description: '在本地轻松运行大语言模型',
    language: 'Go',
    stars: 102340,
    starsToday: 298,
    url: 'https://github.com/ollama/ollama',
    snapshotDate: '2026-10-22',
    rank: 4,
    rankChange: null,
    trend: 'new',
  },
  {
    id: '5',
    owner: 'lobehub',
    name: 'lobe-chat',
    description: '开源的现代 AI 聊天应用框架',
    language: 'TypeScript',
    stars: 55120,
    starsToday: 254,
    url: 'https://github.com/lobehub/lobe-chat',
    snapshotDate: '2026-10-22',
    rank: 5,
    rankChange: 3,
    trend: 'up',
  },
  {
    id: '6',
    owner: 'ggml-org',
    name: 'llama.cpp',
    description: 'C/C++ 大语言模型推理',
    language: 'C++',
    stars: 68100,
    starsToday: 233,
    url: 'https://github.com/ggml-org/llama.cpp',
    snapshotDate: '2026-10-22',
    rank: 6,
    rankChange: -2,
    trend: 'down',
  },
  {
    id: '7',
    owner: 'browser-use',
    name: 'browser-use',
    description: '让 AI 代理轻松操作浏览器',
    language: 'Python',
    stars: 32400,
    starsToday: 210,
    url: 'https://github.com/browser-use/browser-use',
    snapshotDate: '2026-10-22',
    rank: 7,
    rankChange: 0,
    trend: 'same',
  },
  {
    id: '8',
    owner: 'n8n-io',
    name: 'n8n',
    description: '工作流自动化平台，原生支持 AI 能力',
    language: 'TypeScript',
    stars: 61200,
    starsToday: 198,
    url: 'https://github.com/n8n-io/n8n',
    snapshotDate: '2026-10-22',
    rank: 8,
    rankChange: null,
    trend: 'new',
  },
  {
    id: '9',
    owner: 'supabase',
    name: 'supabase',
    description: '开源的 Firebase 替代方案',
    language: 'TypeScript',
    stars: 74500,
    starsToday: 187,
    url: 'https://github.com/supabase/supabase',
    snapshotDate: '2026-10-22',
    rank: 9,
    rankChange: 1,
    trend: 'up',
  },
  {
    id: '10',
    owner: 'tauri-apps',
    name: 'tauri',
    description: '使用 Web 技术构建更小、更快、更安全的桌面应用',
    language: 'Rust',
    stars: 92100,
    starsToday: 165,
    url: 'https://github.com/tauri-apps/tauri',
    snapshotDate: '2026-10-22',
    rank: 10,
    rankChange: -1,
    trend: 'down',
  },
]

/** 生成查询串：空值不写入，保持缓存键稳定。 */
export function buildTrendingQuery(params: TrendingQuery = {}): string {
  const search = new URLSearchParams()
  if (params.date) search.set('date', params.date)
  if (params.language) search.set('language', params.language)
  if (params.limit) search.set('limit', String(params.limit))
  const qs = search.toString()
  return qs ? `?${qs}` : ''
}

/** 演示模式：按语言过滤，并按当前日期重排演示数据的排名。 */
export function filterMockTrending(
  items: TrendingRepo[],
  params: TrendingQuery = {}
): TrendingRepo[] {
  const language = params.language?.toLowerCase()
  const filtered = language
    ? items.filter((item) => item.language.toLowerCase() === language)
    : items
  return filtered
    .slice(0, params.limit ?? filtered.length)
    .map((item, index) => ({
      ...item,
      snapshotDate: params.date ?? item.snapshotDate,
      rank: index + 1,
    }))
}

export function fetchTrending(
  params: TrendingQuery = {}
): Promise<TrendingRepo[]> {
  return fetchWithFallback<TrendingRepo[]>(
    `/api/trending${buildTrendingQuery(params)}`,
    filterMockTrending(MOCK_TRENDING_REPOS, params)
  )
}

/** 兼容两种 /dates 返回：{dates,latest} 或 [{date,count}]。 */
export async function fetchTrendingDates(): Promise<TrendingDatesResponse> {
  const fallback: TrendingDatesResponse = {
    dates: MOCK_TRENDING_DATES,
    latest: MOCK_TRENDING_DATES[0] ?? null,
  }
  const raw = await fetchWithFallback<
    TrendingDatesResponse | Array<{ date: string; count: number }>
  >('/api/trending/dates', fallback)
  if (Array.isArray(raw)) {
    const dates = raw.map((item) => item.date)
    return { dates, latest: dates[0] ?? null }
  }
  return raw
}

export function fetchTrendingLanguages(
  date?: string
): Promise<TrendingLanguagesResponse> {
  const counts = new Map<string, number>()
  for (const item of MOCK_TRENDING_REPOS) {
    counts.set(item.language, (counts.get(item.language) ?? 0) + 1)
  }
  return fetchWithFallback<TrendingLanguagesResponse>(
    `/api/trending/languages${date ? `?date=${encodeURIComponent(date)}` : ''}`,
    {
      date: date ?? MOCK_TRENDING_DATES[0] ?? null,
      languages: [...counts.entries()]
        .map(([language, count]) => ({ language, count }))
        .sort(
          (a, b) => b.count - a.count || a.language.localeCompare(b.language)
        ),
    }
  )

const MOCK_TECH_STACK: Record<string, string[]> = {
  'langchain-ai/langchain': ['Python', 'LLM', 'RAG'],
  'microsoft/autogen': ['Python', 'LLM'],
  'shadcn-ui/ui': ['TypeScript', 'React', 'Tailwind CSS'],
  'ollama/ollama': ['Go', 'LLM'],
  'lobehub/lobe-chat': ['TypeScript', 'React', 'Next.js'],
  'ggml-org/llama.cpp': ['C++', 'LLM'],
  'browser-use/browser-use': ['Python', 'LLM'],
  'n8n-io/n8n': ['TypeScript', 'Node.js'],
  'supabase/supabase': ['TypeScript', 'PostgreSQL'],
  'tauri-apps/tauri': ['Rust', 'Tauri'],
}

export const MOCK_TRENDING_DETAILS: TrendingRepoDetail[] = MOCK_TRENDING_REPOS.map(
  (item) => ({
    ...item,
    platform: 'github',
    techStack: MOCK_TECH_STACK[`${item.owner}/${item.name}`] ?? [item.language],
    summary: `${item.description}。该项目主要使用 ${item.language}，适合需要相关能力的团队参考。`,
    summarySource: 'description',
    crawledAt: '2026-10-22',
    isFavorited: false,
  })
)

/** 详情页路径：owner/name 分段编码，避免斜杠被当成路径分隔符 */
export function trendingDetailPath(owner: string, name: string): string {
  return `/api/trending/${encodeURIComponent(owner)}/${encodeURIComponent(name)}`
}

function mockDetail(owner: string, name: string): TrendingRepoDetail {
  const found = MOCK_TRENDING_DETAILS.find(
    (item) => item.owner === owner && item.name === name
  )
  if (found) return { ...found }
  return {
    id: `${owner}/${name}`,
    owner,
    name,
    description: '演示项目',
    language: 'Unknown',
    stars: 0,
    starsToday: 0,
    url: `https://github.com/${owner}/${name}`,
    platform: 'github',
    techStack: [],
    summary: '演示模式下暂无该项目的摘要。',
    summarySource: 'empty',
    crawledAt: null,
    isFavorited: false,
  }
}

export async function fetchTrendingDetail(
  owner: string,
  name: string
): Promise<TrendingRepoDetail> {
  if (DEMO_MODE) return mockDetail(owner, name)
  return apiFetch<TrendingRepoDetail>(trendingDetailPath(owner, name))
}

export async function favoriteTrending(
  owner: string,
  name: string
): Promise<FavoriteResult> {
  if (DEMO_MODE) {
    return { favorited: true, created: true, repoId: `${owner}/${name}` }
  }
  return apiFetch<FavoriteResult>(`${trendingDetailPath(owner, name)}/favorite`, {
    method: 'POST',
  })
}

export async function unfavoriteTrending(
  owner: string,
  name: string
): Promise<FavoriteResult> {
  if (DEMO_MODE) {
    return { favorited: false, removed: true, repoId: `${owner}/${name}` }
  }
  return apiFetch<FavoriteResult>(`${trendingDetailPath(owner, name)}/favorite`, {
    method: 'DELETE',
  })
}
