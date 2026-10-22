import { apiFetch } from '@/lib/api'
import type {
  DuplicateCluster,
  DuplicateDismissal,
  DuplicateScanResponse,
  DuplicateScope,
} from './utils'

export type {
  DuplicateCluster,
  DuplicateDismissal,
  DuplicateFieldSuggestion,
  DuplicateKind,
  DuplicateMember,
  DuplicateScanResponse,
  DuplicateScope,
  DuplicateSuggestion,
} from './utils'

export interface DuplicateScanRequest {
  scope: DuplicateScope
  minScore?: number
  maxClusters?: number
}

export interface DismissDuplicateRequest {
  clusterId: string
  repoIds?: string[]
  reason?: string
}

function mockMember(
  source: 'my' | 'trending',
  repoId: string,
  name: string,
  description: string,
  stars: number,
  language: string,
  role: 'canonical' | 'merge',
  extra: Partial<DuplicateCluster['members'][number]> = {}
): DuplicateCluster['members'][number] {
  return {
    source,
    repoId,
    fullName: repoId,
    name,
    description,
    language,
    stars,
    url: `https://github.com/${repoId}`,
    platform: 'github',
    categoryId: '',
    readmeSummary: '',
    techStack: [],
    role,
    signals: {
      nameSimilarity: 0.94,
      descriptionSimilarity: 0.82,
      vectorSimilarity: null,
      exactKey: false,
    },
    ...extra,
  }
}

export const MOCK_DUPLICATE_CLUSTERS: DuplicateCluster[] = [
  {
    id: 'dup_demo_exact',
    kind: 'exact',
    confidence: 1,
    reasons: [
      '仓库地址归一化后完全一致（同一项目）',
      '同一项目同时出现在收藏库与热榜',
    ],
    members: [
      mockMember(
        'my',
        'demo/tenant-admin',
        'tenant-admin',
        '支持多租户的 NestJS 管理后台模板',
        356,
        'TypeScript',
        'canonical',
        { categoryId: 'admin', techStack: ['NestJS', 'React'] }
      ),
      mockMember(
        'trending',
        'demo/tenant-admin',
        'tenant-admin',
        '多租户 SaaS 后台模板，内置计费、权限与审计',
        2100,
        'TypeScript',
        'merge',
        { techStack: ['NestJS', 'PostgreSQL'] }
      ),
    ],
    suggestion: {
      action: 'merge',
      keep: { source: 'my', repoId: 'demo/tenant-admin' },
      mergeTargets: [{ source: 'trending', repoId: 'demo/tenant-admin' }],
      fields: [
        {
          field: 'description',
          value: '多租户 SaaS 后台模板，内置计费、权限与审计',
          from: { source: 'trending', repoId: 'demo/tenant-admin' },
          reason: '取最完整的项目简介',
        },
        {
          field: 'stars',
          value: 2100,
          from: { source: 'trending', repoId: 'demo/tenant-admin' },
          reason: '取最大的 Star 数',
        },
        {
          field: 'techStack',
          value: ['NestJS', 'React', 'PostgreSQL'],
          from: { source: 'my', repoId: 'demo/tenant-admin' },
          reason: '合并技术栈标签',
        },
      ],
      notes:
        '收藏库与热榜命中同一项目，建议保留收藏库条目，将热榜的摘要 / 技术栈并入后归档。',
    },
  },
  {
    id: 'dup_demo_name',
    kind: 'name',
    confidence: 0.93,
    reasons: ['仓库名相似度 93%', '项目简介相似度 78%'],
    members: [
      mockMember(
        'my',
        'demo/saas-starter',
        'saas-starter',
        '多租户 SaaS 启动模板，内置计费与权限',
        2100,
        'TypeScript',
        'canonical',
        { techStack: ['Next.js', 'Prisma'] }
      ),
      mockMember(
        'my',
        'demo/saas_starter',
        'saas_starter',
        '多租户 SaaS 启动模板（含计费与权限）',
        180,
        'TypeScript',
        'merge',
        { techStack: ['Next.js', 'Drizzle'] }
      ),
    ],
    suggestion: {
      action: 'merge',
      keep: { source: 'my', repoId: 'demo/saas-starter' },
      mergeTargets: [{ source: 'my', repoId: 'demo/saas_starter' }],
      fields: [
        {
          field: 'techStack',
          value: ['Next.js', 'Prisma', 'Drizzle'],
          from: { source: 'my', repoId: 'demo/saas_starter' },
          reason: '合并技术栈标签',
        },
      ],
      notes: '建议保留元数据更完整的条目，合并其余重复项后归档。',
    },
  },
  {
    id: 'dup_demo_semantic',
    kind: 'semantic',
    confidence: 0.86,
    reasons: ['项目简介相似度 81%', '向量余弦相似度 91%'],
    members: [
      mockMember(
        'my',
        'demo/edge-cache',
        'edge-cache',
        '面向 Cloudflare Workers 的边缘缓存中间件，支持标签失效',
        88,
        'TypeScript',
        'canonical'
      ),
      mockMember(
        'trending',
        'demo/workers-cache',
        'workers-cache',
        'Workers 边缘缓存工具，支持按标签批量失效与预热',
        640,
        'TypeScript',
        'merge',
        { techStack: ['Cloudflare Workers'] }
      ),
    ],
    suggestion: {
      action: 'review',
      keep: { source: 'my', repoId: 'demo/edge-cache' },
      mergeTargets: [{ source: 'trending', repoId: 'demo/workers-cache' }],
      fields: [],
      notes: '当前置信度 86%，请人工确认后再合并。',
    },
  },
]

export const MOCK_DUPLICATE_RESPONSE: DuplicateScanResponse = {
  scanId: 'dup_demo',
  scope: 'all',
  mode: 'vps',
  count: MOCK_DUPLICATE_CLUSTERS.length,
  scanned: 128,
  compared: 8128,
  tookMs: 46,
  thresholds: {
    minScore: 0.7,
    nameThreshold: 0.86,
    descriptionThreshold: 0.75,
    vectorThreshold: 0.88,
    maxRepos: 500,
    maxClusters: 50,
  },
  dismissedCount: 0,
  clusters: MOCK_DUPLICATE_CLUSTERS,
}

/** 扫描重复项目；接口不可用时回退演示数据，保证页面可预览。 */
export async function scanDuplicates(
  input: DuplicateScanRequest
): Promise<DuplicateScanResponse> {
  try {
    return await apiFetch<DuplicateScanResponse>('/api/duplicates/scan', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        scope: input.scope,
        ...(input.minScore === undefined ? {} : { minScore: input.minScore }),
        ...(input.maxClusters === undefined
          ? {}
          : { maxClusters: input.maxClusters }),
      }),
    })
  } catch {
    // eslint-disable-next-line no-console
    console.info('[opensource-factory] 重复检测接口不可用，使用演示数据')
    return {
      ...MOCK_DUPLICATE_RESPONSE,
      scope: input.scope,
      count: MOCK_DUPLICATE_CLUSTERS.length,
      clusters: MOCK_DUPLICATE_CLUSTERS,
    }
  }
}

/** 忽略一个重复簇（按用户存 D1）。演示模式 / 接口不可用时本地视为成功。 */
export async function dismissDuplicate(
  input: DismissDuplicateRequest
): Promise<{ dismissed: boolean; clusterId: string }> {
  try {
    return await apiFetch<{ dismissed: boolean; clusterId: string }>(
      '/api/duplicates/dismiss',
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          clusterId: input.clusterId,
          ...(input.repoIds === undefined ? {} : { repoIds: input.repoIds }),
          ...(input.reason === undefined ? {} : { reason: input.reason }),
        }),
      }
    )
  } catch {
    // eslint-disable-next-line no-console
    console.info('[opensource-factory] 忽略接口不可用，演示模式本地生效')
    return { dismissed: true, clusterId: input.clusterId }
  }
}

/** 已忽略列表。 */
export async function fetchDismissedDuplicates(): Promise<{
  count: number
  items: DuplicateDismissal[]
}> {
  return await apiFetch<{ count: number; items: DuplicateDismissal[] }>(
    '/api/duplicates/dismissed'
  )
}

/** 恢复（取消忽略）。 */
export async function restoreDuplicate(
  clusterId: string
): Promise<{ removed: boolean; clusterId: string }> {
  return await apiFetch<{ removed: boolean; clusterId: string }>(
    `/api/duplicates/dismiss/${encodeURIComponent(clusterId)}`,
    { method: 'DELETE' }
  )
}
