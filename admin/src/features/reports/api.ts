import { API_BASE, apiFetch, DEMO_MODE, fetchWithFallback } from '@/lib/api'

export type ReportKind = 'weekly' | 'monthly'
export type ReportStatus = 'ready' | 'empty'
export type ReportItemSource = 'collection' | 'recommendation' | 'trending'

export interface ReportStats {
  totalRepos: number
  newRepos: number
  totalStars: number
  newStars: number
  categoryCount: number
  languageCount: number
  recommendationCount: number
  trendingCount: number
  topLanguage: string | null
  topCategory: string | null
}

export interface ReportItem {
  id: string
  name: string
  url: string
  description: string | null
  language: string | null
  stars: number
  starsDelta: number
  reason: string | null
  source: ReportItemSource
  category: string | null
  tags: string[]
}

export interface ReportSection {
  key: 'new' | 'top' | 'recommendations' | 'trending'
  title: string
  description: string
  items: ReportItem[]
}

export interface ReportSummary {
  id: string
  kind: ReportKind
  title: string
  periodStart: string
  periodEnd: string
  status: ReportStatus
  summary: string
  stats: ReportStats
  generatedAt: string
}

export interface CuratedReport extends ReportSummary {
  sections: ReportSection[]
  markdown: string
}

export interface ReportListResponse {
  items: ReportSummary[]
  total: number
}

const MOCK_WEEKLY_REPORT: CuratedReport = {
  id: 'rpt_weekly_demo_20261019',
  kind: 'weekly',
  title: '每周精选报告 · 10-19 ~ 10-25',
  periodStart: '2026-10-19',
  periodEnd: '2026-10-25',
  status: 'ready',
  summary:
    '本周新增 3 个收藏（+2,840 Star）；当前共收藏 24 个项目、累计 62.5 万 Star；为你精选 4 个推荐；捕捉 3 个热榜项目。',
  stats: {
    totalRepos: 24,
    newRepos: 3,
    totalStars: 624900,
    newStars: 2840,
    categoryCount: 6,
    languageCount: 7,
    recommendationCount: 4,
    trendingCount: 3,
    topLanguage: 'TypeScript',
    topCategory: 'AI 工具',
  },
  generatedAt: '2026-10-26T00:30:00.000Z',
  sections: [
    {
      key: 'new',
      title: '本期新增收藏',
      description: '本周期加入收藏库的项目，按 Star 排序。',
      items: [
        {
          id: 'langgenius/dify',
          name: 'langgenius/dify',
          url: 'https://github.com/langgenius/dify',
          description: '开源 LLM 应用开发平台，可视化编排 Agent 与工作流。',
          language: 'TypeScript',
          stars: 128400,
          starsDelta: 0,
          reason: null,
          source: 'collection',
          category: 'AI 工具',
          tags: ['llm', 'agent'],
        },
        {
          id: 'open-webui/open-webui',
          name: 'open-webui/open-webui',
          url: 'https://github.com/open-webui/open-webui',
          description: '自托管的大模型对话界面，支持 Ollama 与 OpenAI 兼容接口。',
          language: 'Svelte',
          stars: 86400,
          starsDelta: 0,
          reason: null,
          source: 'collection',
          category: 'AI 工具',
          tags: ['llm', 'self-hosted'],
        },
        {
          id: 'astral-sh/uv',
          name: 'astral-sh/uv',
          url: 'https://github.com/astral-sh/uv',
          description: '用 Rust 编写的极速 Python 包与环境管理器。',
          language: 'Rust',
          stars: 48200,
          starsDelta: 0,
          reason: null,
          source: 'collection',
          category: '开发工具',
          tags: ['python', 'cli'],
        },
      ],
    },
    {
      key: 'top',
      title: '收藏库之星',
      description: '当前收藏中 Star 最高的项目，值得回看。',
      items: [
        {
          id: 'vercel/next.js',
          name: 'vercel/next.js',
          url: 'https://github.com/vercel/next.js',
          description: 'React 全栈框架，支持服务端渲染与静态生成。',
          language: 'JavaScript',
          stars: 132000,
          starsDelta: 0,
          reason: null,
          source: 'collection',
          category: '前端框架',
          tags: ['react', 'ssr'],
        },
        {
          id: 'langgenius/dify',
          name: 'langgenius/dify',
          url: 'https://github.com/langgenius/dify',
          description: '开源 LLM 应用开发平台，可视化编排 Agent 与工作流。',
          language: 'TypeScript',
          stars: 128400,
          starsDelta: 0,
          reason: null,
          source: 'collection',
          category: 'AI 工具',
          tags: ['llm', 'agent'],
        },
      ],
    },
    {
      key: 'recommendations',
      title: '推荐关注',
      description: '结合你的收藏与偏好生成的推荐。',
      items: [
        {
          id: 'All-Hands-AI/OpenHands',
          name: 'All-Hands-AI/OpenHands',
          url: 'https://github.com/All-Hands-AI/OpenHands',
          description: '开源的 AI 软件工程助手，可自主完成编码任务。',
          language: 'Python',
          stars: 56200,
          starsDelta: 0,
          reason: '与你收藏的 AI Agent 项目技术栈相近，质量分 0.92。',
          source: 'recommendation',
          category: null,
          tags: [],
        },
        {
          id: 'modelcontextprotocol/servers',
          name: 'modelcontextprotocol/servers',
          url: 'https://github.com/modelcontextprotocol/servers',
          description: 'MCP 官方服务器集合，为模型提供文件、搜索等工具能力。',
          language: 'TypeScript',
          stars: 39400,
          starsDelta: 0,
          reason: '你收藏了多个 LLM 工具项目，MCP 生态值得跟进。',
          source: 'recommendation',
          category: null,
          tags: [],
        },
      ],
    },
    {
      key: 'trending',
      title: '热榜精选',
      description: '本周期 Star 增长最快的开源项目。',
      items: [
        {
          id: 'deepseek-ai/DeepSeek-V3',
          name: 'deepseek-ai/DeepSeek-V3',
          url: 'https://github.com/deepseek-ai/DeepSeek-V3',
          description: '开源大语言模型，推理与代码能力突出。',
          language: 'Python',
          stars: 98200,
          starsDelta: 12400,
          reason: null,
          source: 'trending',
          category: null,
          tags: [],
        },
        {
          id: 'astral-sh/ruff',
          name: 'astral-sh/ruff',
          url: 'https://github.com/astral-sh/ruff',
          description: '极快的 Python linter 与格式化工具。',
          language: 'Rust',
          stars: 42600,
          starsDelta: 3800,
          reason: null,
          source: 'trending',
          category: null,
          tags: [],
        },
      ],
    },
  ],
  markdown: `# 每周精选报告 · 10-19 ~ 10-25

> 周期：2026-10-19 ~ 2026-10-25（UTC）｜生成时间：2026-10-26T00:30:00.000Z

本周新增 3 个收藏（+2,840 Star）；当前共收藏 24 个项目、累计 62.5 万 Star；为你精选 4 个推荐；捕捉 3 个热榜项目。

## 数据概览

- 收藏总数：24
- 本期新增收藏：3
- Star 合计：624,900
- 本期新增 Star：2,840
- 分类 / 语言：6 / 7
- 推荐 / 热榜：4 / 3

## 本期新增收藏

1. [langgenius/dify](https://github.com/langgenius/dify) — ⭐ 128,400 · TypeScript · AI 工具
2. [open-webui/open-webui](https://github.com/open-webui/open-webui) — ⭐ 86,400 · Svelte · AI 工具
3. [astral-sh/uv](https://github.com/astral-sh/uv) — ⭐ 48,200 · Rust · 开发工具
`,
}

const MOCK_MONTHLY_REPORT: CuratedReport = {
  id: 'rpt_monthly_demo_202609',
  kind: 'monthly',
  title: '月度精选报告 · 2026 年 09 月',
  periodStart: '2026-09-01',
  periodEnd: '2026-09-30',
  status: 'ready',
  summary:
    '本月新增 9 个收藏（+18,600 Star）；当前共收藏 21 个项目、累计 58.7 万 Star；为你精选 6 个推荐；捕捉 8 个热榜项目。',
  stats: {
    totalRepos: 21,
    newRepos: 9,
    totalStars: 587300,
    newStars: 18600,
    categoryCount: 5,
    languageCount: 6,
    recommendationCount: 6,
    trendingCount: 8,
    topLanguage: 'TypeScript',
    topCategory: 'AI 工具',
  },
  generatedAt: '2026-10-01T00:40:00.000Z',
  sections: [
    {
      key: 'new',
      title: '本期新增收藏',
      description: '本周期加入收藏库的项目，按 Star 排序。',
      items: [
        {
          id: 'langgenius/dify',
          name: 'langgenius/dify',
          url: 'https://github.com/langgenius/dify',
          description: '开源 LLM 应用开发平台，可视化编排 Agent 与工作流。',
          language: 'TypeScript',
          stars: 128400,
          starsDelta: 0,
          reason: null,
          source: 'collection',
          category: 'AI 工具',
          tags: ['llm', 'agent'],
        },
      ],
    },
    {
      key: 'top',
      title: '收藏库之星',
      description: '当前收藏中 Star 最高的项目，值得回看。',
      items: [
        {
          id: 'vercel/next.js',
          name: 'vercel/next.js',
          url: 'https://github.com/vercel/next.js',
          description: 'React 全栈框架，支持服务端渲染与静态生成。',
          language: 'JavaScript',
          stars: 132000,
          starsDelta: 0,
          reason: null,
          source: 'collection',
          category: '前端框架',
          tags: ['react', 'ssr'],
        },
      ],
    },
    {
      key: 'recommendations',
      title: '推荐关注',
      description: '结合你的收藏与偏好生成的推荐。',
      items: [],
    },
    {
      key: 'trending',
      title: '热榜精选',
      description: '本周期 Star 增长最快的开源项目。',
      items: [],
    },
  ],
  markdown: `# 月度精选报告 · 2026 年 09 月

> 周期：2026-09-01 ~ 2026-09-30（UTC）｜生成时间：2026-10-01T00:40:00.000Z

本月新增 9 个收藏（+18,600 Star）；当前共收藏 21 个项目、累计 58.7 万 Star。
`,
}

export const MOCK_REPORT_DETAILS: Record<string, CuratedReport> = {
  [MOCK_WEEKLY_REPORT.id]: MOCK_WEEKLY_REPORT,
  [MOCK_MONTHLY_REPORT.id]: MOCK_MONTHLY_REPORT,
}

function toSummary(report: CuratedReport): ReportSummary {
  return {
    id: report.id,
    kind: report.kind,
    title: report.title,
    periodStart: report.periodStart,
    periodEnd: report.periodEnd,
    status: report.status,
    summary: report.summary,
    stats: report.stats,
    generatedAt: report.generatedAt,
  }
}

/** 演示模式数据：与 `/api/reports` 契约一致 */
export const MOCK_REPORTS: ReportSummary[] = [
  toSummary(MOCK_WEEKLY_REPORT),
  toSummary(MOCK_MONTHLY_REPORT),
]

/** 拉取报告列表；接口不可用时回退演示数据 */
export function fetchReports(kind: ReportKind | 'all' = 'all'): Promise<ReportListResponse> {
  const fallbackItems =
    kind === 'all' ? MOCK_REPORTS : MOCK_REPORTS.filter((item) => item.kind === kind)
  return fetchWithFallback<ReportListResponse>(`/api/reports?kind=${kind}`, {
    items: fallbackItems,
    total: fallbackItems.length,
  })
}

/** 拉取报告详情；接口不可用时回退演示数据 */
export function fetchReport(id: string): Promise<CuratedReport> {
  const fallback =
    MOCK_REPORT_DETAILS[id] ??
    (id.includes('monthly') ? MOCK_MONTHLY_REPORT : MOCK_WEEKLY_REPORT)
  return fetchWithFallback<CuratedReport>(`/api/reports/${encodeURIComponent(id)}`, fallback)
}

/** 立即生成当前周期报告 */
export async function generateReport(kind: ReportKind): Promise<CuratedReport> {
  if (DEMO_MODE) {
    return kind === 'monthly' ? MOCK_MONTHLY_REPORT : MOCK_WEEKLY_REPORT
  }
  const response = await apiFetch<{ report: CuratedReport }>('/api/reports/generate', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ kind }),
  })
  return response.report
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

/** 下载报告 Markdown（演示模式直接下载内置内容） */
export async function downloadReportMarkdown(report: CuratedReport): Promise<void> {
  const filename = `openfactory-${report.kind}-${report.periodStart}.md`
  if (DEMO_MODE) {
    triggerDownload(new Blob([report.markdown], { type: 'text/markdown;charset=utf-8' }), filename)
    return
  }
  const res = await fetch(`${API_BASE}/api/reports/${encodeURIComponent(report.id)}/markdown`, {
    credentials: 'include',
  })
  if (!res.ok) {
    throw new Error(`下载报告失败：${res.status}`)
  }
  triggerDownload(await res.blob(), filename)
}
