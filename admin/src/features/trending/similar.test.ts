import { describe, expect, it } from 'vitest'
import { buildSimilarFallback, similarReposPath } from './api'

describe('similar recommendations helpers', () => {
  it('encodes repoId as a single query value', () => {
    expect(similarReposPath('trending', 'openai/whisper', 6)).toBe(
      '/api/similar?source=trending&repoId=openai%2Fwhisper&topK=6'
    )
  })

  it('excludes the seed and ranks same-language projects first', () => {
    const items = buildSimilarFallback('langchain-ai/langchain', 3)
    expect(items).toHaveLength(3)
    expect(items.map((item) => item.fullName)).not.toContain(
      'langchain-ai/langchain'
    )
    expect(items[0].language).toBe('Python')
    expect(items[0].reason).toContain('langchain')
    expect(items.every((item) => item.source === 'trending')).toBe(true)
    expect(items.every((item) => item.score > 0)).toBe(true)
    const scores = items.map((item) => item.score)
    expect([...scores].sort((a, b) => b - a)).toEqual(scores)
  })

  it('still returns fallback items for an unknown seed', () => {
    const items = buildSimilarFallback('unknown/repo', 2)
    expect(items).toHaveLength(2)
    expect(items.every((item) => item.reason.length > 0)).toBe(true)
  })
})
