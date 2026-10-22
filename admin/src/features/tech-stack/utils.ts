import type {
  TechStackGraphLink,
  TechStackGraphNode,
  TechStackLanguage,
} from './api'

export const RADIAL_INNER_RATIO = 0.25
export const RADIAL_OUTER_RATIO = 0.375

export interface LanguageBar {
  name: string
  repoCount: number
  starCount: number
  share: number
  frameworks: string[]
  isOther: boolean
}

/** 语言榜最多保留 limit 项，其余合并为「其他」 */
export function foldLanguages(
  languages: readonly TechStackLanguage[],
  limit = 8
): LanguageBar[] {
  const safeLimit = Math.max(2, limit)
  const rows: LanguageBar[] = languages.map((item) => ({
    name: item.name,
    repoCount: item.repoCount,
    starCount: item.starCount,
    share: item.share,
    frameworks: item.frameworks,
    isOther: false,
  }))
  if (rows.length <= safeLimit) return rows

  const head = rows.slice(0, safeLimit - 1)
  const tail = rows.slice(safeLimit - 1)
  head.push({
    name: '其他',
    repoCount: tail.reduce((sum, item) => sum + item.repoCount, 0),
    starCount: tail.reduce((sum, item) => sum + item.starCount, 0),
    share: Math.round(tail.reduce((sum, item) => sum + item.share, 0) * 10) / 10,
    frameworks: [],
    isOther: true,
  })
  return head
}

/** 百分比展示：整数不带小数，其余保留一位 */
export function formatPercent(value: number): string {
  if (!Number.isFinite(value)) return '0%'
  return Number.isInteger(value) ? `${value}%` : `${value.toFixed(1)}%`
}

/** Star 等大数字的紧凑展示（中文万 / 亿） */
export function formatCompactNumber(value: number): string {
  if (!Number.isFinite(value)) return '0'
  return new Intl.NumberFormat('zh-CN', {
    notation: 'compact',
    maximumFractionDigits: 1,
  }).format(value)
}

export interface TechPair {
  language: string
  framework: string
  weight: number
}

/** 取权重最高的语言 × 框架组合 */
export function topLanguageFrameworkPairs(
  graph: { nodes: readonly TechStackGraphNode[]; links: readonly TechStackGraphLink[] },
  limit = 4
): TechPair[] {
  const labels = new Map(graph.nodes.map((node) => [node.id, node.label]))
  return [...graph.links]
    .sort((a, b) => b.weight - a.weight)
    .slice(0, Math.max(0, limit))
    .map((link) => ({
      language: labels.get(link.source) ?? link.source,
      framework: labels.get(link.target) ?? link.target,
      weight: link.weight,
    }))
}

export interface PositionedNode extends TechStackGraphNode {
  x: number
  y: number
  r: number
  angle: number
}

export interface PositionedLink extends TechStackGraphLink {
  x1: number
  y1: number
  x2: number
  y2: number
}

export interface RadialLayout {
  nodes: PositionedNode[]
  links: PositionedLink[]
  center: { x: number; y: number }
}

function languageRadius(weight: number): number {
  return Math.min(32, 15 + Math.sqrt(Math.max(1, weight)) * 4.5)
}

function frameworkRadius(weight: number): number {
  return Math.min(20, 7 + Math.sqrt(Math.max(1, weight)) * 3.2)
}

/**
 * 计算「内圈语言 + 外圈框架」的径向布局。
 *
 * 框架按所属语言分组后沿外圈依次排布，避免节点与标签重叠；
 * 纯函数，输出可直接映射为 SVG 坐标。
 */
export function buildRadialLayout(
  graph: { nodes: readonly TechStackGraphNode[]; links: readonly TechStackGraphLink[] },
  width = 760,
  height = 560
): RadialLayout {
  const center = { x: width / 2, y: height / 2 }
  const shortSide = Math.min(width, height)
  const innerRadius = shortSide * RADIAL_INNER_RATIO
  const outerRadius = shortSide * RADIAL_OUTER_RATIO

  const languages = graph.nodes.filter((node) => node.kind === 'language')
  const frameworks = graph.nodes.filter((node) => node.kind === 'framework')
  const positioned: PositionedNode[] = []
  const languageAngles = new Map<string, number>()

  languages.forEach((node, index) => {
    const angle =
      -Math.PI / 2 + (index * 2 * Math.PI) / Math.max(1, languages.length)
    languageAngles.set(node.id, angle)
    positioned.push({
      ...node,
      x: center.x + Math.cos(angle) * innerRadius,
      y: center.y + Math.sin(angle) * innerRadius,
      r: languageRadius(node.weight),
      angle,
    })
  })

  const groups = new Map<string, TechStackGraphNode[]>()
  const ungrouped: TechStackGraphNode[] = []
  for (const framework of frameworks) {
    const links = graph.links.filter((link) => link.target === framework.id)
    if (links.length === 0) {
      ungrouped.push(framework)
      continue
    }
    const dominant = links.reduce((best, link) =>
      link.weight > best.weight ? link : best
    )
    const list = groups.get(dominant.source) ?? []
    list.push(framework)
    groups.set(dominant.source, list)
  }

  const orderedFrameworks: TechStackGraphNode[] = []
  for (const language of languages) {
    const list = groups.get(language.id)
    if (!list) continue
    list.sort(
      (a, b) =>
        b.weight - a.weight || a.label.localeCompare(b.label, 'zh-Hans-CN')
    )
    orderedFrameworks.push(...list)
  }
  ungrouped.sort(
    (a, b) => b.weight - a.weight || a.label.localeCompare(b.label, 'zh-Hans-CN')
  )
  orderedFrameworks.push(...ungrouped)

  orderedFrameworks.forEach((node, index) => {
    const angle =
      -Math.PI / 2 +
      (index * 2 * Math.PI) / Math.max(1, orderedFrameworks.length)
    positioned.push({
      ...node,
      x: center.x + Math.cos(angle) * outerRadius,
      y: center.y + Math.sin(angle) * outerRadius,
      r: frameworkRadius(node.weight),
      angle,
    })
  })

  const byId = new Map(positioned.map((node) => [node.id, node]))
  const links: PositionedLink[] = []
  for (const link of graph.links) {
    const source = byId.get(link.source)
    const target = byId.get(link.target)
    if (!source || !target) continue
    links.push({
      ...link,
      x1: source.x,
      y1: source.y,
      x2: target.x,
      y2: target.y,
    })
  }

  return { nodes: positioned, links, center }
}
