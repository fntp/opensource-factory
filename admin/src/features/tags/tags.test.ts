import { describe, expect, it } from 'vitest'
import type { Tag } from './api'
import {
  filterTags,
  normalizeTagName,
  sortTags,
  summarizeTags,
  validateTagName,
} from './tags'

const TAGS: Tag[] = [
  { id: 1, name: 'LLM', count: 18 },
  { id: 2, name: 'Python', count: 16 },
  { id: 3, name: 'TypeScript', count: 16 },
  { id: 4, name: '框架', count: 12 },
  { id: 5, name: '工具', count: 0 },
]

describe('标签名称处理', () => {
  it('归一化空白', () => {
    expect(normalizeTagName('  React   Hooks ')).toBe('React Hooks')
  })

  it('校验空名 / 逗号 / 超长', () => {
    expect(validateTagName('   ')).toContain('不能为空')
    expect(validateTagName('a,b')).toContain('逗号')
    expect(validateTagName('x'.repeat(51))).toContain('50')
    expect(validateTagName('大模型')).toBeNull()
  })
})

describe('标签列表处理', () => {
  it('按名称大小写不敏感过滤', () => {
    expect(filterTags(TAGS, 'python').map((tag) => tag.name)).toEqual([
      'Python',
    ])
    expect(filterTags(TAGS, '框架').map((tag) => tag.name)).toEqual(['框架'])
    expect(filterTags(TAGS, '  ')).toHaveLength(TAGS.length)
  })

  it('按引用数降序，计数相同按名称排序', () => {
    const sorted = sortTags(TAGS, 'count', 'desc')
    expect(sorted.map((tag) => tag.name)).toEqual([
      'LLM',
      'Python',
      'TypeScript',
      '框架',
      '工具',
    ])
  })

  it('按名称升序', () => {
    const sorted = sortTags(TAGS, 'name', 'asc')
    expect(sorted.map((tag) => tag.name)).toEqual([
      'LLM',
      'Python',
      'TypeScript',
      '工具',
      '框架',
    ])
  })

  it('汇总总数 / 已引用数 / 关联总数', () => {
    expect(summarizeTags(TAGS)).toEqual({
      total: 5,
      used: 4,
      references: 62,
    })
  })
})
