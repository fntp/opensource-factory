import { describe, expect, it } from 'vitest'
import { crc32 } from './zip'
import {
  buildDemoExport,
  buildDemoKnowledgeExport,
  buildDemoMarkdown,
  buildDemoObsidianEntries,
  fallbackFileName,
  FORMAT_OPTIONS,
  formatCompactNumber,
} from './utils'

const NOW = '2026-10-22T10:00:00.000Z'

function readZipNames(bytes: Uint8Array): string[] {
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength)
  let eocd = -1
  for (let i = bytes.length - 22; i >= 0; i -= 1) {
    if (view.getUint32(i, true) === 0x06054b50) {
      eocd = i
      break
    }
  }
  if (eocd < 0) throw new Error('missing EOCD')
  const total = view.getUint16(eocd + 10, true)
  let offset = view.getUint32(eocd + 16, true)
  const decoder = new TextDecoder()
  const names: string[] = []
  for (let i = 0; i < total; i += 1) {
    if (view.getUint32(offset, true) !== 0x02014b50) {
      throw new Error('bad central directory')
    }
    const nameLength = view.getUint16(offset + 28, true)
    const extraLength = view.getUint16(offset + 30, true)
    const commentLength = view.getUint16(offset + 32, true)
    names.push(
      decoder.decode(bytes.slice(offset + 46, offset + 46 + nameLength))
    )
    offset += 46 + nameLength + extraLength + commentLength
  }
  return names
}

describe('知识库导出工具函数', () => {
  it('提供三种导出格式与文件名', () => {
    expect(FORMAT_OPTIONS.map((option) => option.key)).toEqual([
      'markdown',
      'json',
      'obsidian',
    ])
    expect(fallbackFileName('markdown', NOW)).toBe(
      'openfactory-knowledge-2026-10-22.md'
    )
    expect(fallbackFileName('json', NOW)).toBe(
      'openfactory-knowledge-2026-10-22.json'
    )
    expect(fallbackFileName('obsidian', NOW)).toBe(
      'openfactory-obsidian-vault-2026-10-22.zip'
    )
  })

  it('聚合演示数据统计并按 Star 降序', () => {
    const data = buildDemoKnowledgeExport(NOW)
    expect(data.schema).toBe('openfactory.knowledge.v1')
    expect(data.stats.totalRepos).toBe(4)
    expect(data.stats.withSummary).toBe(4)
    expect(data.stats.categories).toBe(3)
    expect(data.stats.totalStars).toBe(357270)
    expect(data.repositories[0].fullName).toBe('ollama/ollama')
    expect(data.repositories[data.repositories.length - 1].fullName).toBe(
      'shadcn-ui/ui'
    )
  })

  it('Markdown 导出包含 frontmatter、分类与摘要，可关闭摘要', () => {
    const data = buildDemoKnowledgeExport(NOW)
    const markdown = buildDemoMarkdown(data, {
      format: 'markdown',
      includeSummary: true,
      groupBy: 'category',
    })
    expect(markdown).toMatch(/^---\ntitle: "我的开源知识库（演示）"/)
    expect(markdown).toContain('## AI/LLM')
    expect(markdown).toContain('### [ollama/ollama](https://github.com/ollama/ollama)')
    expect(markdown).toContain('**摘要**：本地模型运行时')

    const withoutSummary = buildDemoMarkdown(data, {
      format: 'markdown',
      includeSummary: false,
      groupBy: 'none',
    })
    expect(withoutSummary).not.toContain('**摘要**')
    expect(withoutSummary).toContain('## 全部项目')
  })

  it('Obsidian 导出生成 README、分类笔记与仓库笔记', () => {
    const data = buildDemoKnowledgeExport(NOW)
    const entries = buildDemoObsidianEntries(data, {
      format: 'obsidian',
      includeSummary: true,
      groupBy: 'category',
    })
    const names = entries.map((entry) => entry.name)
    expect(names).toContain('README.md')
    expect(names).toContain('20-分类/AI-LLM.md')
    expect(names).toContain('10-项目/AI-LLM/ollama--ollama.md')
    const note = entries.find(
      (entry) => entry.name === '10-项目/AI-LLM/ollama--ollama.md'
    )
    expect(note?.content).toContain('title: "ollama/ollama"')
    expect(note?.content).toContain('"tag/本地模型"')
    expect(note?.content).toContain('## 摘要')
  })

  it('JSON 与 Obsidian 导出产出正确的 Blob 内容', () => {
    const json = buildDemoExport(
      { format: 'json', includeSummary: true, groupBy: 'category' },
      NOW
    )
    expect(json.fileName).toBe('openfactory-knowledge-2026-10-22.json')
    expect(JSON.parse(String(json.body)).schema).toBe('openfactory.knowledge.v1')

    const zip = buildDemoExport(
      { format: 'obsidian', includeSummary: true, groupBy: 'category' },
      NOW
    )
    expect(zip.contentType).toBe('application/zip')
    const bytes = zip.body as Uint8Array
    expect([bytes[0], bytes[1]]).toEqual([0x50, 0x4b])
    expect(readZipNames(bytes)).toContain('README.md')
  })

  it('CRC32 与数字格式化', () => {
    expect(crc32(new TextEncoder().encode('hello'))).toBe(0x3610a686)
    expect(formatCompactNumber(999)).toBe('999')
    expect(formatCompactNumber(1200)).toBe('1.2k')
    expect(formatCompactNumber(0)).toBe('0')
  })
})
