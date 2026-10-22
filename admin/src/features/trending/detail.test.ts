import { describe, expect, it } from 'vitest'
import type { TrendingRepoDetail } from './api'
import { buildMetaItems, repoRouteParams, summarySourceLabel } from './detail'

const detail: TrendingRepoDetail = {
  id: 'openai/whisper',
  owner: 'openai',
  name: 'whisper',
  description: 'Robust Speech Recognition',
  language: 'Python',
  stars: 65432,
  starsToday: 1234,
  url: 'https://github.com/openai/whisper',
  platform: 'github',
  techStack: ['Python', 'PyTorch'],
  summary: '语音识别模型',
  summarySource: 'readme',
  crawledAt: '2026-10-22',
  isFavorited: false,
}

describe('trending detail helpers', () => {
  it('maps summary sources to Chinese labels', () => {
    expect(summarySourceLabel('readme')).toBe('README 摘要')
    expect(summarySourceLabel('description')).toBe('项目描述')
    expect(summarySourceLabel('tech')).toBe('技术栈提示')
    expect(summarySourceLabel('empty')).toBe('暂无摘要')
  })

  it('builds metadata items with formatted stars and fallbacks', () => {
    const items = buildMetaItems(detail)
    expect(items).toContainEqual({ label: '总 Star', value: '65,432' })
    expect(items).toContainEqual({ label: '今日 Star', value: '+1,234' })
    expect(items).toContainEqual({ label: '技术栈', value: 'Python · PyTorch' })
    expect(items).toContainEqual({ label: '抓取日期', value: '2026-10-22' })

    const empty = buildMetaItems({ ...detail, language: '', techStack: [], crawledAt: null })
    expect(empty).toContainEqual({ label: '主语言', value: '—' })
    expect(empty).toContainEqual({ label: '技术栈', value: '—' })
    expect(empty).toContainEqual({ label: '抓取日期', value: '—' })
  })

  it('splits repo id into route params only for owner/repo', () => {
    expect(repoRouteParams('openai/whisper')).toEqual({
      owner: 'openai',
      name: 'whisper',
    })
    expect(repoRouteParams('openai')).toBeNull()
    expect(repoRouteParams('a/b/c')).toBeNull()
  })
})
