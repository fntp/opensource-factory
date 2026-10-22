import { apiFetch } from '@/lib/api'
import type { SearchMode, SearchScope } from './utils'

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
    reason: '与查询语义相似度 91%。主要使用 TypeScript 开发；项目简介：NestJS 生态资源与最佳实践合集。',
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
    reason: '与查询语义相似度 88%。主要使用 TypeScript 开发；项目简介：支持多租户的 NestJS 管理后台模板。',
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
    reason: '与查询语义相似度 79%。主要使用 TypeScript 开发；项目简介：多租户 SaaS 启动模板，内置计费与权限。',
  },
]

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
