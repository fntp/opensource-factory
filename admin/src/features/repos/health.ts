/**
 * 项目健康度（M6-05）：前端展示与演示数据兜底。
 *
 * 正式数据来自 `GET /api/repos` 内嵌的 `health` 字段（edge 由 D1 计算 / VPS 回写）；
 * 演示模式或旧后端未返回时，按最近更新时间在本地推导一个可展示的结果。
 */

export const HEALTH_LABELS = {
  active: '活跃',
  attention: '需关注',
  stale: '停滞',
  archived: '已归档',
  unknown: '未知',
} as const

export type HealthStatus = keyof typeof HEALTH_LABELS

export interface RepoHealth {
  status: HealthStatus
  label: string
  score: number
  lastPushAt: string | null
  daysSincePush: number | null
  openIssues: number
  archived: boolean
  reasons: string[]
  checkedAt: string | null
}

export interface RepoHealthSummary {
  total: number
  active: number
  attention: number
  stale: number
  archived: number
  unknown: number
  averageScore: number
}

const DAY_MS = 24 * 60 * 60 * 1000
const DEFAULT_ACTIVE_DAYS = 90
const DEFAULT_ATTENTION_DAYS = 180
const DEFAULT_STALE_DAYS = 365

export function normalizeHealthStatus(value: unknown): HealthStatus {
  const text = String(value ?? '')
    .trim()
    .toLowerCase()
  return text in HEALTH_LABELS ? (text as HealthStatus) : 'unknown'
}

function parseDate(value: string | null | undefined): Date | null {
  if (!value) return null
  const text = String(value).trim()
  if (!text) return null
  const normalized = /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}/.test(text)
    ? `${text.replace(' ', 'T')}Z`
    : text
  const ms = Date.parse(normalized)
  return Number.isFinite(ms) ? new Date(ms) : null
}

function clamp(value: number): number {
  return Math.max(0, Math.min(100, Math.round(value)))
}

export interface EvaluateHealthInput {
  lastPushAt?: string | null
  stars?: number
  openIssues?: number
  archived?: boolean
  disabled?: boolean
  now?: Date
}

/** 与 edge / VPS 相同口径的健康度计算（用于演示数据与旧接口兜底）。 */
export function evaluateHealth(input: EvaluateHealthInput): RepoHealth {
  const now = input.now ?? new Date()
  const pushedAt = parseDate(input.lastPushAt ?? null)
  const issues = Math.max(0, Math.trunc(Number(input.openIssues ?? 0) || 0))

  if (input.archived) {
    return {
      status: 'archived',
      label: HEALTH_LABELS.archived,
      score: 0,
      lastPushAt: pushedAt ? pushedAt.toISOString() : null,
      daysSincePush: null,
      openIssues: issues,
      archived: true,
      reasons: ['仓库已归档，不再接收更新'],
      checkedAt: null,
    }
  }

  if (!pushedAt) {
    return {
      status: 'unknown',
      label: HEALTH_LABELS.unknown,
      score: 0,
      lastPushAt: null,
      daysSincePush: null,
      openIssues: issues,
      archived: false,
      reasons: ['缺少最后提交时间，无法判断活跃度'],
      checkedAt: null,
    }
  }

  const days = Math.max(0, Math.floor((now.getTime() - pushedAt.getTime()) / DAY_MS))
  let status: HealthStatus
  let score: number
  if (days <= DEFAULT_ACTIVE_DAYS) {
    status = 'active'
    score = 100
  } else if (days <= DEFAULT_ATTENTION_DAYS) {
    status = 'attention'
    score = 70
  } else if (days <= DEFAULT_STALE_DAYS) {
    status = 'stale'
    score = 45
  } else {
    status = 'stale'
    score = 20
  }

  let issueReason: string
  if (issues <= 0) {
    score += 5
    issueReason = '当前没有未关闭 issue'
  } else {
    const stars = Math.max(1, Math.trunc(Number(input.stars ?? 0) || 0))
    const ratio = issues / stars
    if (ratio >= 0.5) {
      score -= 20
      issueReason = `存在 ${issues} 个未关闭 issue / PR（占 Star ${Math.round(ratio * 100)}%），需关注维护压力`
    } else if (ratio >= 0.2) {
      score -= 10
      issueReason = `存在 ${issues} 个未关闭 issue / PR（占 Star ${Math.round(ratio * 100)}%）`
    } else {
      issueReason = `存在 ${issues} 个未关闭 issue / PR`
    }
  }

  const reasons = [`最后提交于 ${days} 天前`]
  if (input.disabled) {
    score = Math.min(score, 30)
    status = 'stale'
    reasons.push('仓库已被 GitHub 禁用')
  }
  if (days > DEFAULT_ATTENTION_DAYS) {
    reasons.push(`超过 ${DEFAULT_ATTENTION_DAYS} 天无提交，建议评估是否仍在使用`)
  }
  reasons.push(issueReason)

  return {
    status,
    label: HEALTH_LABELS[status],
    score: clamp(score),
    lastPushAt: pushedAt.toISOString(),
    daysSincePush: days,
    openIssues: issues,
    archived: false,
    reasons,
    checkedAt: null,
  }
}

/** 取仓库健康度：优先接口字段，缺失时用最近更新时间兜底。 */
export function healthForRepo(repo: {
  updatedAt?: string | null
  stars?: number
  health?: RepoHealth
}): RepoHealth {
  if (repo.health) return repo.health
  return evaluateHealth({
    lastPushAt: repo.updatedAt ?? null,
    stars: repo.stars ?? 0,
  })
}

export function summarizeRepoHealth(
  repos: Array<{ health?: RepoHealth }>
): RepoHealthSummary {
  const summary: RepoHealthSummary = {
    total: repos.length,
    active: 0,
    attention: 0,
    stale: 0,
    archived: 0,
    unknown: 0,
    averageScore: 0,
  }
  let scoreSum = 0
  for (const repo of repos) {
    const health = repo.health ?? evaluateHealth({})
    summary[normalizeHealthStatus(health.status)] += 1
    scoreSum += Number(health.score ?? 0)
  }
  summary.averageScore = repos.length
    ? Math.round((scoreSum / repos.length) * 10) / 10
    : 0
  return summary
}

/** 健康度徽章配色（Tailwind 类）。 */
export function healthBadgeClass(status: HealthStatus): string {
  switch (status) {
    case 'active':
      return 'border-emerald-500/30 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400'
    case 'attention':
      return 'border-amber-500/30 bg-amber-500/10 text-amber-600 dark:text-amber-400'
    case 'stale':
      return 'border-rose-500/30 bg-rose-500/10 text-rose-600 dark:text-rose-400'
    case 'archived':
      return 'border-slate-500/30 bg-slate-500/10 text-slate-600 dark:text-slate-400'
    default:
      return 'border-muted-foreground/30 bg-muted text-muted-foreground'
  }
}
