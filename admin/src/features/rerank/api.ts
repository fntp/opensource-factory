import { apiFetch, DEMO_MODE } from '@/lib/api'

export interface RerankWeights {
  relevance: number
  affinity: number
  freshness: number
  momentum: number
  popularity: number
  health: number
}

export interface RerankItem {
  repoId: string
  name: string
  htmlUrl: string
  language: string
  baseScore: number
  rerankScore: number
  rankBefore: number
  rankAfter: number
  signals: Record<string, number>
  contributions: Record<string, number>
  reasons: string[]
  diversityPenalty: number
}

export interface RerankMetrics {
  total: number
  selected: number
  movedUp: number
  movedDown: number
  unchanged: number
  avgRankShift: number
  diversityBefore: number
  diversityAfter: number
  languageCoverage: number
}

export interface RerankResult {
  status: string
  mode: 'vps' | 'local'
  userId: string
  generatedAt: string
  weights: RerankWeights
  mmrLambda: number
  metrics: RerankMetrics
  items: RerankItem[]
  applied: boolean
}

export interface RerankParams {
  topK?: number
  poolSize?: number
  mmrLambda?: number
  weights?: Partial<RerankWeights>
}

export const DEFAULT_RERANK_WEIGHTS: RerankWeights = {
  relevance: 0.45,
  affinity: 0.15,
  freshness: 0.12,
  momentum: 0.1,
  popularity: 0.08,
  health: 0.1,
}

export const MOCK_RERANK_RESULT: RerankResult = {
  status: 'ok',
  mode: 'local',
  userId: 'demo',
  generatedAt: '2026-10-22T08:30:00Z',
  weights: DEFAULT_RERANK_WEIGHTS,
  mmrLambda: 0.75,
  metrics: {
    total: 5,
    selected: 4,
    movedUp: 2,
    movedDown: 1,
    unchanged: 1,
    avgRankShift: 1.25,
    diversityBefore: 0.32,
    diversityAfter: 0.58,
    languageCoverage: 0.75,
  },
  items: [
    {
      repoId: 'huggingface/transformers',
      name: 'transformers',
      htmlUrl: 'https://github.com/huggingface/transformers',
      language: 'Python',
      baseScore: 0.86,
      rerankScore: 0.91,
      rankBefore: 2,
      rankAfter: 1,
      signals: {
        relevance: 0.86,
        affinity: 0.9,
        freshness: 0.78,
        momentum: 0.82,
        popularity: 0.95,
        health: 0.8,
      },
      contributions: {
        relevance: 0.387,
        affinity: 0.135,
        freshness: 0.094,
        momentum: 0.082,
        popularity: 0.076,
        health: 0.08,
      },
      reasons: ['与你收藏方向语义相关', '语言 / 技术栈与你的收藏高度重合', '社区关注度高'],
      diversityPenalty: 0,
    },
    {
      repoId: 'astral-sh/ruff',
      name: 'ruff',
      htmlUrl: 'https://github.com/astral-sh/ruff',
      language: 'Rust',
      baseScore: 0.88,
      rerankScore: 0.84,
      rankBefore: 1,
      rankAfter: 2,
      signals: {
        relevance: 0.88,
        affinity: 0.2,
        freshness: 0.9,
        momentum: 0.7,
        popularity: 0.6,
        health: 0.9,
      },
      contributions: {
        relevance: 0.396,
        affinity: 0.03,
        freshness: 0.108,
        momentum: 0.07,
        popularity: 0.048,
        health: 0.09,
      },
      reasons: ['与你收藏方向语义相关', '近期仍有活跃提交', '项目元数据完整、维护状态良好'],
      diversityPenalty: 0.02,
    },
    {
      repoId: 'modelcontextprotocol/servers',
      name: 'servers',
      htmlUrl: 'https://github.com/modelcontextprotocol/servers',
      language: 'TypeScript',
      baseScore: 0.72,
      rerankScore: 0.77,
      rankBefore: 4,
      rankAfter: 3,
      signals: {
        relevance: 0.72,
        affinity: 0.7,
        freshness: 0.95,
        momentum: 0.88,
        popularity: 0.55,
        health: 0.7,
      },
      contributions: {
        relevance: 0.324,
        affinity: 0.105,
        freshness: 0.114,
        momentum: 0.088,
        popularity: 0.044,
        health: 0.07,
      },
      reasons: ['今日热度快速上升', '近期仍有活跃提交', '语言 / 技术栈与你的收藏高度重合'],
      diversityPenalty: 0,
    },
    {
      repoId: 'vercel/next.js',
      name: 'next.js',
      htmlUrl: 'https://github.com/vercel/next.js',
      language: 'JavaScript',
      baseScore: 0.7,
      rerankScore: 0.68,
      rankBefore: 3,
      rankAfter: 4,
      signals: {
        relevance: 0.7,
        affinity: 0.3,
        freshness: 0.6,
        momentum: 0.5,
        popularity: 0.9,
        health: 0.8,
      },
      contributions: {
        relevance: 0.315,
        affinity: 0.045,
        freshness: 0.072,
        momentum: 0.05,
        popularity: 0.072,
        health: 0.08,
      },
      reasons: ['与你收藏方向语义相关', '社区关注度高'],
      diversityPenalty: 0.06,
    },
  ],
  applied: false,
}

function demoResult(params: RerankParams, applied: boolean): RerankResult {
  return {
    ...MOCK_RERANK_RESULT,
    weights: { ...DEFAULT_RERANK_WEIGHTS, ...params.weights },
    mmrLambda: params.mmrLambda ?? MOCK_RERANK_RESULT.mmrLambda,
    generatedAt: new Date().toISOString(),
    applied,
  }
}

/** 精排预览：不写库，返回精排前后名次与信号。 */
export async function fetchRerankPreview(params: RerankParams = {}): Promise<RerankResult> {
  try {
    return await apiFetch<RerankResult>('/api/rerank/preview', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(params),
    })
  } catch (error) {
    if (DEMO_MODE) {
      // eslint-disable-next-line no-console
      console.info('[opensource-factory] 精排接口不可用，使用演示数据')
      return demoResult(params, false)
    }
    throw error
  }
}

/** 应用精排：写回推荐分与名次。 */
export async function applyRerank(params: RerankParams = {}): Promise<RerankResult> {
  try {
    return await apiFetch<RerankResult>('/api/rerank/apply', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(params),
    })
  } catch (error) {
    if (DEMO_MODE) {
      return demoResult(params, true)
    }
    throw error
  }
}
