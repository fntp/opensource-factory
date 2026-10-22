/** 重复 / 相似项目检测的纯函数辅助与前端 DTO。 */

export type DuplicateScope = 'my' | 'trending' | 'all'
export type DuplicateKind = 'exact' | 'name' | 'semantic' | 'mixed'
export type DuplicateSource = 'my' | 'trending'
export type DuplicateScanMode = 'vps' | 'hybrid' | 'local'

export interface DuplicateSignals {
  nameSimilarity: number
  descriptionSimilarity: number
  vectorSimilarity: number | null
  exactKey: boolean
}

export interface DuplicateMember {
  source: DuplicateSource
  repoId: string
  fullName: string
  name: string
  description: string
  language: string
  stars: number
  url: string
  platform: string
  categoryId: string
  readmeSummary: string
  techStack: string[]
  role: 'canonical' | 'merge'
  signals: DuplicateSignals
}

export interface DuplicateFieldSuggestion {
  field: string
  value: unknown
  from: { source: DuplicateSource; repoId: string }
  reason: string
}

export interface DuplicateSuggestion {
  action: 'merge' | 'review'
  keep: { source: DuplicateSource; repoId: string }
  mergeTargets: Array<{ source: DuplicateSource; repoId: string }>
  fields: DuplicateFieldSuggestion[]
  notes: string
}

export interface DuplicateCluster {
  id: string
  kind: DuplicateKind
  confidence: number
  reasons: string[]
  members: DuplicateMember[]
  suggestion: DuplicateSuggestion
}

export interface DuplicateThresholds {
  minScore: number
  nameThreshold: number
  descriptionThreshold: number
  vectorThreshold: number
  maxRepos: number
  maxClusters: number
}

export interface DuplicateScanResponse {
  scanId: string
  scope: DuplicateScope
  mode: DuplicateScanMode
  count: number
  scanned: number
  compared: number
  tookMs: number
  thresholds: DuplicateThresholds
  dismissedCount: number
  clusters: DuplicateCluster[]
}

export interface DuplicateDismissal {
  clusterId: string
  repoIds: string[]
  reason: string | null
  createdAt: string | null
}

/** 置信度展示：0.8734 → 87%。 */
export function formatConfidence(value: number): string {
  if (!Number.isFinite(value)) return '0%'
  return `${Math.round(Math.max(0, Math.min(1, value)) * 100)}%`
}

export function kindLabel(kind: DuplicateKind): string {
  if (kind === 'exact') return '地址完全重复'
  if (kind === 'name') return '名称高度相似'
  if (kind === 'semantic') return '语义相似'
  return '混合命中'
}

export function scopeLabel(scope: DuplicateScope): string {
  if (scope === 'my') return '我的仓库'
  if (scope === 'trending') return '每日热榜'
  return '全部来源'
}

export function modeLabel(mode: DuplicateScanMode): string {
  if (mode === 'vps') return 'VPS 规则 + 向量'
  if (mode === 'hybrid') return 'VPS + 本地补扫'
  return '本地规则兜底'
}

export function sourceLabel(source: DuplicateSource): string {
  return source === 'my' ? '我的仓库' : '每日热榜'
}

export function memberRoleLabel(role: DuplicateMember['role']): string {
  return role === 'canonical' ? '保留' : '合并'
}

export function actionLabel(action: DuplicateSuggestion['action']): string {
  return action === 'merge' ? '建议合并' : '建议人工复核'
}

export function fieldLabel(field: string): string {
  switch (field) {
    case 'description':
      return '项目简介'
    case 'readmeSummary':
      return 'README 摘要'
    case 'stars':
      return 'Star 数'
    case 'language':
      return '主语言'
    case 'categoryId':
      return '分类'
    case 'techStack':
      return '技术栈'
    default:
      return field
  }
}

/** 字段建议值展示：数组用「、」连接，其余转字符串。 */
export function formatFieldValue(value: unknown): string {
  if (Array.isArray(value)) {
    return value.map((item) => String(item)).join('、')
  }
  if (value === null || value === undefined || value === '') return '—'
  return String(value)
}

/** 概览文案：扫描 N 个仓库，发现 M 组重复。 */
export function scanSummary(result: DuplicateScanResponse): string {
  const scanned = Math.max(0, result.scanned)
  const count = Math.max(0, result.count)
  return `扫描 ${scanned.toLocaleString()} 个仓库，发现 ${count} 组疑似重复`
}
