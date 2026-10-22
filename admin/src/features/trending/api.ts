import { fetchWithFallback } from '@/lib/api'

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

export function fetchTrending(): Promise<TrendingRepo[]> {
  return fetchWithFallback<TrendingRepo[]>('/api/trending', MOCK_TRENDING_REPOS)
}
