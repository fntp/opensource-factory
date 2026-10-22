import { fetchWithFallback } from '@/lib/api'

export interface Recommendation {
  id: string
  owner: string
  name: string
  description: string
  language: string
  stars: number
  score: number
  reason: string
  basedOn: string[]
  url: string
}

export const MOCK_RECOMMENDATIONS: Recommendation[] = [
  {
    id: '1',
    owner: 'huggingface',
    name: 'transformers',
    description: '最流行的预训练模型库，覆盖 NLP、视觉与多模态',
    language: 'Python',
    stars: 136000,
    score: 0.95,
    reason: '与你收藏的 langchain、ollama 同属 AI/LLM 领域，语义相似度极高',
    basedOn: ['AI/LLM', 'Python'],
    url: 'https://github.com/huggingface/transformers',
  },
  {
    id: '2',
    owner: 'modelcontextprotocol',
    name: 'servers',
    description: 'Model Context Protocol 官方服务器集合',
    language: 'TypeScript',
    stars: 42800,
    score: 0.92,
    reason: '与你关注的「AI 工具链」方向高度相关',
    basedOn: ['AI/LLM', '工具'],
    url: 'https://github.com/modelcontextprotocol/servers',
  },
  {
    id: '3',
    owner: 'astral-sh',
    name: 'ruff',
    description: '极快的 Python linter 与格式化工具',
    language: 'Rust',
    stars: 35200,
    score: 0.88,
    reason: '你收藏了多个 Python 项目，ruff 是当前最流行的 Python 开发工具',
    basedOn: ['Python', '开发工具'],
    url: 'https://github.com/astral-sh/ruff',
  },
  {
    id: '4',
    owner: 'vercel',
    name: 'next.js',
    description: '用于生产环境的 React 全栈框架',
    language: 'TypeScript',
    stars: 127000,
    score: 0.85,
    reason: '你收藏的前端项目较多（shadcn/ui、vuejs/core），推荐同领域热门框架',
    basedOn: ['前端开发', 'TypeScript'],
    url: 'https://github.com/vercel/next.js',
  },
  {
    id: '5',
    owner: 'apache',
    name: 'airflow',
    description: '以编程方式编写、调度和监控工作流的平台',
    language: 'Python',
    stars: 36800,
    score: 0.81,
    reason: '与「数据工程」标签语义相近，且你近期阅读了多个调度相关项目',
    basedOn: ['数据工程', 'Python'],
    url: 'https://github.com/apache/airflow',
  },
  {
    id: '6',
    owner: 'tailscale',
    name: 'tailscale',
    description: '零配置的 WireGuard 组网工具',
    language: 'Go',
    stars: 24800,
    score: 0.78,
    reason: '基于你近期阅读的「基础设施」类内容推荐',
    basedOn: ['基础设施', 'Go'],
    url: 'https://github.com/tailscale/tailscale',
  },
]

export function fetchRecommendations(): Promise<Recommendation[]> {
  return fetchWithFallback<Recommendation[]>(
    '/api/recommendations',
    MOCK_RECOMMENDATIONS
  )
}
