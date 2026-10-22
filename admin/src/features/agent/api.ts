import { API_BASE, apiFetch, DEMO_MODE, fetchWithFallback } from '@/lib/api'

export type AgentTemplate = 'organize' | 'draft' | 'full'
export type AgentMode = 'preview' | 'apply'
export type AgentRunStatus = 'completed' | 'failed'
export type AgentDraftStatus = 'draft' | 'applied' | 'discarded'

export interface AgentTemplateDefinition {
  key: AgentTemplate
  title: string
  description: string
  defaultMode: AgentMode
  defaultThreshold: number
}

export interface AgentPlanStep {
  key: string
  title: string
  detail: string
  count: number
  status: 'ready' | 'skipped'
}

export interface AgentAction {
  kind: 'tag' | 'category'
  repoId: string
  value: string
  score: number
  reason: string
}

export interface AgentStats {
  totalRepos: number
  totalStars: number
  categoryCount: number
  languageCount: number
  tagCount: number
  topLanguage: string | null
  topCategory: string | null
}

export interface AgentRunResult {
  appliedTags: AgentAction[]
  appliedCategories: AgentAction[]
  pendingTags: number
  pendingCategories: number
  stats: AgentStats
  source: 'vps' | 'local'
}

export interface AgentDraftMetadata {
  highlights: string[]
  stats: AgentStats
  template: AgentTemplate
  mode: AgentMode
  focus: string | null
}

export interface AgentDraft {
  id: string
  runId: string | null
  kind: string
  title: string
  content: string
  status: AgentDraftStatus
  metadata: AgentDraftMetadata
  createdAt: string
  updatedAt: string
}

export interface AgentRunSummary {
  id: string
  template: AgentTemplate
  mode: AgentMode
  status: AgentRunStatus
  threshold: number
  repoCount: number
  draftId: string | null
  createdAt: string
  finishedAt: string | null
  error: string | null
}

export interface AgentRunDetail extends AgentRunSummary {
  plan: AgentPlanStep[]
  result: AgentRunResult
  draft: AgentDraft | null
}

export interface AgentRunListResponse {
  items: AgentRunSummary[]
  total: number
}

export interface AgentDraftListResponse {
  items: AgentDraft[]
  total: number
}

export interface AgentTemplateResponse {
  items: AgentTemplateDefinition[]
  defaults: { mode: AgentMode; threshold: number; limit: number }
}

export interface CreateAgentRunInput {
  template: AgentTemplate
  mode: AgentMode
  threshold: number
  focus?: string | null
}

export const MOCK_AGENT_TEMPLATES: AgentTemplateDefinition[] = [
  {
    key: 'organize',
    title: '自动整理',
    description: '汇总待处理的标签 / 分类建议，按阈值生成整理计划，可选择直接应用。',
    defaultMode: 'preview',
    defaultThreshold: 0.75,
  },
  {
    key: 'draft',
    title: '收藏草稿',
    description: '基于当前收藏、分类与标签，生成一份可编辑的 Markdown 精选草稿。',
    defaultMode: 'preview',
    defaultThreshold: 0.75,
  },
  {
    key: 'full',
    title: '整理 + 草稿',
    description: '先整理标签 / 分类，再把本次变更写进收藏草稿，一次完成维护与输出。',
    defaultMode: 'apply',
    defaultThreshold: 0.75,
  },
]

const MOCK_STATS: AgentStats = {
  totalRepos: 24,
  totalStars: 624900,
  categoryCount: 6,
  languageCount: 7,
  tagCount: 18,
  topLanguage: 'TypeScript',
  topCategory: 'AI 工具',
}

const MOCK_PLAN: AgentPlanStep[] = [
  {
    key: 'inventory',
    title: '盘点收藏',
    detail: '扫描 24 个收藏仓库，读取分类、标签与摘要覆盖。',
    count: 24,
    status: 'ready',
  },
  {
    key: 'tags',
    title: '整理标签',
    detail: '3 条标签建议达到阈值 0.75，将写入 tags / repo_tags。',
    count: 3,
    status: 'ready',
  },
  {
    key: 'categories',
    title: '整理分类',
    detail: '1 条分类建议达到阈值 0.75，将写入仓库分类。',
    count: 1,
    status: 'ready',
  },
  {
    key: 'draft',
    title: '生成草稿',
    detail: '基于 24 个收藏生成一份可编辑的 Markdown 精选草稿。',
    count: 24,
    status: 'ready',
  },
]

const MOCK_MARKDOWN = `# 我的开源收藏精选 · 2026-10-22

> 由 OpenFactory Agent 基于 24 个收藏生成于 2026-10-22；模板 \`full\`，可在发布前自由编辑。

## 概览

- 收藏总数：24
- Star 合计：62.5 万
- 分类数：6
- 语言数：7
- 标签数：18

## 本期亮点

1. **langgenius/dify** — 开源 LLM 应用开发平台，可视化编排 Agent 与工作流。
2. **open-webui/open-webui** — 自托管的大模型对话界面，支持 Ollama 与 OpenAI 兼容接口。
3. **astral-sh/uv** — 用 Rust 编写的极速 Python 包与环境管理器。

## 分类精选

### AI 工具（8）

- [langgenius/dify](https://github.com/langgenius/dify) — 开源 LLM 应用开发平台（TypeScript · ⭐ 12.8 万） #llm #agent
- [open-webui/open-webui](https://github.com/open-webui/open-webui) — 自托管大模型对话界面（Svelte · ⭐ 8.6 万） #llm #self-hosted

### 开发工具（6）

- [astral-sh/uv](https://github.com/astral-sh/uv) — 极速 Python 包管理器（Rust · ⭐ 4.8 万） #python #cli

## 本次整理

- 应用标签建议 3 条
- 应用分类建议 1 条

## 发布清单

- [ ] 核对项目描述与链接
- [ ] 补充一段个人点评
- [ ] 选择发布渠道（博客 / 周报 / 社群）
`

export const MOCK_AGENT_RUN: AgentRunDetail = {
  id: 'run_demo_20261022',
  template: 'full',
  mode: 'apply',
  status: 'completed',
  threshold: 0.75,
  repoCount: 24,
  draftId: 'draft_demo_20261022',
  createdAt: '2026-10-22T08:30:00.000Z',
  finishedAt: '2026-10-22T08:30:01.000Z',
  error: null,
  plan: MOCK_PLAN,
  result: {
    appliedTags: [
      {
        kind: 'tag',
        repoId: 'langgenius/dify',
        value: 'agent',
        score: 0.93,
        reason: '描述命中 Agent 关键词',
      },
      {
        kind: 'tag',
        repoId: 'open-webui/open-webui',
        value: 'llm',
        score: 0.88,
        reason: '分类与标签共现',
      },
      {
        kind: 'tag',
        repoId: 'astral-sh/uv',
        value: 'python',
        score: 0.86,
        reason: '语言与描述匹配',
      },
    ],
    appliedCategories: [
      {
        kind: 'category',
        repoId: 'langgenius/dify',
        value: 'AI 工具',
        score: 0.91,
        reason: '与 AI 工具分类高度相似',
      },
    ],
    pendingTags: 3,
    pendingCategories: 1,
    stats: MOCK_STATS,
    source: 'vps',
  },
  draft: {
    id: 'draft_demo_20261022',
    runId: 'run_demo_20261022',
    kind: 'collection_digest',
    title: '我的开源收藏精选 · 2026-10-22',
    content: MOCK_MARKDOWN,
    status: 'draft',
    metadata: {
      highlights: [
        '收藏 24 个项目，累计 62.5 万 Star',
        '覆盖 6 个分类、7 种语言',
        '整理动作：标签 3 条、分类 1 条',
      ],
      stats: MOCK_STATS,
      template: 'full',
      mode: 'apply',
      focus: null,
    },
    createdAt: '2026-10-22T08:30:00.000Z',
    updatedAt: '2026-10-22T08:30:00.000Z',
  },
}

const MOCK_OLDER_RUN: AgentRunSummary = {
  id: 'run_demo_20261015',
  template: 'draft',
  mode: 'preview',
  status: 'completed',
  threshold: 0.75,
  repoCount: 21,
  draftId: 'draft_demo_20261015',
  createdAt: '2026-10-15T09:00:00.000Z',
  finishedAt: '2026-10-15T09:00:01.000Z',
  error: null,
}

const MOCK_DRAFT: AgentDraft = MOCK_AGENT_RUN.draft as AgentDraft

const MOCK_OLDER_DRAFT: AgentDraft = {
  ...MOCK_DRAFT,
  id: 'draft_demo_20261015',
  runId: 'run_demo_20261015',
  title: '我的开源收藏精选 · 2026-10-15',
  status: 'applied',
  createdAt: '2026-10-15T09:00:00.000Z',
  updatedAt: '2026-10-15T10:20:00.000Z',
}

export function fetchAgentTemplates(): Promise<AgentTemplateResponse> {
  return fetchWithFallback<AgentTemplateResponse>('/api/agent/templates', {
    items: MOCK_AGENT_TEMPLATES,
    defaults: { mode: 'preview', threshold: 0.75, limit: 200 },
  })
}

export function fetchAgentRuns(): Promise<AgentRunListResponse> {
  return fetchWithFallback<AgentRunListResponse>('/api/agent/runs', {
    items: [MOCK_AGENT_RUN, MOCK_OLDER_RUN],
    total: 2,
  })
}

export function fetchAgentRun(id: string): Promise<AgentRunDetail> {
  const fallback = id === MOCK_AGENT_RUN.id ? MOCK_AGENT_RUN : { ...MOCK_AGENT_RUN, ...MOCK_OLDER_RUN, plan: MOCK_PLAN, result: MOCK_AGENT_RUN.result, draft: MOCK_OLDER_DRAFT }
  return fetchWithFallback<AgentRunDetail>(`/api/agent/runs/${encodeURIComponent(id)}`, fallback)
}

export function fetchAgentDrafts(): Promise<AgentDraftListResponse> {
  return fetchWithFallback<AgentDraftListResponse>('/api/agent/drafts', {
    items: [MOCK_DRAFT, MOCK_OLDER_DRAFT],
    total: 2,
  })
}

export async function createAgentRun(input: CreateAgentRunInput): Promise<AgentRunDetail> {
  if (DEMO_MODE) {
    return {
      ...MOCK_AGENT_RUN,
      template: input.template,
      mode: input.mode,
      threshold: input.threshold,
      draft: MOCK_AGENT_RUN.draft
        ? {
            ...MOCK_AGENT_RUN.draft,
            metadata: { ...MOCK_AGENT_RUN.draft.metadata, template: input.template, mode: input.mode },
          }
        : null,
    }
  }
  return apiFetch<AgentRunDetail>('/api/agent/runs', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  })
}

export async function updateAgentDraftStatus(
  id: string,
  status: Exclude<AgentDraftStatus, 'draft'>
): Promise<AgentDraft> {
  if (DEMO_MODE) {
    return { ...MOCK_DRAFT, id, status }
  }
  return apiFetch<AgentDraft>(`/api/agent/drafts/${encodeURIComponent(id)}/status`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ status }),
  })
}

function triggerDownload(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  URL.revokeObjectURL(url)
}

export function downloadAgentDraft(draft: AgentDraft): void {
  triggerDownload(
    new Blob([draft.content], { type: 'text/markdown;charset=utf-8' }),
    `${draft.id}.md`
  )
}

export { API_BASE }
