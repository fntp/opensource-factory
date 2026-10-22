import type {
  TagSuggestionCategory,
  TagSuggestionItem,
  TagSuggestionStatus,
  TagSuggestionsSummary,
} from './api'

export interface RepoTagGroup {
  repoId: string
  repoName: string
  repoUrl: string
  summary: string
  items: TagSuggestionItem[]
  avgScore: number
}

const CATEGORY_LABELS: Record<TagSuggestionCategory, string> = {
  language: '语言',
  framework: '框架',
  domain: '业务域',
  quality: '工程属性',
}

const STATUS_LABELS: Record<TagSuggestionStatus, string> = {
  pending: '待确认',
  accepted: '已采纳',
  dismissed: '已忽略',
}

/** 分数格式化为百分比（0~1，非法值按 0）。 */
export function formatScore(score: number | null | undefined): string {
  const value = typeof score === 'number' && Number.isFinite(score) ? score : 0
  const clamped = Math.min(1, Math.max(0, value))
  return `${Math.round(clamped * 100)}%`
}

export function categoryLabel(category: TagSuggestionCategory): string {
  return CATEGORY_LABELS[category] ?? category
}

export function statusLabel(status: TagSuggestionStatus): string {
  return STATUS_LABELS[status] ?? status
}

/** 置信度分档：高 / 中 / 低，用于徽标颜色。 */
export function scoreTone(score: number): 'high' | 'medium' | 'low' {
  if (score >= 0.8) return 'high'
  if (score >= 0.65) return 'medium'
  return 'low'
}

/** 建议按仓库分组：组内按分数降序，组间按最高分降序。 */
export function groupSuggestionsByRepo(items: TagSuggestionItem[]): RepoTagGroup[] {
  const groups = new Map<string, RepoTagGroup>()
  for (const item of items) {
    const current = groups.get(item.repoId)
    if (current) {
      current.items.push(item)
    } else {
      groups.set(item.repoId, {
        repoId: item.repoId,
        repoName: item.repoName || item.repoId,
        repoUrl: item.repoUrl,
        summary: item.summary,
        items: [item],
        avgScore: 0,
      })
    }
  }

  const result = [...groups.values()]
  for (const group of result) {
    group.items.sort((a, b) => b.score - a.score || a.tagName.localeCompare(b.tagName))
    group.avgScore =
      group.items.reduce((sum, item) => sum + item.score, 0) / group.items.length
  }
  result.sort(
    (a, b) =>
      (b.items[0]?.score ?? 0) - (a.items[0]?.score ?? 0) ||
      a.repoId.localeCompare(b.repoId)
  )
  return result
}

/** 本地汇总（演示模式或操作后即时更新用）。 */
export function summarizeSuggestions(items: TagSuggestionItem[]): TagSuggestionsSummary {
  const pending = items.filter((item) => item.status === 'pending')
  return {
    pending: pending.length,
    accepted: items.filter((item) => item.status === 'accepted').length,
    dismissed: items.filter((item) => item.status === 'dismissed').length,
    repos: new Set(pending.map((item) => item.repoId)).size,
    avgScore:
      pending.length > 0
        ? pending.reduce((sum, item) => sum + item.score, 0) / pending.length
        : null,
  }
}

/** 摘要过长时截断，保留可读的前半段。 */
export function truncateSummary(summary: string, maxLength = 120): string {
  const text = (summary ?? '').trim()
  if (text.length <= maxLength) return text
  return `${text.slice(0, maxLength)}…`
}
