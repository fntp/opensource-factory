import { describe, expect, it } from 'vitest'
import {
  evaluateHealth,
  healthBadgeClass,
  healthForRepo,
  normalizeHealthStatus,
  summarizeRepoHealth,
} from './health'

const NOW = new Date('2026-10-22T10:00:00Z')
const daysAgo = (days: number) =>
  new Date(NOW.getTime() - days * 24 * 60 * 60 * 1000).toISOString()

describe('evaluateHealth', () => {
  it('按最后提交天数分档', () => {
    expect(
      evaluateHealth({ lastPushAt: daysAgo(10), stars: 100, now: NOW })
    ).toMatchObject({ status: 'active', score: 100, daysSincePush: 10 })
    expect(
      evaluateHealth({ lastPushAt: daysAgo(120), stars: 100, now: NOW })
    ).toMatchObject({ status: 'attention', score: 75 })
    expect(
      evaluateHealth({ lastPushAt: daysAgo(400), stars: 100, now: NOW })
    ).toMatchObject({ status: 'stale', score: 25 })
  })

  it('归档与未知优先处理', () => {
    expect(
      evaluateHealth({ lastPushAt: daysAgo(1), archived: true, now: NOW })
    ).toMatchObject({ status: 'archived', score: 0 })
    expect(evaluateHealth({ lastPushAt: null, now: NOW })).toMatchObject({
      status: 'unknown',
      score: 0,
    })
  })

  it('issue 压力只扣分不改状态', () => {
    const health = evaluateHealth({
      lastPushAt: daysAgo(5),
      openIssues: 60,
      stars: 100,
      now: NOW,
    })
    expect(health.status).toBe('active')
    expect(health.score).toBe(80)
  })
})

describe('healthForRepo', () => {
  it('优先使用接口返回的健康度', () => {
    const health = evaluateHealth({ lastPushAt: daysAgo(3), now: NOW })
    expect(
      healthForRepo({ updatedAt: '2020-01-01', stars: 1, health })
    ).toBe(health)
  })

  it('缺失时按最近更新时间兜底', () => {
    const health = healthForRepo({ updatedAt: daysAgo(10), stars: 100 })
    expect(health.status).toBe('active')
  })
})

describe('summarizeRepoHealth', () => {
  it('统计各状态数量与平均分', () => {
    const summary = summarizeRepoHealth([
      { health: evaluateHealth({ lastPushAt: daysAgo(1), now: NOW }) },
      { health: evaluateHealth({ lastPushAt: daysAgo(120), now: NOW }) },
      { health: evaluateHealth({ lastPushAt: null, now: NOW }) },
    ])
    expect(summary).toMatchObject({
      total: 3,
      active: 1,
      attention: 1,
      unknown: 1,
    })
    expect(summary.averageScore).toBeGreaterThan(0)
  })
})

describe('展示辅助', () => {
  it('归一化非法状态并区分徽章配色', () => {
    expect(normalizeHealthStatus('ARCHIVED')).toBe('archived')
    expect(normalizeHealthStatus('bogus')).toBe('unknown')
    const classes = new Set(
      (['active', 'attention', 'stale', 'archived', 'unknown'] as const).map(
        healthBadgeClass
      )
    )
    expect(classes.size).toBe(5)
  })
})
