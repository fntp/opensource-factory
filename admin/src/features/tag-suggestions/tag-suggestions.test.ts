import { describe, expect, it } from 'vitest'
import { MOCK_TAG_SUGGESTIONS, mockTagSuggestionsPayload } from './api'
import {
  categoryLabel,
  formatScore,
  groupSuggestionsByRepo,
  scoreTone,
  summarizeSuggestions,
  truncateSummary,
} from './utils'

describe('formatScore', () => {
  it('formats 0~1 scores as percentages and clamps invalid values', () => {
    expect(formatScore(0.83)).toBe('83%')
    expect(formatScore(1)).toBe('100%')
    expect(formatScore(0)).toBe('0%')
    expect(formatScore(-1)).toBe('0%')
    expect(formatScore(2)).toBe('100%')
    expect(formatScore(Number.NaN)).toBe('0%')
    expect(formatScore(null)).toBe('0%')
  })
})

describe('categoryLabel / scoreTone', () => {
  it('maps categories to Chinese labels', () => {
    expect(categoryLabel('language')).toBe('语言')
    expect(categoryLabel('framework')).toBe('框架')
    expect(categoryLabel('domain')).toBe('业务域')
    expect(categoryLabel('quality')).toBe('工程属性')
  })

  it('buckets scores for badge colours', () => {
    expect(scoreTone(0.9)).toBe('high')
    expect(scoreTone(0.7)).toBe('medium')
    expect(scoreTone(0.5)).toBe('low')
  })
})

describe('groupSuggestionsByRepo', () => {
  it('groups by repo, sorts items by score and groups by best score', () => {
    const groups = groupSuggestionsByRepo(MOCK_TAG_SUGGESTIONS)
    expect(groups.length).toBeGreaterThan(1)
    for (const group of groups) {
      const scores = group.items.map((item) => item.score)
      expect(scores).toEqual([...scores].sort((a, b) => b - a))
      expect(group.avgScore).toBeGreaterThan(0)
    }
    expect(groups[0].items[0].score).toBeGreaterThanOrEqual(
      groups[groups.length - 1].items[0].score
    )
  })
})

describe('summarizeSuggestions', () => {
  it('counts statuses, repos and average pending score', () => {
    const summary = summarizeSuggestions(MOCK_TAG_SUGGESTIONS)
    const pending = MOCK_TAG_SUGGESTIONS.filter((item) => item.status === 'pending')
    expect(summary.pending).toBe(pending.length)
    expect(summary.accepted).toBe(
      MOCK_TAG_SUGGESTIONS.filter((item) => item.status === 'accepted').length
    )
    expect(summary.repos).toBe(new Set(pending.map((item) => item.repoId)).size)
    expect(summary.avgScore).toBeCloseTo(
      pending.reduce((sum, item) => sum + item.score, 0) / pending.length,
      5
    )
  })

  it('returns null average when nothing is pending', () => {
    const summary = summarizeSuggestions(
      MOCK_TAG_SUGGESTIONS.filter((item) => item.status !== 'pending')
    )
    expect(summary.pending).toBe(0)
    expect(summary.avgScore).toBeNull()
  })
})

describe('mockTagSuggestionsPayload', () => {
  it('filters by status and keeps global summary', () => {
    const pending = mockTagSuggestionsPayload('pending')
    expect(pending.items.every((item) => item.status === 'pending')).toBe(true)
    expect(pending.summary.pending).toBe(pending.total)

    const all = mockTagSuggestionsPayload('all')
    expect(all.total).toBe(MOCK_TAG_SUGGESTIONS.length)
    expect(all.summary.accepted).toBeGreaterThan(0)
    expect(all.summary.dismissed).toBeGreaterThan(0)
  })
})

describe('truncateSummary', () => {
  it('keeps short text and truncates long text', () => {
    expect(truncateSummary('短摘要')).toBe('短摘要')
    const long = 'a'.repeat(200)
    expect(truncateSummary(long, 50)).toHaveLength(51)
    expect(truncateSummary(long, 50).endsWith('…')).toBe(true)
  })
})
