import type {
  AgentDraftStatus,
  AgentMode,
  AgentRunStatus,
  AgentStats,
  AgentTemplate,
} from './api'

const TEMPLATE_LABELS: Record<AgentTemplate, string> = {
  organize: '自动整理',
  draft: '收藏草稿',
  full: '整理 + 草稿',
}

const MODE_LABELS: Record<AgentMode, string> = {
  preview: '预览',
  apply: '直接应用',
}

const RUN_STATUS_LABELS: Record<AgentRunStatus, string> = {
  completed: '已完成',
  failed: '失败',
}

const DRAFT_STATUS_LABELS: Record<AgentDraftStatus, string> = {
  draft: '草稿',
  applied: '已采用',
  discarded: '已丢弃',
}

export function agentTemplateLabel(template: AgentTemplate): string {
  return TEMPLATE_LABELS[template] ?? template
}

export function agentModeLabel(mode: AgentMode): string {
  return MODE_LABELS[mode] ?? mode
}

export function agentRunStatusLabel(status: AgentRunStatus): string {
  return RUN_STATUS_LABELS[status] ?? status
}

export function agentDraftStatusLabel(status: AgentDraftStatus): string {
  return DRAFT_STATUS_LABELS[status] ?? status
}

/** 数字展示：非法值显示破折号，其余按千分位。 */
export function formatAgentCount(value: number): string {
  if (!Number.isFinite(value)) return '—'
  return new Intl.NumberFormat('zh-CN').format(Math.round(value))
}

/** Star 展示：万 / k 缩写，与草稿内文案一致。 */
export function formatAgentStars(value: number): string {
  const number = Math.max(0, Math.trunc(Number(value) || 0))
  if (number >= 10000) return `${(number / 10000).toFixed(1)} 万`
  if (number >= 1000) return `${(number / 1000).toFixed(1)}k`
  return String(number)
}

export function formatAgentTime(value: string | null | undefined): string {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '—'
  return date.toLocaleString('zh-CN', { hour12: false })
}

/** 阈值展示：0.75 → 75%。 */
export function formatAgentThreshold(value: number): string {
  if (!Number.isFinite(value)) return '—'
  return `${Math.round(value * 100)}%`
}

export interface AgentStatCard {
  title: string
  value: string
  hint: string
}

/** 执行结果顶部的统计卡（纯函数，便于测试口径）。 */
export function agentStatCards(stats: AgentStats): AgentStatCard[] {
  return [
    {
      title: '收藏总数',
      value: formatAgentCount(stats.totalRepos),
      hint: `${formatAgentCount(stats.categoryCount)} 个分类 · ${formatAgentCount(stats.languageCount)} 种语言`,
    },
    {
      title: 'Star 合计',
      value: formatAgentStars(stats.totalStars),
      hint: `${formatAgentCount(stats.tagCount)} 个标签`,
    },
    {
      title: '主要语言',
      value: stats.topLanguage ?? '—',
      hint: '按收藏数量统计',
    },
    {
      title: '主要分类',
      value: stats.topCategory ?? '—',
      hint: '按分类名称排序',
    },
  ]
}

/** 计划步骤是否可执行（用于 UI 灰显）。 */
export function isAgentStepReady(status: string): boolean {
  return status === 'ready'
}

/** 草稿文件名：使用草稿 id，避免中文标题在部分系统下乱码。 */
export function agentDraftFilename(id: string): string {
  return `${id || 'agent-draft'}.md`
}
