import { apiFetch, fetchWithFallback } from '@/lib/api'
import type {
  CategorySuggestionAcceptResult,
  CategorySuggestionGenerateResult,
  CategorySuggestionListResponse,
  CategorySuggestionStatus,
} from './utils'

export type {
  CategorySuggestionAcceptResult,
  CategorySuggestionGenerateResult,
  CategorySuggestionItem,
  CategorySuggestionListResponse,
  CategorySuggestionStatus,
  CategorySuggestionSummary,
} from './utils'

export interface GenerateCategorySuggestionRequest {
  limit?: number
  perRepo?: number
  minScore?: number
  repoIds?: string[]
}

function mockItem(
  id: string,
  repoId: string,
  repoName: string,
  categoryName: string,
  businessLine: string,
  score: number,
  reason: string,
  evidence: string,
  status: CategorySuggestionStatus = 'pending'
) {
  return {
    id,
    repoId,
    repoName,
    repoUrl: `https://github.com/${repoId}`,
    summary: evidence,
    categoryName,
    businessLine,
    score,
    reason,
    evidence,
    status,
    currentCategory: null,
    updatedAt: '2026-10-22 09:30:00',
  }
}

export const MOCK_CATEGORY_SUGGESTIONS: CategorySuggestionListResponse = {
  items: [
    mockItem(
      'cs_demo_pay',
      'demo/pay-gateway',
      'pay-gateway',
      '金融 / 支付',
      'fintech',
      0.91,
      '名称命中「payment」；简介命中「支付」「对账」',
      '多渠道 payment gateway，支持支付、退款与自动对账'
    ),
    mockItem(
      'cs_demo_llm',
      'demo/llm-chat',
      'llm-chat',
      'AI / 大模型',
      'ai',
      0.88,
      '名称命中「llm」；摘要命中「RAG」「Agent」',
      '基于大模型的对话应用，支持 RAG 检索增强与 Agent 工具调用'
    ),
    mockItem(
      'cs_demo_edge',
      'demo/edge-cache',
      'edge-cache',
      'DevOps / 云原生',
      'cloud-devops',
      0.72,
      '简介命中「Workers」「缓存」；语言为 TypeScript',
      '面向 Cloudflare Workers 的边缘缓存中间件，支持标签失效'
    ),
    mockItem(
      'cs_demo_admin',
      'demo/tenant-admin',
      'tenant-admin',
      '企业服务 / SaaS',
      'saas',
      0.83,
      '简介命中「多租户」「后台」',
      '支持多租户的 NestJS 管理后台模板，内置权限与审计',
      'accepted'
    ),
  ],
  summary: {
    total: 4,
    pending: 3,
    accepted: 1,
    dismissed: 0,
    repos: 4,
    avgScore: 0.836,
  },
  categories: [
    { id: 'cat_demo_fintech', name: '金融 / 支付' },
    { id: 'cat_demo_ai', name: 'AI / 大模型' },
    { id: 'cat_demo_saas', name: '企业服务 / SaaS' },
  ],
}

/** 当前用户的分类建议列表（默认待确认）。 */
export async function fetchCategorySuggestions(
  status: CategorySuggestionStatus | 'all' = 'pending'
): Promise<CategorySuggestionListResponse> {
  const query = status === 'all' ? '' : `?status=${status}`
  return await fetchWithFallback<CategorySuggestionListResponse>(
    `/api/category-suggestions${query}`,
    status === 'all'
      ? MOCK_CATEGORY_SUGGESTIONS
      : {
          ...MOCK_CATEGORY_SUGGESTIONS,
          items: MOCK_CATEGORY_SUGGESTIONS.items.filter(
            (item) => item.status === status
          ),
        }
  )
}

/** 批量生成建议：优先 VPS 规则引擎，edge 内部自动本地兜底。 */
export async function generateCategorySuggestions(
  input: GenerateCategorySuggestionRequest = {}
): Promise<CategorySuggestionGenerateResult> {
  try {
    return await apiFetch<CategorySuggestionGenerateResult>(
      '/api/category-suggestions/generate',
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(input),
      }
    )
  } catch {
    // eslint-disable-next-line no-console
    console.info('[opensource-factory] 分类建议生成接口不可用，使用演示数据')
    return {
      generatedAt: new Date().toISOString(),
      scanned: 42,
      suggested: 18,
      skipped: 24,
      source: 'local',
    }
  }
}

/** 采纳建议：写入仓库分类；分类不存在时由 edge 自动创建。 */
export async function acceptCategorySuggestions(
  ids: string[]
): Promise<CategorySuggestionAcceptResult> {
  try {
    return await apiFetch<CategorySuggestionAcceptResult>(
      '/api/category-suggestions/accept',
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ids }),
      }
    )
  } catch {
    // eslint-disable-next-line no-console
    console.info('[opensource-factory] 采纳接口不可用，演示模式本地生效')
    return { accepted: ids.length, categoriesCreated: 0, items: [] }
  }
}

/** 忽略建议。 */
export async function dismissCategorySuggestions(
  ids: string[]
): Promise<{ dismissed: number }> {
  try {
    return await apiFetch<{ dismissed: number }>(
      '/api/category-suggestions/dismiss',
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ids }),
      }
    )
  } catch {
    // eslint-disable-next-line no-console
    console.info('[opensource-factory] 忽略接口不可用，演示模式本地生效')
    return { dismissed: ids.length }
  }
}
