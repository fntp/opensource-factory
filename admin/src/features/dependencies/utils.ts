const ECOSYSTEM_LABELS: Record<string, string> = {
  npm: 'npm',
  pypi: 'PyPI',
  go: 'Go Modules',
  cargo: 'Cargo',
  maven: 'Maven',
  rubygems: 'RubyGems',
  composer: 'Composer',
}

const STATUS_LABELS: Record<string, string> = {
  ok: '已分析',
  no_manifest: '无清单',
  failed: '失败',
  pending: '待分析',
  unknown: '未分析',
}

export type StatusVariant = 'default' | 'secondary' | 'destructive' | 'outline'

export function formatPercent(value: number, digits = 1): string {
  if (!Number.isFinite(value)) return '0%'
  return `${(value * 100).toFixed(digits)}%`
}

export function formatCount(value: number): string {
  if (!Number.isFinite(value)) return '0'
  return value.toLocaleString('zh-CN')
}

export function ecosystemLabel(ecosystem: string): string {
  return ECOSYSTEM_LABELS[ecosystem] ?? ecosystem
}

export function kindLabel(kind: string): string {
  return kind === 'dev' ? '开发依赖' : '运行时'
}

export function statusLabel(status: string): string {
  return STATUS_LABELS[status] ?? status
}

export function statusVariant(status: string): StatusVariant {
  if (status === 'ok') return 'default'
  if (status === 'failed') return 'destructive'
  if (status === 'no_manifest') return 'secondary'
  return 'outline'
}

export function formatGeneratedAt(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '—'
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(
    date.getHours()
  )}:${pad(date.getMinutes())}`
}

/** 技术栈条形宽度：最小 4% 保证可见，最大 100%。 */
export function barWidth(percent: number): string {
  const value = Number.isFinite(percent) ? Math.min(Math.max(percent, 0), 1) : 0
  return `${Math.max(value * 100, value > 0 ? 4 : 0)}%`
}
