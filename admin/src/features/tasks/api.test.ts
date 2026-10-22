import { describe, expect, it } from 'vitest'
import {
  isTaskActive,
  taskDuration,
  taskProgressPercent,
  taskResultSummary,
  taskStatusLabel,
  taskTypeLabel,
  type SyncTask,
} from './api'

function makeTask(overrides: Partial<SyncTask> = {}): SyncTask {
  return {
    taskId: 'task-1',
    type: 'sync',
    status: 'pending',
    progress: null,
    result: null,
    error: null,
    createdAt: '2026-10-22T04:00:00.000Z',
    updatedAt: '2026-10-22T04:00:00.000Z',
    finishedAt: null,
    ...overrides,
  }
}

describe('task helpers', () => {
  it('maps status and type labels with fallbacks', () => {
    expect(taskStatusLabel('progress')).toBe('同步中')
    expect(taskStatusLabel('success')).toBe('已完成')
    expect(taskStatusLabel('weird')).toBe('未知')
    expect(taskTypeLabel('sync-starred')).toBe('Starred 全量同步')
    expect(taskTypeLabel('custom')).toBe('custom')
  })

  it('detects active statuses', () => {
    expect(isTaskActive('pending')).toBe(true)
    expect(isTaskActive('started')).toBe(true)
    expect(isTaskActive('progress')).toBe(true)
    expect(isTaskActive('success')).toBe(false)
    expect(isTaskActive('failure')).toBe(false)
  })

  it('calculates progress percent with clamps and fallbacks', () => {
    expect(taskProgressPercent(makeTask({ progress: { percent: 40 } }))).toBe(
      40
    )
    expect(taskProgressPercent(makeTask({ progress: { percent: 120 } }))).toBe(
      100
    )
    expect(taskProgressPercent(makeTask({ status: 'success' }))).toBe(100)
    expect(taskProgressPercent(makeTask({ status: 'pending' }))).toBe(0)
  })

  it('formats duration from creation to finish', () => {
    expect(
      taskDuration(
        makeTask({
          finishedAt: '2026-10-22T04:01:12.000Z',
        })
      )
    ).toBe('1m 12s')
    expect(
      taskDuration(
        makeTask({
          updatedAt: '2026-10-22T04:00:10.000Z',
        })
      )
    ).toBe('10s')
  })

  it('summarizes results and prefers errors', () => {
    expect(
      taskResultSummary(
        makeTask({
          status: 'success',
          result: { status: 'ok', total: 128, created: 12, updated: 116 },
        })
      )
    ).toBe('共 128 个仓库 · 新增 12 · 更新 116')
    expect(
      taskResultSummary(
        makeTask({ error: '限流', result: { status: 'error' } })
      )
    ).toBe('限流')
    expect(
      taskResultSummary(
        makeTask({
          result: { status: 'skipped', reason: 'GITHUB_TOKEN 未配置' },
        })
      )
    ).toBe('GITHUB_TOKEN 未配置')
    expect(taskResultSummary(makeTask())).toBe('—')
  })
})
