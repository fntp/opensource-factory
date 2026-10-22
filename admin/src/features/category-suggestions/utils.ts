/** 自动分类建议（M7-02）前端 DTO 与纯函数辅助。 */

export type CategorySuggestionStatus = 'pending' | 'accepted' | 'dismissed'

export interface CategorySuggestionItem {
  id: string
  repoId: string
  repoName: string
  repoUrl: string
  summary: string | null
  categoryName: string
  businessLine: string
  score: number
  reason: string | null
  evidence: string | null
  status: CategorySuggestionStatus
  currentCategory: string | null
  updatedAt: string | null
}

export interface CategorySuggestionSummary {
  total: number
  pending: number
  accepted: number
  dismissed: number
  repos: number
  avgScore: number
}

export interface CategorySuggestionListResponse {
  items: CategorySuggestionItem[]
  summary: CategorySuggestionSummary
  categories: Array<{ id: string; name: string }>
}

export interface CategorySuggestionGenerateResult {
  generatedAt: string
  scanned: number
  suggested: number
  skipped: number
  source: 'vps' | 'local' | 'mixed'
}

export interface CategorySuggestionAcceptResult {
  accepted: number
  categoriesCreated: number
  items: Array<{ repoId: string; categoryName: string; categoryId: string }>
}

/** 业务线 key → 中文名（与 edge / vps 词表保持一致）。 */
const BUSINESS_LINE_LABELS: Record<string, string> = {
  ai: 'AI / 大模型',
  fintech: '金融 / 支付',
  ecommerce: '电商 / 零售',
  saas: '企业服务 / SaaS',
  devtools: '开发工具',
  'data-infra': '数据工程',
  'cloud-devops': 'DevOps / 云原生',
  security: '安全 / 合规',
  'web-frontend': '前端开发',
  mobile: '移动端',
  'content-media': '内容 / 媒体',
  education: '教育 / 学习',
  productivity: '效率 / 办公',
  gaming: '游戏 / 娱乐',
  iot: '物联网 / 嵌入式',
  blockchain: '区块链 / Web3',
  healthcare: '医疗 / 健康',
  'backend-api': '后端与 API',
}

export function businessLineLabel(key: string): string {
  return BUSINESS_LINE_LABELS[key] ?? key
}

/** 置信度格式化为整数百分比（0~100）。 */
export function formatScore(score: number): string {
  if (!Number.isFinite(score)) return '0%'
  return `${Math.round(Math.min(1, Math.max(0, score)) * 100)}%`
}

/** 分数档位：高 / 中 / 低，用于卡片配色。 */
export function scoreTier(score: number): 'high' | 'medium' | 'low' {
  if (score >= 0.8) return 'high'
  if (score >= 0.65) return 'medium'
  return 'low'
}

export function statusLabel(status: CategorySuggestionStatus | 'all'): string {
  if (status === 'accepted') return '已采纳'
  if (status === 'dismissed') return '已忽略'
  if (status === 'all') return '全部'
  return '待确认'
}

export function sourceLabel(
  source: CategorySuggestionGenerateResult['source']
): string {
  if (source === 'vps') return 'VPS 规则引擎'
  if (source === 'mixed') return 'VPS + 本地补扫'
  return '本地规则兜底'
}

export function summaryText(summary: CategorySuggestionSummary): string {
  return `共 ${summary.total} 条建议，覆盖 ${summary.repos} 个仓库，待确认 ${summary.pending} 条`
}

export function generateSummary(
  result: CategorySuggestionGenerateResult
): string {
  return `扫描 ${result.scanned} 个仓库，新增 / 刷新 ${result.suggested} 条建议，跳过 ${result.skipped} 个`
}

/** 按仓库聚合建议，便于在列表里按项目成组展示。 */
export function groupByRepo(
  items: CategorySuggestionItem[]
): Array<{
  repoId: string
  repoName: string
  repoUrl: string
  items: CategorySuggestionItem[]
}> {
  const groups = new Map<
    string,
    {
      repoId: string
      repoName: string
      repoUrl: string
      items: CategorySuggestionItem[]
    }
  >()
  for (const item of items) {
    const existing = groups.get(item.repoId)
    if (existing) {
      existing.items.push(item)
      continue
    }
    groups.set(item.repoId, {
      repoId: item.repoId,
      repoName: item.repoName,
      repoUrl: item.repoUrl,
      items: [item],
    })
  }
  return [...groups.values()]
}
