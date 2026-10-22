import type {
  DetectedFormat,
  ImportFormat,
  ImportHistoryResponse,
  ImportPreview,
  ImportRequest,
  ImportResult,
  ImportSampleItem,
  ImportStatus,
} from './types'

/** 与 edge 端 parse.ts 保持一致的上限 */
export const MAX_CONTENT_LENGTH = 2_000_000
export const MAX_IMPORT_ENTRIES = 2_000

export const FORMAT_OPTIONS: Array<{
  key: ImportFormat
  label: string
  description: string
  accept: string
}> = [
  {
    key: 'auto',
    label: '自动识别',
    description: '根据内容判断 JSON / CSV / 浏览器书签 HTML',
    accept: '.json,.csv,.txt,.html,.htm',
  },
  {
    key: 'json',
    label: 'JSON',
    description: 'openfactory.knowledge.v1、{ items } 或对象数组',
    accept: '.json,.txt',
  },
  {
    key: 'csv',
    label: 'CSV',
    description: '逗号 / 制表符 / 分号分隔，支持引号字段',
    accept: '.csv,.tsv,.txt',
  },
  {
    key: 'html',
    label: '浏览器书签',
    description: 'Chrome / Edge / Firefox 导出的 Netscape 书签 HTML',
    accept: '.html,.htm',
  },
]

export const STATUS_LABELS: Record<ImportStatus, string> = {
  new: '新增',
  update: '更新',
  conflict: '冲突',
}

export const ISSUE_REASON_LABELS: Record<string, string> = {
  invalid_repo: '无法识别仓库地址',
  invalid_json: 'JSON 解析失败',
  invalid_json_structure: 'JSON 结构不支持',
  invalid_row: '行内容无效',
  empty_content: '内容为空',
  missing_header: '缺少可识别表头',
  missing_url: '缺少链接',
  unsupported_url: '非 GitHub / Gitee 仓库链接',
}

export function issueReasonLabel(reason: string): string {
  return ISSUE_REASON_LABELS[reason] ?? reason
}

export function formatLabel(format: DetectedFormat | ImportFormat): string {
  return FORMAT_OPTIONS.find((option) => option.key === format)?.label ?? '未知格式'
}

export function formatFileSize(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes <= 0) return '0 B'
  if (bytes < 1024) return `${Math.round(bytes)} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`
}

/** SQLite CURRENT_TIMESTAMP（UTC）与 ISO 时间都兼容 */
export function formatDateTime(value: string): string {
  if (!value) return '-'
  const normalized = value.includes('T')
    ? value
    : `${value.replace(' ', 'T')}Z`
  const date = new Date(normalized)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat('zh-CN', {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(date)
}

export function detectDemoFormat(content: string): DetectedFormat {
  const trimmed = content.trim()
  if (trimmed.startsWith('{') || trimmed.startsWith('[')) return 'json'
  if (/netscape-bookmark-file|<a\s+[^>]*href=/i.test(content)) return 'html'
  return 'csv'
}

const REPO_URL_RE =
  /https?:\/\/(?:www\.)?(github|gitee)\.com\/([A-Za-z0-9_.-]+)\/([A-Za-z0-9_.-]+)/gi

function extractDemoEntries(content: string): ImportSampleItem[] {
  const seen = new Set<string>()
  const items: ImportSampleItem[] = []
  for (const match of content.matchAll(REPO_URL_RE)) {
    const platform = match[1].toLowerCase() as 'github' | 'gitee'
    const owner = match[2]
    const name = match[3].replace(/\.git$/i, '')
    const id = `${owner}/${name}`.toLowerCase()
    if (seen.has(id)) continue
    seen.add(id)
    items.push({
      fullName: `${owner}/${name}`,
      platform,
      url: `https://${platform}.com/${owner}/${name}`,
      description: null,
      language: null,
      stars: 0,
      category: null,
      tags: [],
      status: 'new',
    })
    if (items.length >= MAX_IMPORT_ENTRIES) break
  }
  return items
}

/** 演示模式预览：用正则抽取仓库链接，并给出稳定的三种状态样例 */
export function buildDemoPreview(request: ImportRequest): ImportPreview {
  const format =
    request.format === 'auto' ? detectDemoFormat(request.content) : request.format
  const entries = extractDemoEntries(request.content)
  const sample = entries.slice(0, 50).map((item, index) => ({
    ...item,
    status: (index === 1 ? 'update' : index === 2 ? 'conflict' : 'new') as ImportStatus,
  }))
  const conflict = sample.filter((item) => item.status === 'conflict').length
  const update = sample.filter((item) => item.status === 'update').length
  return {
    format,
    total: entries.length,
    new: entries.length - conflict - update,
    update,
    conflict,
    invalid: 0,
    duplicates: 0,
    truncated: entries.length >= MAX_IMPORT_ENTRIES,
    sample,
    issues: [],
  }
}

export function buildDemoResult(preview: ImportPreview): ImportResult {
  const updated = preview.update
  const conflicts = preview.conflict
  return {
    runId: `imp_demo_${Date.now().toString(36)}`,
    format: preview.format,
    total: preview.total,
    imported: preview.new,
    updated,
    skipped: conflicts + preview.invalid,
    conflicts,
    invalid: preview.invalid,
    duplicates: preview.duplicates,
    categoriesCreated: 0,
    tagsCreated: 0,
    tagsLinked: 0,
    truncated: preview.truncated,
  }
}

export const MOCK_IMPORT_HISTORY: ImportHistoryResponse = {
  items: [
    {
      id: 'imp_demo_1',
      format: 'html',
      status: 'completed',
      total: 128,
      imported: 96,
      updated: 24,
      skipped: 8,
      conflicts: 6,
      invalid: 2,
      categoriesCreated: 4,
      tagsCreated: 11,
      createdAt: '2026-10-20 09:30:00',
    },
    {
      id: 'imp_demo_2',
      format: 'json',
      status: 'completed',
      total: 32,
      imported: 20,
      updated: 10,
      skipped: 2,
      conflicts: 2,
      invalid: 0,
      categoriesCreated: 1,
      tagsCreated: 3,
      createdAt: '2026-10-12 16:05:00',
    },
  ],
}

/** 演示模式「填入示例」内容，同时覆盖 JSON 导入格式 */
export const DEMO_IMPORT_CONTENT = JSON.stringify(
  {
    schema: 'openfactory.knowledge.v1',
    version: 1,
    repositories: [
      {
        fullName: 'ollama/ollama',
        url: 'https://github.com/ollama/ollama',
        description: '本地运行大语言模型',
        language: 'Go',
        stars: 120000,
        category: 'AI/LLM',
        tags: ['本地模型', '推理'],
      },
      {
        fullName: 'shadcn-ui/ui',
        url: 'https://github.com/shadcn-ui/ui',
        description: '可复制粘贴的 React 组件集合',
        language: 'TypeScript',
        stars: 80000,
        category: '前端',
        tags: ['React', '组件库'],
      },
      {
        fullName: 'openai/openai-python',
        url: 'https://github.com/openai/openai-python',
        description: 'OpenAI 官方 Python SDK',
        language: 'Python',
        stars: 24000,
        category: 'AI/LLM',
        tags: ['SDK'],
      },
    ],
  },
  null,
  2
)
