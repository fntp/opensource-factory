import type { SummarySource, TrendingRepoDetail } from './api'

export interface MetaItem {
  label: string
  value: string
}

const SUMMARY_SOURCE_LABEL: Record<SummarySource, string> = {
  readme: 'README 摘要',
  description: '项目描述',
  tech: '技术栈提示',
  empty: '暂无摘要',
}

export function summarySourceLabel(source: SummarySource): string {
  return SUMMARY_SOURCE_LABEL[source] ?? SUMMARY_SOURCE_LABEL.empty
}

export function formatStars(value: number): string {
  return value.toLocaleString('zh-CN')
}

/** 详情页元信息网格（纯函数，便于单测） */
export function buildMetaItems(detail: TrendingRepoDetail): MetaItem[] {
  return [
    { label: '总 Star', value: formatStars(detail.stars) },
    { label: '今日 Star', value: `+${formatStars(detail.starsToday)}` },
    { label: '主语言', value: detail.language || '—' },
    { label: '平台', value: detail.platform || 'github' },
    { label: '技术栈', value: detail.techStack.length ? detail.techStack.join(' · ') : '—' },
    { label: '抓取日期', value: detail.crawledAt || '—' },
  ]
}

/** 列表项跳转参数：把 id 拆成 owner / name */
export function repoRouteParams(id: string): { owner: string; name: string } | null {
  const parts = id.trim().split('/')
  if (parts.length !== 2 || !parts[0] || !parts[1]) return null
  return { owner: parts[0], name: parts[1] }
}
