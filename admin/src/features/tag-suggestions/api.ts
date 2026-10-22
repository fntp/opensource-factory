import { apiFetch, fetchWithFallback } from '@/lib/api'

export type TagSuggestionCategory =
  | 'language'
  | 'framework'
  | 'domain'
  | 'quality'
export type TagSuggestionStatus = 'pending' | 'accepted' | 'dismissed'
export type TagSuggestionFilter = TagSuggestionStatus | 'all'

export interface TagSuggestionItem {
  id: string
  repoId: string
  repoName: string
  repoUrl: string
  summary: string
  tagName: string
  category: TagSuggestionCategory
  score: number
  reason: string
  evidence: string
  status: TagSuggestionStatus
  createdAt: string
  updatedAt: string
}

export interface TagSuggestionsSummary {
  pending: number
  accepted: number
  dismissed: number
  repos: number
  avgScore: number | null
}

export interface TagSuggestionsPayload {
  items: TagSuggestionItem[]
  total: number
  summary: TagSuggestionsSummary
}

export interface GenerateTagSuggestionsResult {
  generatedAt: string
  scanned: number
  suggested: number
  skipped: number
  source: 'vps' | 'local'
  saved: number
  items: Array<{
    repoId: string
    tags: Array<{
      name: string
      category: TagSuggestionCategory
      score: number
      reason: string
      evidence: string
    }>
  }>
}

export interface AcceptTagSuggestionsResult {
  accepted: number
  tagsApplied: number
  skipped: number
  total: number
}

export interface DismissTagSuggestionsResult {
  dismissed: number
}

function hoursAgo(hours: number): string {
  return new Date(Date.now() - hours * 60 * 60 * 1000).toISOString()
}

export const MOCK_TAG_SUGGESTIONS: TagSuggestionItem[] = [
  {
    id: 'mock-ts-1',
    repoId: 'fntp/opensource-factory',
    repoName: 'fntp/opensource-factory',
    repoUrl: 'https://github.com/fntp/opensource-factory',
    summary:
      '一个面向开发者的开源资产管理平台，提供 GitHub 仓库同步、中文摘要生成与智能推荐。后端基于 Python FastAPI，前端使用 React 与 TypeScript，支持自托管部署。',
    tagName: 'Python',
    category: 'language',
    score: 0.83,
    reason: '语言字段为 Python',
    evidence: 'language 字段：Python',
    status: 'pending',
    createdAt: hoursAgo(2),
    updatedAt: hoursAgo(2),
  },
  {
    id: 'mock-ts-2',
    repoId: 'fntp/opensource-factory',
    repoName: 'fntp/opensource-factory',
    repoUrl: 'https://github.com/fntp/opensource-factory',
    summary:
      '一个面向开发者的开源资产管理平台，提供 GitHub 仓库同步、中文摘要生成与智能推荐。后端基于 Python FastAPI，前端使用 React 与 TypeScript，支持自托管部署。',
    tagName: 'FastAPI',
    category: 'framework',
    score: 0.72,
    reason: '摘要命中「FastAPI」',
    evidence: '…后端基于 Python FastAPI，前端使用 React 与 TypeScript…',
    status: 'pending',
    createdAt: hoursAgo(2),
    updatedAt: hoursAgo(2),
  },
  {
    id: 'mock-ts-3',
    repoId: 'fntp/opensource-factory',
    repoName: 'fntp/opensource-factory',
    repoUrl: 'https://github.com/fntp/opensource-factory',
    summary:
      '一个面向开发者的开源资产管理平台，提供 GitHub 仓库同步、中文摘要生成与智能推荐。后端基于 Python FastAPI，前端使用 React 与 TypeScript，支持自托管部署。',
    tagName: '自托管',
    category: 'quality',
    score: 0.63,
    reason: '摘要命中「自托管」',
    evidence: '…前端使用 React 与 TypeScript，支持自托管部署。',
    status: 'pending',
    createdAt: hoursAgo(2),
    updatedAt: hoursAgo(2),
  },
  {
    id: 'mock-ts-4',
    repoId: 'langchain-ai/langchain',
    repoName: 'langchain-ai/langchain',
    repoUrl: 'https://github.com/langchain-ai/langchain',
    summary:
      '构建上下文感知推理应用的开源框架，支持大语言模型编排、工具调用与可扩展的插件生态。',
    tagName: 'AI/LLM',
    category: 'domain',
    score: 0.68,
    reason: '摘要命中「大语言模型」',
    evidence: '…支持大语言模型编排、工具调用与可扩展的插件生态。',
    status: 'pending',
    createdAt: hoursAgo(5),
    updatedAt: hoursAgo(5),
  },
  {
    id: 'mock-ts-5',
    repoId: 'ollama/ollama',
    repoName: 'ollama/ollama',
    repoUrl: 'https://github.com/ollama/ollama',
    summary:
      '在本地轻松运行大语言模型，支持离线使用与多种模型格式，提供命令行与 HTTP API。',
    tagName: '离线可用',
    category: 'quality',
    score: 0.63,
    reason: '摘要命中「离线」',
    evidence: '…支持离线使用与多种模型格式…',
    status: 'accepted',
    createdAt: hoursAgo(26),
    updatedAt: hoursAgo(20),
  },
  {
    id: 'mock-ts-6',
    repoId: 'shadcn-ui/ui',
    repoName: 'shadcn-ui/ui',
    repoUrl: 'https://github.com/shadcn-ui/ui',
    summary: '设计精美的组件集合，可复制到你的应用中，基于 Tailwind CSS 构建。',
    tagName: '前端开发',
    category: 'domain',
    score: 0.68,
    reason: '摘要命中「前端」',
    evidence: '…可复制到你的应用中…',
    status: 'dismissed',
    createdAt: hoursAgo(30),
    updatedAt: hoursAgo(28),
  },
]

export function mockTagSuggestionsPayload(
  status: TagSuggestionFilter = 'pending'
): TagSuggestionsPayload {
  const all = MOCK_TAG_SUGGESTIONS
  const pending = all.filter((item) => item.status === 'pending')
  const items = status === 'all' ? all : all.filter((item) => item.status === status)
  const avg =
    pending.length > 0
      ? pending.reduce((sum, item) => sum + item.score, 0) / pending.length
      : null
  return {
    items,
    total: items.length,
    summary: {
      pending: pending.length,
      accepted: all.filter((item) => item.status === 'accepted').length,
      dismissed: all.filter((item) => item.status === 'dismissed').length,
      repos: new Set(pending.map((item) => item.repoId)).size,
      avgScore: avg,
    },
  }
}

function jsonInit(body: unknown): RequestInit {
  return {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  }
}

export function fetchTagSuggestions(
  status: TagSuggestionFilter = 'pending'
): Promise<TagSuggestionsPayload> {
  return fetchWithFallback<TagSuggestionsPayload>(
    `/api/tag-suggestions?status=${status}&limit=200`,
    mockTagSuggestionsPayload(status)
  )
}

export function generateTagSuggestions(body: {
  repoIds?: string[]
  limit?: number
  perRepo?: number
} = {}): Promise<GenerateTagSuggestionsResult> {
  return apiFetch<GenerateTagSuggestionsResult>(
    '/api/tag-suggestions/generate',
    jsonInit(body)
  )
}

export function acceptTagSuggestions(body: {
  ids?: string[]
  repoId?: string
  tags?: string[]
}): Promise<AcceptTagSuggestionsResult> {
  return apiFetch<AcceptTagSuggestionsResult>(
    '/api/tag-suggestions/accept',
    jsonInit(body)
  )
}

export function dismissTagSuggestions(ids: string[]): Promise<DismissTagSuggestionsResult> {
  return apiFetch<DismissTagSuggestionsResult>(
    '/api/tag-suggestions/dismiss',
    jsonInit({ ids })
  )
}
