import { describe, expect, it } from 'vitest'
import { MOCK_REPOS } from './api'
import {
  buildReposQuery,
  countActiveFilters,
  DEFAULT_REPO_FILTERS,
  filterAndSortRepos,
  starRangeToBounds,
  timeRangeToAfter,
  type RepoFilters,
} from './filters'

const NOW = new Date('2026-10-22T08:00:00.000Z')

function filters(patch: Partial<RepoFilters> = {}): RepoFilters {
  return { ...DEFAULT_REPO_FILTERS, ...patch }
}

describe('buildReposQuery', () => {
  it('默认筛选不产生查询串（与 facet 查询共享缓存）', () => {
    expect(buildReposQuery(DEFAULT_REPO_FILTERS, NOW)).toBe('')
  })

  it('组合筛选与排序生成完整查询串', () => {
    const query = buildReposQuery(
      filters({
        keyword: '  react ',
        categoryId: '1',
        tagNames: ['LLM', '框架'],
        languages: ['TypeScript', 'Python'],
        starRange: '1k-10k',
        timeRange: '30d',
        sort: 'updated',
        order: 'asc',
      }),
      NOW
    )
    const params = new URLSearchParams(query)
    expect(params.get('q')).toBe('react')
    expect(params.get('categoryId')).toBe('1')
    expect(params.get('tags')).toBe('LLM,框架')
    expect(params.get('languages')).toBe('TypeScript,Python')
    expect(params.get('starsMin')).toBe('1000')
    expect(params.get('starsMax')).toBe('9999')
    expect(params.get('updatedAfter')).toBe('2026-09-23')
    expect(params.get('sort')).toBe('updated')
    expect(params.get('order')).toBe('asc')
  })
})

describe('starRangeToBounds', () => {
  it('预设区间无间隙、无重叠', () => {
    expect(starRangeToBounds('all')).toEqual({})
    expect(starRangeToBounds('lt1k')).toEqual({ max: 999 })
    expect(starRangeToBounds('1k-10k')).toEqual({ min: 1000, max: 9999 })
    expect(starRangeToBounds('10k-50k')).toEqual({ min: 10000, max: 49999 })
    expect(starRangeToBounds('gte50k')).toEqual({ min: 50000 })
  })
})

describe('timeRangeToAfter', () => {
  it('按 UTC 当天向前推算，含当天', () => {
    expect(timeRangeToAfter('all', NOW)).toBeUndefined()
    expect(timeRangeToAfter('7d', NOW)).toBe('2026-10-16')
    expect(timeRangeToAfter('30d', NOW)).toBe('2026-09-23')
    expect(timeRangeToAfter('90d', NOW)).toBe('2026-07-25')
    expect(timeRangeToAfter('1y', NOW)).toBe('2025-10-23')
  })
})

describe('filterAndSortRepos', () => {
  it('标签多选为 AND 语义', () => {
    const result = filterAndSortRepos(
      MOCK_REPOS,
      filters({ tagNames: ['LLM', '框架'] }),
      NOW
    )
    expect(result.map((repo) => repo.fullName)).toEqual([
      'langchain-ai/langchain',
    ])
  })

  it('语言、Star、时间与分类可组合', () => {
    const result = filterAndSortRepos(
      MOCK_REPOS,
      filters({
        languages: ['TypeScript'],
        categoryId: '2',
        starRange: 'gte50k',
        timeRange: '30d',
      }),
      NOW
    )
    expect(result.map((repo) => repo.fullName)).toEqual(['shadcn-ui/ui'])
  })

  it('默认按 Star 降序，支持升序与名称排序', () => {
    const desc = filterAndSortRepos(MOCK_REPOS, DEFAULT_REPO_FILTERS, NOW)
    expect(desc[0]?.stars).toBe(102340)

    const asc = filterAndSortRepos(MOCK_REPOS, filters({ order: 'asc' }), NOW)
    expect(asc[0]?.stars).toBe(128)

    const byName = filterAndSortRepos(
      MOCK_REPOS,
      filters({ sort: 'name', order: 'asc' }),
      NOW
    )
    expect(byName[0]?.fullName).toBe('fastapi/fastapi')
  })

  it('关键词匹配描述、语言、分类与标签', () => {
    const byTag = filterAndSortRepos(
      MOCK_REPOS,
      filters({ keyword: '本地模型' }),
      NOW
    )
    expect(byTag.map((repo) => repo.fullName)).toEqual(['ollama/ollama'])

    const byLanguage = filterAndSortRepos(
      MOCK_REPOS,
      filters({ keyword: 'python' }),
      NOW
    )
    expect(byLanguage.map((repo) => repo.fullName).sort()).toEqual([
      'fastapi/fastapi',
      'langchain-ai/langchain',
    ])
  })
})

describe('countActiveFilters', () => {
  it('按筛选组计数，排序不算筛选', () => {
    expect(countActiveFilters(DEFAULT_REPO_FILTERS)).toBe(0)
    expect(
      countActiveFilters(
        filters({
          keyword: 'x',
          categoryId: '1',
          tagNames: ['a', 'b'],
          languages: ['Go'],
          starRange: 'lt1k',
          timeRange: '7d',
          sort: 'name',
          order: 'asc',
        })
      )
    ).toBe(6)
  })
})
