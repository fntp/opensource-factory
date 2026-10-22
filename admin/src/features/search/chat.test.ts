import { describe, expect, it } from 'vitest'
import type { ChatResultItem } from './api'
import {
  chatModeLabel,
  chatScopeLabel,
  citationLabel,
  collectShownIds,
  formatChatTime,
  historyForRequest,
  intentLabel,
  isChatContentValid,
  normalizeChatContent,
} from './chat-utils'

const item = (id: string): ChatResultItem => ({
  id,
  source: 'my',
  fullName: id,
  name: id.split('/')[1] ?? id,
  description: '',
  language: 'Rust',
  stars: 1,
  starsToday: 0,
  url: `https://example.com/${id}`,
  score: 0.9,
  reason: '',
  citation: 1,
})

describe('问答检索工具函数', () => {
  it('归一化提问：去首尾空白并压缩连续空白', () => {
    expect(normalizeChatContent('  那  Rust   的呢？ ')).toBe('那 Rust 的呢？')
    expect(normalizeChatContent('a\n\tb')).toBe('a b')
  })

  it('校验提问长度 1~500', () => {
    expect(isChatContentValid('   ')).toBe(false)
    expect(isChatContentValid('x')).toBe(true)
    expect(isChatContentValid('x'.repeat(500))).toBe(true)
    expect(isChatContentValid('x'.repeat(501))).toBe(false)
  })

  it('历史裁剪只保留最近 20 条', () => {
    const messages = Array.from({ length: 25 }, (_, index) => ({
      role: 'user' as const,
      content: `问题 ${index}`,
    }))
    const trimmed = historyForRequest(messages)
    expect(trimmed).toHaveLength(20)
    expect(trimmed[0]?.content).toBe('问题 5')
    expect(trimmed[19]?.content).toBe('问题 24')
  })

  it('汇总已展示项目 id：去重、忽略用户消息与重复项', () => {
    const ids = collectShownIds([
      { role: 'user' },
      { role: 'assistant', items: [item('a/b'), item('c/d')] },
      { role: 'assistant', items: [item('a/b'), item('e/f')] },
    ])
    expect(ids).toEqual(['a/b', 'c/d', 'e/f'])
  })

  it('展示标签与引用编号', () => {
    expect(chatModeLabel('hybrid')).toBe('混合检索')
    expect(chatModeLabel('vector')).toBe('向量检索')
    expect(chatModeLabel('keyword')).toContain('关键词')
    expect(chatScopeLabel('auto')).toBe('自动判断')
    expect(chatScopeLabel('my')).toBe('我的仓库')
    expect(intentLabel('count')).toBe('数量统计')
    expect(intentLabel('more')).toBe('继续翻页')
    expect(intentLabel('detail')).toBe('项目详情')
    expect(intentLabel('compare')).toBe('来源对比')
    expect(intentLabel('list')).toBe('项目列表')
    expect(citationLabel(3)).toBe('[3]')
    expect(citationLabel(Number.NaN)).toBe('[0]')
  })

  it('时间格式化为 HH:mm', () => {
    expect(formatChatTime('2026-10-22T08:30:00.000Z')).toMatch(/^\d{2}:\d{2}$/)
    expect(formatChatTime('not-a-date')).toBe('')
  })
})
