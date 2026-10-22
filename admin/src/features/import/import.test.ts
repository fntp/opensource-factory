import { describe, expect, it } from 'vitest'
import {
  DEMO_IMPORT_CONTENT,
  FORMAT_OPTIONS,
  MOCK_IMPORT_HISTORY,
  buildDemoPreview,
  buildDemoResult,
  detectDemoFormat,
  formatDateTime,
  formatFileSize,
  formatLabel,
  issueReasonLabel,
} from './utils'
import type { ImportRequest } from './types'

const JSON_REQUEST: ImportRequest = {
  content: DEMO_IMPORT_CONTENT,
  format: 'json',
  useFolders: true,
  createCategories: true,
}

describe('数据导入工具函数', () => {
  it('提供四种格式选项与标签', () => {
    expect(FORMAT_OPTIONS.map((option) => option.key)).toEqual([
      'auto',
      'json',
      'csv',
      'html',
    ])
    expect(formatLabel('html')).toBe('浏览器书签')
    expect(formatLabel('json')).toBe('JSON')
  })

  it('按内容识别演示格式', () => {
    expect(detectDemoFormat('{"repositories": []}')).toBe('json')
    expect(detectDemoFormat('[{"url": "https://github.com/a/b"}]')).toBe('json')
    expect(
      detectDemoFormat('<!DOCTYPE NETSCAPE-Bookmark-file-1><DL><DT><A HREF="x">x</A>')
    ).toBe('html')
    expect(detectDemoFormat('fullName,url\nfoo/bar,https://github.com/foo/bar')).toBe(
      'csv'
    )
  })

  it('演示预览抽取仓库链接、去重并标注状态', () => {
    const content = [
      'https://github.com/ollama/ollama',
      'https://github.com/ollama/ollama.git',
      'https://gitee.com/foo/bar',
      'https://github.com/openai/openai-python/issues/1',
      'https://example.com/not-a-repo',
    ].join('\n')
    const preview = buildDemoPreview({
      content,
      format: 'auto',
      useFolders: true,
      createCategories: true,
    })
    expect(preview.format).toBe('csv')
    expect(preview.total).toBe(3)
    expect(preview.new).toBe(1)
    expect(preview.update).toBe(1)
    expect(preview.conflict).toBe(1)
    expect(preview.sample.map((item) => item.fullName)).toEqual([
      'ollama/ollama',
      'foo/bar',
      'openai/openai-python',
    ])
    expect(preview.sample[0].platform).toBe('github')
    expect(preview.sample[1].platform).toBe('gitee')
  })

  it('演示执行结果与预览统计一致', () => {
    const preview = buildDemoPreview(JSON_REQUEST)
    const result = buildDemoResult(preview)
    expect(result.total).toBe(3)
    expect(result.imported).toBe(1)
    expect(result.updated).toBe(1)
    expect(result.conflicts).toBe(1)
    expect(result.skipped).toBe(1)
    expect(result.format).toBe('json')
    expect(result.runId.startsWith('imp_demo_')).toBe(true)
  })

  it('格式化文件大小与时间', () => {
    expect(formatFileSize(0)).toBe('0 B')
    expect(formatFileSize(512)).toBe('512 B')
    expect(formatFileSize(2048)).toBe('2.0 KB')
    expect(formatFileSize(2 * 1024 * 1024)).toBe('2.00 MB')
    expect(formatDateTime('2026-10-22 10:00:00')).toContain('2026')
    expect(formatDateTime('2026-10-22T10:00:00.000Z')).toContain('2026')
    expect(formatDateTime('')).toBe('-')
  })

  it('错误原因有中文提示，历史演示数据可用', () => {
    expect(issueReasonLabel('invalid_repo')).toBe('无法识别仓库地址')
    expect(issueReasonLabel('unsupported_url')).toBe('非 GitHub / Gitee 仓库链接')
    expect(issueReasonLabel('custom_reason')).toBe('custom_reason')
    expect(MOCK_IMPORT_HISTORY.items.length).toBeGreaterThan(0)
    expect(MOCK_IMPORT_HISTORY.items[0].imported).toBeGreaterThan(0)
  })
})
