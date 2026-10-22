import { apiFetch } from '@/lib/api'
import type { SearchMode, SearchScope, SearchUnderstanding } from './utils'

export interface SearchResultItem {
  id: string
  source: 'my' | 'trending'
  fullName: string
  name: string
  description: string
  language: string
  stars: number
  starsToday: number
  url: string
  score: number
  reason: string
}

export interface SearchResponse {
  query: string
  mode: SearchMode
  count: number
  tookMs: number
  backend: string
  model: string
  dim: number
  items: SearchResultItem[]
  understanding?: SearchUnderstanding
}

export interface SearchRequest {
  query: string
  topK?: number
  scope?: SearchScope
}

export const MOCK_SEARCH_ITEMS: SearchResultItem[] = [
  {
    id: 'nestjs/awesome-nestjs',
    source: 'trending',
    fullName: 'nestjs/awesome-nestjs',
    name: 'awesome-nestjs',
    description: 'NestJS 生态资源与最佳实践合集',
    language: 'TypeScript',
    stars: 12800,
    starsToday: 42,
    url: 'https://github.com/nestjs/awesome-nestjs',
    score: 0.91,
    reason:
      '与查询语义相似度 91%。主要使用 TypeScript 开发；项目简介：NestJS 生态资源与最佳实践合集。',
  },
  {
    id: 'demo/tenant-admin',
    source: 'my',
    fullName: 'demo/tenant-admin',
    name: 'tenant-admin',
    description: '支持多租户的 NestJS 管理后台模板',
    language: 'TypeScript',
    stars: 356,
    starsToday: 0,
    url: 'https://github.com/demo/tenant-admin',
    score: 0.88,
    reason:
      '与查询语义相似度 88%。主要使用 TypeScript 开发；项目简介：支持多租户的 NestJS 管理后台模板。',
  },
  {
    id: 'demo/saas-starter',
    source: 'trending',
    fullName: 'demo/saas-starter',
    name: 'saas-starter',
    description: '多租户 SaaS 启动模板，内置计费与权限',
    language: 'TypeScript',
    stars: 2100,
    starsToday: 18,
    url: 'https://github.com/demo/saas-starter',
    score: 0.79,
    reason:
      '与查询语义相似度 79%。主要使用 TypeScript 开发；项目简介：多租户 SaaS 启动模板，内置计费与权限。',
  },
]

/** 多轮问答式检索（M6-09） */
export type ChatRole = 'user' | 'assistant'
export type ChatScopeInput = 'auto' | SearchScope
export type ChatMode = 'hybrid' | 'vector' | 'keyword'
export type ChatIntent = 'list' | 'count' | 'more' | 'detail' | 'compare'

export interface ChatMessage {
  role: ChatRole
  content: string
}

export interface ChatResultItem extends SearchResultItem {
  /** 答案中的 [n] 引用编号 */
  citation: number
}

export interface ChatFilters {
  language: string
  concepts: string[]
  terms: string[]
}

export interface ChatFacets {
  languages: Array<{ name: string; count: number }>
  sources: Array<{ name: string; count: number }>
}

export interface ChatResponse {
  question: string
  answer: string
  intent: ChatIntent
  scope: SearchScope
  topic: string
  language: string
  filters: ChatFilters
  count: number
  total: number
  items: ChatResultItem[]
  facets: ChatFacets
  suggestions: string[]
  mode: ChatMode
  tookMs: number
  turn: number
  backend: string
  model: string
  fallback?: boolean
}

export interface ChatRequest {
  messages: ChatMessage[]
  shownIds?: string[]
  topK?: number
  scope?: ChatScopeInput
}

export const MOCK_CHAT_ITEMS: ChatResultItem[] = MOCK_SEARCH_ITEMS.map(
  (item, index) => ({ ...item, citation: index + 1 })
)

/** 演示模式的问答响应：保持与真实接口同构，页面逻辑无需分支。 */
export function demoChatResponse(input: ChatRequest): ChatResponse {
  const question =
    [...input.messages].reverse().find((item) => item.role === 'user')
      ?.content ?? '我的收藏里有哪些支付相关项目？'
  const scope: SearchScope =
    input.scope === 'my' || input.scope === 'trending' ? input.scope : 'all'
  const items = MOCK_CHAT_ITEMS.filter(
    (item) => scope === 'all' || item.source === scope
  )
  const lines = [
    `演示模式：在${
      scope === 'my'
        ? '你的收藏'
        : scope === 'trending'
          ? '每日热榜'
          : '全部来源'
    }里找到 ${items.length} 个与「${question}」相关的项目：`,
    ...items.map(
      (item) =>
        `[${item.citation}] ${item.fullName}（${item.language}，★${item.stars}）`
    ),
  ]
  return {
    question,
    answer: lines.join('\n'),
    intent: 'list',
    scope,
    topic: question,
    language: '',
    filters: { language: '', concepts: [], terms: [question] },
    count: items.length,
    total: items.length,
    items,
    facets: {
      languages: [{ name: 'TypeScript', count: items.length }],
      sources: [{ name: 'trending', count: items.length }],
    },
    suggestions: ['还有吗？', '只看我的收藏', '其中 Star 最多的是哪个？'],
    mode: 'keyword',
    tookMs: 0,
    turn: input.messages.filter((item) => item.role === 'user').length,
    backend: '',
    model: '',
    fallback: true,
  }
}

/** 调用边缘多轮问答检索；失败时回退演示数据，保证页面可用。 */
export async function chatWithFallback(
  input: ChatRequest
): Promise<ChatResponse> {
  try {
    return await apiFetch<ChatResponse>('/api/search/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        messages: input.messages,
        shownIds: input.shownIds ?? [],
        topK: input.topK ?? 8,
        scope: input.scope ?? 'auto',
      }),
    })
  } catch {
    // eslint-disable-next-line no-console
    console.info('[opensource-factory] 问答检索接口不可用，使用演示数据')
    return demoChatResponse(input)
  }
}

/** 调用边缘语义搜索接口；失败时回退演示数据，保证页面可用。 */
export async function searchRepositories(
  input: SearchRequest
): Promise<SearchResponse> {
  try {
    return await apiFetch<SearchResponse>('/api/search/semantic', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        query: input.query,
        topK: input.topK ?? 10,
        scope: input.scope ?? 'all',
      }),
    })
  } catch {
    // eslint-disable-next-line no-console
    console.info('[opensource-factory] 语义搜索接口不可用，使用演示数据')
    return {
      query: input.query,
      mode: 'keyword',
      count: MOCK_SEARCH_ITEMS.length,
      tookMs: 0,
      backend: '',
      model: '',
      dim: 0,
      items: MOCK_SEARCH_ITEMS,
    }
  }
}
