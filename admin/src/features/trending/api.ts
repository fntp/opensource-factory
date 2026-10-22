import { apiFetch, DEMO_MODE, fetchWithFallback } from '@/lib/api'

export type SummarySource = 'readme' | 'description' | 'tech' | 'empty'

export interface TrendingRepo {
  id: string
  owner: string
  name: string
  description: string
  language: string
  stars: number
  starsToday: number
  url: string
}

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
    stars: 78120,
    starsToday: 366,
    url: 'https://github.com/shadcn-ui/ui',
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
  },
]

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

export function fetchTrending(): Promise<TrendingRepo[]> {
  return fetchWithFallback<TrendingRepo[]>('/api/trending', MOCK_TRENDING_REPOS)
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
