import { apiFetch, fetchWithFallback } from '@/lib/api'

export type ModelRouteTaskKey =
  'summary' | 'embedding' | 'tagging' | 'classification' | 'chat' | 'rerank'

export type ModelRouteStrategy = 'budget' | 'balanced' | 'quality' | 'manual'

export type ModelRouteProvider = 'ollama' | 'deepseek' | 'rules'

export interface ModelRouteModel {
  id: string
  name: string
  provider: ModelRouteProvider
  kind: 'llm' | 'embedding' | 'rules'
  quality: number
  costPer1k: number
  latencyMs: number
  residentMb: number
  quantization: string
  dimension: number | null
  contextTokens: number
  note: string
  withinBudget: boolean
}

export interface ModelRouteUpgrade {
  modelId: string
  modelName: string
  provider: ModelRouteProvider
  quality: number
  residentMb: number
  costPer1k: number
  latencyMs: number
  eligible: boolean
  reason: string
}

export interface ModelRouteTask {
  task: ModelRouteTaskKey
  label: string
  description: string
  strategy: ModelRouteStrategy
  modelId: string
  modelName: string
  provider: ModelRouteProvider
  kind: 'llm' | 'embedding' | 'rules'
  quality: number
  costPer1k: number
  latencyMs: number
  residentMb: number
  quantization: string
  dimension: number | null
  budgetMb: number
  withinBudget: boolean
  reason: string
  fallbackModels: string[]
  candidates: ModelRouteModel[]
  upgrades: ModelRouteUpgrade[]
  updatedBy: string
  updatedAt: string | null
}

export interface ModelRouteOverview {
  budgetMb: number
  peakResidentMb: number
  budgetPercent: number
  withinBudget: boolean
  taskCount: number
  localModelCount: number
  cloudModelCount: number
  ruleModelCount: number
  updatedAt: string | null
  tasks: ModelRouteTask[]
  models: ModelRouteModel[]
}

export interface ModelRouteHealth {
  ollama: {
    configured: boolean
    reachable: boolean
    models: {
      name: string
      sizeMb: number
      sizeVramMb: number
      withinBudget: boolean
    }[]
    peakResidentMb: number
    budgetOk: boolean
    error: string
  }
  deepseek: { configured: boolean; model: string; baseUrl: string }
  rules: { available: boolean }
  budgetMb: number
  checkedAt: string
}

export interface ModelRouteUpdatePayload {
  strategy: ModelRouteStrategy
  modelId?: string | null
  updatedBy?: string
}

export interface ModelRouteAction {
  ok: boolean
  task: string
  modelId: string
  message: string
  route: ModelRouteTask | null
}

export interface ModelRouteReset {
  ok: boolean
  deleted: number
  message: string
}

const MODELS: Record<string, ModelRouteModel> = {
  'local-rules': {
    id: 'local-rules',
    name: '本地规则引擎',
    provider: 'rules',
    kind: 'rules',
    quality: 45,
    costPer1k: 0,
    latencyMs: 5,
    residentMb: 0,
    quantization: 'none',
    dimension: null,
    contextTokens: 0,
    note: '零成本、零模型驻留',
    withinBudget: true,
  },
  'local-heuristic': {
    id: 'local-heuristic',
    name: '本地启发式精排',
    provider: 'rules',
    kind: 'rules',
    quality: 40,
    costPer1k: 0,
    latencyMs: 20,
    residentMb: 0,
    quantization: 'none',
    dimension: null,
    contextTokens: 0,
    note: '为 M7-07 精排预留',
    withinBudget: true,
  },
  'bge-m3-int8': {
    id: 'bge-m3-int8',
    name: 'BAAI/bge-m3',
    provider: 'ollama',
    kind: 'embedding',
    quality: 92,
    costPer1k: 0,
    latencyMs: 60,
    residentMb: 1100,
    quantization: 'int8',
    dimension: 1024,
    contextTokens: 0,
    note: '默认向量模型；1024 维',
    withinBudget: true,
  },
  'bge-small-zh-v1.5': {
    id: 'bge-small-zh-v1.5',
    name: 'BAAI/bge-small-zh-v1.5',
    provider: 'ollama',
    kind: 'embedding',
    quality: 78,
    costPer1k: 0,
    latencyMs: 25,
    residentMb: 300,
    quantization: 'fp32',
    dimension: 512,
    contextTokens: 0,
    note: '低配降级；512 维，切换需重建索引',
    withinBudget: true,
  },
  'bge-m3-fp16': {
    id: 'bge-m3-fp16',
    name: 'BAAI/bge-m3',
    provider: 'ollama',
    kind: 'embedding',
    quality: 93,
    costPer1k: 0,
    latencyMs: 80,
    residentMb: 2300,
    quantization: 'fp16',
    dimension: 1024,
    contextTokens: 0,
    note: '超出 2G 预算',
    withinBudget: false,
  },
  'qwen2.5-1.5b-q4': {
    id: 'qwen2.5-1.5b-q4',
    name: 'qwen2.5:1.5b-instruct-q4_K_M',
    provider: 'ollama',
    kind: 'llm',
    quality: 72,
    costPer1k: 0,
    latencyMs: 1200,
    residentMb: 1300,
    quantization: 'q4_K_M',
    dimension: null,
    contextTokens: 32768,
    note: '默认本地摘要模型',
    withinBudget: true,
  },
  'deepseek-r1-1.5b-q4': {
    id: 'deepseek-r1-1.5b-q4',
    name: 'deepseek-r1:1.5b',
    provider: 'ollama',
    kind: 'llm',
    quality: 78,
    costPer1k: 0,
    latencyMs: 2600,
    residentMb: 1400,
    quantization: 'q4_K_M',
    dimension: null,
    contextTokens: 65536,
    note: '本地推理型备选',
    withinBudget: true,
  },
  'deepseek-chat': {
    id: 'deepseek-chat',
    name: 'deepseek-chat',
    provider: 'deepseek',
    kind: 'llm',
    quality: 90,
    costPer1k: 0.001,
    latencyMs: 1800,
    residentMb: 0,
    quantization: 'cloud',
    dimension: null,
    contextTokens: 65536,
    note: '云端模型；需要 DEEPSEEK_API_KEY',
    withinBudget: true,
  },
  'qwen2.5-3b-q4': {
    id: 'qwen2.5-3b-q4',
    name: 'qwen2.5:3b-instruct-q4_K_M',
    provider: 'ollama',
    kind: 'llm',
    quality: 82,
    costPer1k: 0,
    latencyMs: 2200,
    residentMb: 2200,
    quantization: 'q4_K_M',
    dimension: null,
    contextTokens: 32768,
    note: '超出 2G 预算',
    withinBudget: false,
  },
  'qwen2.5-7b-q4': {
    id: 'qwen2.5-7b-q4',
    name: 'qwen2.5:7b',
    provider: 'ollama',
    kind: 'llm',
    quality: 88,
    costPer1k: 0,
    latencyMs: 5000,
    residentMb: 4700,
    quantization: 'q4_K_M',
    dimension: null,
    contextTokens: 32768,
    note: '超出 2G 预算',
    withinBudget: false,
  },
}

function model(id: string): ModelRouteModel {
  return MODELS[id] as ModelRouteModel
}

function upgrade(
  id: string,
  eligible: boolean,
  reason: string
): ModelRouteUpgrade {
  const item = model(id)
  return {
    modelId: item.id,
    modelName: item.name,
    provider: item.provider,
    quality: item.quality,
    residentMb: item.residentMb,
    costPer1k: item.costPer1k,
    latencyMs: item.latencyMs,
    eligible,
    reason,
  }
}

function task(
  overrides: Pick<
    ModelRouteTask,
    | 'task'
    | 'label'
    | 'description'
    | 'strategy'
    | 'modelId'
    | 'reason'
    | 'candidates'
    | 'upgrades'
    | 'fallbackModels'
  >
): ModelRouteTask {
  const current = model(overrides.modelId)
  return {
    ...overrides,
    modelName: current.name,
    provider: current.provider,
    kind: current.kind,
    quality: current.quality,
    costPer1k: current.costPer1k,
    latencyMs: current.latencyMs,
    residentMb: current.residentMb,
    quantization: current.quantization,
    dimension: current.dimension,
    budgetMb: 2048,
    withinBudget: current.withinBudget,
    updatedBy: '',
    updatedAt: null,
  }
}

export const MOCK_MODEL_ROUTES: ModelRouteOverview = {
  budgetMb: 2048,
  peakResidentMb: 1300,
  budgetPercent: 63,
  withinBudget: true,
  taskCount: 6,
  localModelCount: 7,
  cloudModelCount: 1,
  ruleModelCount: 2,
  updatedAt: null,
  models: Object.values(MODELS),
  tasks: [
    task({
      task: 'summary',
      label: '摘要生成',
      description: 'README 摘要：本地优先，云端作为质量升级',
      strategy: 'budget',
      modelId: 'qwen2.5-1.5b-q4',
      reason:
        '预算优先：qwen2.5:1.5b-instruct-q4_K_M 驻留 1300 MB / 预算 2048 MB',
      fallbackModels: ['deepseek-chat', 'deepseek-r1-1.5b-q4'],
      candidates: [
        model('qwen2.5-1.5b-q4'),
        model('deepseek-r1-1.5b-q4'),
        model('deepseek-chat'),
      ],
      upgrades: [
        upgrade(
          'deepseek-chat',
          true,
          '预算内可升级：质量 72 → 90，云端成本约 $0.0010/千 tokens'
        ),
        upgrade('deepseek-r1-1.5b-q4', true, '预算内可升级：质量 72 → 78'),
        upgrade(
          'qwen2.5-7b-q4',
          false,
          '需将预算提高至 4700 MB（当前 2048 MB）'
        ),
        upgrade(
          'qwen2.5-3b-q4',
          false,
          '需将预算提高至 2200 MB（当前 2048 MB）'
        ),
      ],
    }),
    task({
      task: 'embedding',
      label: '向量化',
      description: 'BGE-M3 默认；切换小模型会改变向量维度',
      strategy: 'quality',
      modelId: 'bge-m3-int8',
      reason: '质量优先：BAAI/bge-m3 质量分 92，驻留 1100 MB / 预算 2048 MB',
      fallbackModels: ['bge-small-zh-v1.5'],
      candidates: [model('bge-m3-int8'), model('bge-small-zh-v1.5')],
      upgrades: [
        upgrade('bge-m3-fp16', false, '需将预算提高至 2300 MB（当前 2048 MB）'),
      ],
    }),
    task({
      task: 'tagging',
      label: '自动打标',
      description: '规则引擎零成本；LLM 为增强选项',
      strategy: 'budget',
      modelId: 'local-rules',
      reason: '预算优先：本地规则引擎驻留 0 MB，零成本',
      fallbackModels: ['deepseek-chat', 'qwen2.5-1.5b-q4'],
      candidates: [
        model('local-rules'),
        model('qwen2.5-1.5b-q4'),
        model('deepseek-chat'),
      ],
      upgrades: [
        upgrade('qwen2.5-1.5b-q4', true, '预算内可升级：质量 45 → 72'),
        upgrade(
          'deepseek-chat',
          true,
          '预算内可升级：质量 45 → 90，云端成本约 $0.0010/千 tokens'
        ),
      ],
    }),
    task({
      task: 'classification',
      label: '自动分类',
      description: '规则引擎零成本；LLM 为增强选项',
      strategy: 'budget',
      modelId: 'local-rules',
      reason: '预算优先：本地规则引擎驻留 0 MB，零成本',
      fallbackModels: ['deepseek-chat', 'qwen2.5-1.5b-q4'],
      candidates: [
        model('local-rules'),
        model('qwen2.5-1.5b-q4'),
        model('deepseek-chat'),
      ],
      upgrades: [
        upgrade('qwen2.5-1.5b-q4', true, '预算内可升级：质量 45 → 72'),
        upgrade(
          'deepseek-chat',
          true,
          '预算内可升级：质量 45 → 90，云端成本约 $0.0010/千 tokens'
        ),
      ],
    }),
    task({
      task: 'chat',
      label: '问答检索',
      description: '质量优先；云端未配置时运行期降级本地',
      strategy: 'quality',
      modelId: 'deepseek-chat',
      reason: '质量优先：deepseek-chat 质量分 90，驻留 0 MB / 预算 2048 MB',
      fallbackModels: ['deepseek-r1-1.5b-q4', 'qwen2.5-1.5b-q4'],
      candidates: [
        model('deepseek-chat'),
        model('qwen2.5-1.5b-q4'),
        model('deepseek-r1-1.5b-q4'),
      ],
      upgrades: [],
    }),
    task({
      task: 'rerank',
      label: '精排',
      description: '为 M7-07 预留的路由位；当前使用本地启发式',
      strategy: 'budget',
      modelId: 'local-heuristic',
      reason: '预算优先：本地启发式精排驻留 0 MB，零成本',
      fallbackModels: ['deepseek-chat', 'qwen2.5-1.5b-q4'],
      candidates: [
        model('local-heuristic'),
        model('qwen2.5-1.5b-q4'),
        model('deepseek-chat'),
      ],
      upgrades: [
        upgrade('qwen2.5-1.5b-q4', true, '预算内可升级：质量 40 → 72'),
        upgrade(
          'deepseek-chat',
          true,
          '预算内可升级：质量 40 → 90，云端成本约 $0.0010/千 tokens'
        ),
      ],
    }),
  ],
}

export const MOCK_MODEL_ROUTE_HEALTH: ModelRouteHealth = {
  ollama: {
    configured: true,
    reachable: true,
    models: [
      {
        name: 'qwen2.5:1.5b-instruct-q4_K_M',
        sizeMb: 1300,
        sizeVramMb: 0,
        withinBudget: true,
      },
    ],
    peakResidentMb: 1300,
    budgetOk: true,
    error: '',
  },
  deepseek: {
    configured: true,
    model: 'deepseek-chat',
    baseUrl: 'https://api.deepseek.com',
  },
  rules: { available: true },
  budgetMb: 2048,
  checkedAt: new Date(0).toISOString(),
}

export function fetchModelRoutes(): Promise<ModelRouteOverview> {
  return fetchWithFallback('/api/model-routes', MOCK_MODEL_ROUTES)
}

export function fetchModelRouteHealth(): Promise<ModelRouteHealth> {
  return fetchWithFallback('/api/model-routes/health', MOCK_MODEL_ROUTE_HEALTH)
}

export function updateModelRoute(
  taskKey: ModelRouteTaskKey,
  payload: ModelRouteUpdatePayload
): Promise<ModelRouteTask> {
  return apiFetch<ModelRouteTask>(`/api/model-routes/${taskKey}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

export function resetModelRoute(
  taskKey: ModelRouteTaskKey
): Promise<ModelRouteReset> {
  return apiFetch<ModelRouteReset>(`/api/model-routes/${taskKey}`, {
    method: 'DELETE',
  })
}

export function resetAllModelRoutes(): Promise<ModelRouteReset> {
  return apiFetch<ModelRouteReset>('/api/model-routes/reset', {
    method: 'POST',
  })
}

export function applyModelUpgrade(
  taskKey: ModelRouteTaskKey
): Promise<ModelRouteAction> {
  return apiFetch<ModelRouteAction>('/api/model-routes/upgrade', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ task: taskKey }),
  })
}
