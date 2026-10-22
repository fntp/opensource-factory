import { describe, expect, it } from 'vitest'
import {
  MOCK_AGENT_RUN,
  MOCK_AGENT_TEMPLATES,
} from './api'
import {
  agentDraftFilename,
  agentDraftStatusLabel,
  agentModeLabel,
  agentRunStatusLabel,
  agentStatCards,
  agentTemplateLabel,
  formatAgentCount,
  formatAgentStars,
  formatAgentThreshold,
  formatAgentTime,
  isAgentStepReady,
} from './utils'

describe('agent labels', () => {
  it('maps templates, modes and statuses to Chinese labels', () => {
    expect(agentTemplateLabel('organize')).toBe('自动整理')
    expect(agentTemplateLabel('draft')).toBe('收藏草稿')
    expect(agentTemplateLabel('full')).toBe('整理 + 草稿')
    expect(agentModeLabel('preview')).toBe('预览')
    expect(agentModeLabel('apply')).toBe('直接应用')
    expect(agentRunStatusLabel('completed')).toBe('已完成')
    expect(agentRunStatusLabel('failed')).toBe('失败')
    expect(agentDraftStatusLabel('draft')).toBe('草稿')
    expect(agentDraftStatusLabel('applied')).toBe('已采用')
    expect(agentDraftStatusLabel('discarded')).toBe('已丢弃')
  })
})

describe('agent formatting', () => {
  it('formats counts and stars', () => {
    expect(formatAgentCount(1234567)).toBe('1,234,567')
    expect(formatAgentCount(Number.NaN)).toBe('—')
    expect(formatAgentStars(624900)).toBe('62.5 万')
    expect(formatAgentStars(1200)).toBe('1.2k')
    expect(formatAgentStars(42)).toBe('42')
  })

  it('formats thresholds and times', () => {
    expect(formatAgentThreshold(0.75)).toBe('75%')
    expect(formatAgentThreshold(1)).toBe('100%')
    expect(formatAgentTime('2026-10-22T08:30:00.000Z')).not.toBe('—')
    expect(formatAgentTime('bad')).toBe('—')
    expect(formatAgentTime(null)).toBe('—')
  })

  it('builds four stat cards', () => {
    const cards = agentStatCards(MOCK_AGENT_RUN.result.stats)
    expect(cards).toHaveLength(4)
    expect(cards[0]).toMatchObject({ title: '收藏总数', value: '24' })
    expect(cards[1]?.value).toBe('62.5 万')
    expect(cards[2]?.value).toBe('TypeScript')
    expect(cards[3]?.value).toBe('AI 工具')
  })

  it('exposes plan-step readiness and draft filename helpers', () => {
    expect(isAgentStepReady('ready')).toBe(true)
    expect(isAgentStepReady('skipped')).toBe(false)
    expect(agentDraftFilename('draft_123')).toBe('draft_123.md')
    expect(agentDraftFilename('')).toBe('agent-draft.md')
  })
})

describe('mock agent data', () => {
  it('keeps templates and run contracts aligned', () => {
    expect(MOCK_AGENT_TEMPLATES.map((item) => item.key)).toEqual([
      'organize',
      'draft',
      'full',
    ])
    expect(MOCK_AGENT_RUN.plan.map((step) => step.key)).toEqual([
      'inventory',
      'tags',
      'categories',
      'draft',
    ])
    expect(MOCK_AGENT_RUN.draft).not.toBeNull()
    expect(MOCK_AGENT_RUN.draft?.content).toContain('## 概览')
    expect(MOCK_AGENT_RUN.draft?.content).toContain('## 发布清单')
    expect(MOCK_AGENT_RUN.result.appliedTags.length).toBeGreaterThan(0)
    expect(MOCK_AGENT_RUN.result.appliedCategories.length).toBeGreaterThan(0)
  })
})
