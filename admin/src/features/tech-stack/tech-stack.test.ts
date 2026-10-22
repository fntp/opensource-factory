import { describe, expect, it } from 'vitest'
import type { TechStackGraphNode, TechStackLanguage } from './api'
import {
  buildRadialLayout,
  foldLanguages,
  formatCompactNumber,
  formatPercent,
  topLanguageFrameworkPairs,
} from './utils'

function language(name: string, repoCount: number): TechStackLanguage {
  return {
    name,
    repoCount,
    starCount: repoCount * 100,
    share: repoCount,
    frameworks: [],
  }
}

describe('foldLanguages', () => {
  it('keeps every language when the list fits', () => {
    const rows = foldLanguages([language('TypeScript', 3), language('Go', 1)], 8)
    expect(rows.map((row) => row.name)).toEqual(['TypeScript', 'Go'])
    expect(rows.every((row) => !row.isOther)).toBe(true)
  })

  it('folds the tail into 其他 and sums counts', () => {
    const rows = foldLanguages(
      [
        language('A', 10),
        language('B', 8),
        language('C', 6),
        language('D', 4),
        language('E', 2),
      ],
      4
    )
    expect(rows).toHaveLength(4)
    expect(rows[rows.length - 1]).toMatchObject({
      name: '其他',
      repoCount: 6,
      starCount: 600,
      isOther: true,
    })
  })
})

describe('format helpers', () => {
  it('formats percentages with at most one decimal', () => {
    expect(formatPercent(25)).toBe('25%')
    expect(formatPercent(33.3)).toBe('33.3%')
    expect(formatPercent(Number.NaN)).toBe('0%')
  })

  it('formats large numbers compactly in Chinese', () => {
    expect(formatCompactNumber(624900)).toContain('万')
    expect(formatCompactNumber(0)).toBe('0')
  })
})

describe('topLanguageFrameworkPairs', () => {
  it('resolves labels and sorts by weight', () => {
    const nodes: TechStackGraphNode[] = [
      { id: 'lang:TypeScript', label: 'TypeScript', kind: 'language', weight: 3 },
      { id: 'lang:Python', label: 'Python', kind: 'language', weight: 2 },
      { id: 'fw:React', label: 'React', kind: 'framework', weight: 2 },
      { id: 'fw:FastAPI', label: 'FastAPI', kind: 'framework', weight: 2 },
    ]
    const pairs = topLanguageFrameworkPairs(
      {
        nodes,
        links: [
          { source: 'lang:TypeScript', target: 'fw:React', weight: 2 },
          { source: 'lang:Python', target: 'fw:FastAPI', weight: 3 },
        ],
      },
      1
    )
    expect(pairs).toEqual([
      { language: 'Python', framework: 'FastAPI', weight: 3 },
    ])
  })
})

describe('buildRadialLayout', () => {
  it('places languages on the inner ring and frameworks on the outer ring', () => {
    const nodes: TechStackGraphNode[] = [
      { id: 'lang:TypeScript', label: 'TypeScript', kind: 'language', weight: 4 },
      { id: 'lang:Python', label: 'Python', kind: 'language', weight: 2 },
      { id: 'fw:React', label: 'React', kind: 'framework', weight: 3 },
      { id: 'fw:Vite', label: 'Vite', kind: 'framework', weight: 1 },
      { id: 'fw:FastAPI', label: 'FastAPI', kind: 'framework', weight: 2 },
    ]
    const layout = buildRadialLayout(
      {
        nodes,
        links: [
          { source: 'lang:TypeScript', target: 'fw:React', weight: 3 },
          { source: 'lang:TypeScript', target: 'fw:Vite', weight: 1 },
          { source: 'lang:Python', target: 'fw:FastAPI', weight: 2 },
        ],
      },
      760,
      560
    )

    expect(layout.nodes).toHaveLength(5)
    expect(layout.links).toHaveLength(3)
    const typescript = layout.nodes.find((node) => node.id === 'lang:TypeScript')
    expect(typescript?.x).toBeCloseTo(380)
    expect(typescript?.y).toBeCloseTo(140)

    const radius = (node: (typeof layout.nodes)[number]) =>
      Math.hypot(node.x - layout.center.x, node.y - layout.center.y)
    for (const node of layout.nodes) {
      expect(radius(node)).toBeCloseTo(
        node.kind === 'language' ? 140 : 210,
        0
      )
    }

    const react = layout.nodes.find((node) => node.id === 'fw:React')
    const link = layout.links.find((item) => item.target === 'fw:React')
    expect(link?.x2).toBeCloseTo(react?.x ?? 0)
    expect(link?.y2).toBeCloseTo(react?.y ?? 0)
  })

  it('skips links whose endpoints are not in the graph', () => {
    const layout = buildRadialLayout({
      nodes: [{ id: 'lang:Go', label: 'Go', kind: 'language', weight: 1 }],
      links: [{ source: 'lang:Go', target: 'fw:Missing', weight: 1 }],
    })
    expect(layout.links).toEqual([])
  })
})
