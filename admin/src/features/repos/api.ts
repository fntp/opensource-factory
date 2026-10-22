import { fetchWithFallback } from '@/lib/api'

export interface RepoItem {
  id: string
  fullName: string
  description: string
  /** VPS 生成的 README 中文摘要（可选） */
  summary?: string | null
  language: string
  stars: number
  forks: number
  category: string
  tags: string[]
  updatedAt: string
  url: string
}

export const MOCK_REPOS: RepoItem[] = [
  {
    id: '1',
    fullName: 'fntp/opensource-factory',
    description: '个人开源资产管理与智能推荐系统',
    language: 'TypeScript',
    stars: 128,
    forks: 12,
    category: '工具平台',
    tags: ['资产', '推荐'],
    updatedAt: '2026-10-12',
    url: 'https://github.com/fntp/opensource-factory',
  },
  {
    id: '2',
    fullName: 'langchain-ai/langchain',
    description: '构建上下文感知推理应用的开源框架',
    language: 'Python',
    stars: 94210,
    forks: 15230,
    category: 'AI/LLM',
    tags: ['LLM', '框架'],
    updatedAt: '2026-10-13',
    url: 'https://github.com/langchain-ai/langchain',
  },
  {
    id: '3',
    fullName: 'shadcn-ui/ui',
    description: '设计精美的组件集合，可复制到你的应用中',
    language: 'TypeScript',
    stars: 78120,
    forks: 4150,
    category: '前端开发',
    tags: ['组件', '设计'],
    updatedAt: '2026-10-12',
    url: 'https://github.com/shadcn-ui/ui',
  },
  {
    id: '4',
    fullName: 'ollama/ollama',
    description: '在本地轻松运行大语言模型',
    language: 'Go',
    stars: 102340,
    forks: 8100,
    category: 'AI/LLM',
    tags: ['本地模型', '推理'],
    updatedAt: '2026-10-13',
    url: 'https://github.com/ollama/ollama',
  },
  {
    id: '5',
    fullName: 'lobehub/lobe-chat',
    description: '开源的现代 AI 聊天应用框架',
    language: 'TypeScript',
    stars: 55120,
    forks: 12300,
    category: 'AI/LLM',
    tags: ['聊天', '应用'],
    updatedAt: '2026-10-11',
    url: 'https://github.com/lobehub/lobe-chat',
  },
  {
    id: '6',
    fullName: 'fastapi/fastapi',
    description: '高性能的现代 Python Web 框架',
    language: 'Python',
    stars: 82600,
    forks: 7100,
    category: '后端与 API',
    tags: ['API', '异步'],
    updatedAt: '2026-10-10',
    url: 'https://github.com/fastapi/fastapi',
  },
  {
    id: '7',
    fullName: 'vuejs/core',
    description: '渐进式 JavaScript 框架',
    language: 'TypeScript',
    stars: 48900,
    forks: 4300,
    category: '前端开发',
    tags: ['Vue', '框架'],
    updatedAt: '2026-10-12',
    url: 'https://github.com/vuejs/core',
  },
  {
    id: '8',
    fullName: 'tauri-apps/tauri',
    description: '使用 Web 技术构建更小、更快、更安全的桌面应用',
    language: 'Rust',
    stars: 92100,
    forks: 2800,
    category: '桌面端',
    tags: ['跨平台', 'Rust'],
    updatedAt: '2026-10-09',
    url: 'https://github.com/tauri-apps/tauri',
  },
]

export function fetchRepos(): Promise<RepoItem[]> {
  return fetchWithFallback<RepoItem[]>('/api/repos', MOCK_REPOS)
}
