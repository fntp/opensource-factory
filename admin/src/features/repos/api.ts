import { apiFetch, fetchWithFallback } from '@/lib/api'
import type { LicenseInfo } from '@/features/licenses/api'
import { HEALTH_LABELS, type RepoHealth } from './health'

function demoLicense(
  spdxId: string,
  name: string,
  category: LicenseInfo['category'],
  riskLevel: LicenseInfo['riskLevel']
): LicenseInfo {
  const categoryLabel =
    category === 'permissive'
      ? '宽松许可'
      : category === 'weak-copyleft'
        ? '弱著佐权'
        : category === 'network-copyleft'
          ? '网络著佐权'
          : '强著佐权'
  return {
    spdxId,
    name,
    category,
    categoryLabel,
    riskLevel,
    riskLabel:
      riskLevel === 'low'
        ? '低风险'
        : riskLevel === 'medium'
          ? '中风险'
          : '高风险',
    summary: `${name}：请按许可证义务使用、修改与分发。`,
    obligations: ['保留版权与许可证声明'],
    warnings: [],
    source: 'github',
    checkedAt: '2026-10-22T08:00:00',
  }
}

export interface RepoItem {
  id: string
  fullName: string
  description: string
  /** VPS 生成的 README 中文摘要（可选） */
  summary?: string | null
  language: string
  stars: number
  forks: number
  category: string
  tags: string[]
  updatedAt: string
  url: string
  /** 项目健康度（M6-05，旧接口可能缺失） */
  health?: RepoHealth
  /** License 合规提示（M6-06） */
  license?: LicenseInfo | null
}

function mockHealth(
  partial: Pick<RepoHealth, 'status' | 'score' | 'lastPushAt'> &
    Partial<RepoHealth>
): RepoHealth {
  return {
    label: HEALTH_LABELS[partial.status],
    daysSincePush: null,
    openIssues: 0,
    archived: partial.status === 'archived',
    reasons: [],
    checkedAt: '2026-10-22T06:12:00Z',
    ...partial,
  }
}

export const MOCK_REPOS: RepoItem[] = [
  {
    id: '1',
    fullName: 'fntp/opensource-factory',
    description: '个人开源资产管理与智能推荐系统',
    language: 'TypeScript',
    stars: 128,
    forks: 12,
    category: '工具平台',
    tags: ['资产', '推荐'],
    updatedAt: '2026-10-12',
    url: 'https://github.com/fntp/opensource-factory',
    health: mockHealth({
      status: 'active',
      score: 100,
      lastPushAt: '2026-10-12T09:00:00Z',
      daysSincePush: 10,
      reasons: ['最后提交于 10 天前', '当前没有未关闭 issue'],
    }),
    license: demoLicense('MIT', 'MIT License', 'permissive', 'low'),
  },
  {
    id: '2',
    fullName: 'langchain-ai/langchain',
    description: '构建上下文感知推理应用的开源框架',
    language: 'Python',
    stars: 94210,
    forks: 15230,
    category: 'AI/LLM',
    tags: ['LLM', '框架'],
    updatedAt: '2026-10-13',
    url: 'https://github.com/langchain-ai/langchain',
    health: mockHealth({
      status: 'active',
      score: 100,
      lastPushAt: '2026-10-13T08:00:00Z',
      daysSincePush: 9,
      openIssues: 320,
      reasons: ['最后提交于 9 天前', '存在 320 个未关闭 issue / PR'],
    }),
    license: demoLicense('MIT', 'MIT License', 'permissive', 'low'),
  },
  {
    id: '3',
    fullName: 'shadcn-ui/ui',
    description: '设计精美的组件集合，可复制到你的应用中',
    language: 'TypeScript',
    stars: 78120,
    forks: 4150,
    category: '前端开发',
    tags: ['组件', '设计'],
    updatedAt: '2026-10-12',
    url: 'https://github.com/shadcn-ui/ui',
    health: mockHealth({
      status: 'attention',
      score: 70,
      lastPushAt: '2026-06-20T12:00:00Z',
      daysSincePush: 124,
      openIssues: 410,
      reasons: [
        '最后提交于 124 天前',
        '存在 410 个未关闭 issue / PR（占 Star 1%）',
      ],
    }),
    license: demoLicense('MIT', 'MIT License', 'permissive', 'low'),
  },
  {
    id: '4',
    fullName: 'ollama/ollama',
    description: '在本地轻松运行大语言模型',
    language: 'Go',
    stars: 102340,
    forks: 8100,
    category: 'AI/LLM',
    tags: ['本地模型', '推理'],
    updatedAt: '2026-10-13',
    url: 'https://github.com/ollama/ollama',
    health: mockHealth({
      status: 'active',
      score: 100,
      lastPushAt: '2026-10-13T10:30:00Z',
      daysSincePush: 9,
      reasons: ['最后提交于 9 天前', '当前没有未关闭 issue'],
    }),
    license: demoLicense(
      'AGPL-3.0',
      'GNU Affero General Public License 3.0',
      'network-copyleft',
      'high'
    ),
  },
  {
    id: '5',
    fullName: 'lobehub/lobe-chat',
    description: '开源的现代 AI 聊天应用框架',
    language: 'TypeScript',
    stars: 55120,
    forks: 12300,
    category: 'AI/LLM',
    tags: ['聊天', '应用'],
    updatedAt: '2026-10-11',
    url: 'https://github.com/lobehub/lobe-chat',
    health: mockHealth({
      status: 'archived',
      score: 0,
      lastPushAt: '2026-03-01T00:00:00Z',
      archived: true,
      reasons: ['仓库已归档，不再接收更新'],
    }),
    license: demoLicense('MIT', 'MIT License', 'permissive', 'low'),
  },
  {
    id: '6',
    fullName: 'fastapi/fastapi',
    description: '高性能的现代 Python Web 框架',
    language: 'Python',
    stars: 82600,
    forks: 7100,
    category: '后端与 API',
    tags: ['API', '异步'],
    updatedAt: '2026-10-10',
    url: 'https://github.com/fastapi/fastapi',
    health: mockHealth({
      status: 'active',
      score: 100,
      lastPushAt: '2026-10-10T16:00:00Z',
      daysSincePush: 12,
      reasons: ['最后提交于 12 天前', '当前没有未关闭 issue'],
    }),
    license: demoLicense('MIT', 'MIT License', 'permissive', 'low'),
  },
  {
    id: '7',
    fullName: 'vuejs/core',
    description: '渐进式 JavaScript 框架',
    language: 'TypeScript',
    stars: 48900,
    forks: 4300,
    category: '前端开发',
    tags: ['Vue', '框架'],
    updatedAt: '2026-10-12',
    url: 'https://github.com/vuejs/core',
    health: mockHealth({
      status: 'active',
      score: 100,
      lastPushAt: '2026-10-12T14:00:00Z',
      daysSincePush: 10,
      reasons: ['最后提交于 10 天前', '当前没有未关闭 issue'],
    }),
    license: demoLicense('MIT', 'MIT License', 'permissive', 'low'),
  },
  {
    id: '8',
    fullName: 'tauri-apps/tauri',
    description: '使用 Web 技术构建更小、更快、更安全的桌面应用',
    language: 'Rust',
    stars: 92100,
    forks: 2800,
    category: '桌面端',
    tags: ['跨平台', 'Rust'],
    updatedAt: '2026-10-09',
    url: 'https://github.com/tauri-apps/tauri',
    health: mockHealth({
      status: 'stale',
      score: 25,
      lastPushAt: '2025-08-01T00:00:00Z',
      daysSincePush: 447,
      reasons: [
        '最后提交于 447 天前',
        '超过 180 天无提交，建议评估是否仍在使用',
        '当前没有未关闭 issue',
      ],
    }),
    license: demoLicense(
      'Apache-2.0',
      'Apache License 2.0',
      'permissive',
      'low'
    ),
  },
]

export function fetchRepos(): Promise<RepoItem[]> {
  return fetchWithFallback<RepoItem[]>('/api/repos', MOCK_REPOS)
}

export interface RepoHealthRefreshResult {
  status?: string
  taskId?: string | null
  note?: string
}

/** 触发 VPS 刷新仓库元数据与健康度（M6-05） */
export function refreshRepoHealth(): Promise<RepoHealthRefreshResult> {
  return apiFetch<RepoHealthRefreshResult>('/api/repos/health/refresh', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({}),
  })
}
