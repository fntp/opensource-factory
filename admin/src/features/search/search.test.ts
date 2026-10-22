import { describe, expect, it } from 'vitest'
import {
  formatScore,
  isQueryValid,
  modeLabel,
  normalizeQuery,
  scopeLabel,
  understandingLabels,
} from './utils'

describe('语义搜索工具函数', () => {
  it('归一化查询：去首尾空白并压缩连续空白', () => {
    expect(normalizeQuery('  多租户   NestJS  ')).toBe('多租户 NestJS')
    expect(normalizeQuery('a\n\tb')).toBe('a b')
  })

  it('校验查询长度 1~200', () => {
    expect(isQueryValid('   ')).toBe(false)
    expect(isQueryValid('x')).toBe(true)
    expect(isQueryValid('x'.repeat(200))).toBe(true)
    expect(isQueryValid('x'.repeat(201))).toBe(false)
  })

  it('匹配度格式化为百分比并夹取 0~1', () => {
    expect(formatScore(0.8734)).toBe('87%')
    expect(formatScore(-1)).toBe('0%')
    expect(formatScore(2)).toBe('100%')
    expect(formatScore(Number.NaN)).toBe('0%')
  })

  it('来源与模式标签', () => {
    expect(scopeLabel('my')).toBe('我的仓库')
    expect(scopeLabel('trending')).toBe('每日热榜')
    expect(scopeLabel('all')).toBe('全部来源')
    expect(modeLabel('vectorize')).toContain('Vectorize')
    expect(modeLabel('local')).toContain('本地')
    expect(modeLabel('keyword')).toContain('关键词')
  })

  it('查询理解标签：技术栈在前、概念在后并去重', () => {
    const understanding = {
      query: 'k8s 部署',
      rewritten: 'k8s 部署 Kubernetes deployment',
      expanded: true,
      techStack: ['Kubernetes'],
      concepts: ['部署', 'Kubernetes'],
      terms: ['Kubernetes', 'deployment'],
      keywordTerms: ['k8s 部署', 'Kubernetes'],
      maxTerms: 12,
    }
    expect(understandingLabels(understanding)).toEqual(['Kubernetes', '部署'])
    expect(understandingLabels({ ...understanding, expanded: false })).toEqual([])
    expect(understandingLabels(undefined)).toEqual([])
  })
})
