/** 外部收藏导入（M9-03 / REQ-202610-0980）类型定义 */

export type ImportFormat = 'auto' | 'json' | 'csv' | 'html'
export type DetectedFormat = Exclude<ImportFormat, 'auto'>
export type ImportStatus = 'new' | 'update' | 'conflict'

export interface ImportRequest {
  content: string
  format: ImportFormat
  useFolders: boolean
  createCategories: boolean
}

export interface ImportSampleItem {
  fullName: string
  platform: 'github' | 'gitee'
  url: string
  description: string | null
  language: string | null
  stars: number
  category: string | null
  tags: string[]
  status: ImportStatus
}

export interface ImportIssue {
  row: number
  reason: string
  value: string
}

export interface ImportPreview {
  format: DetectedFormat
  total: number
  new: number
  update: number
  conflict: number
  invalid: number
  duplicates: number
  truncated: boolean
  sample: ImportSampleItem[]
  issues: ImportIssue[]
}

export interface ImportResult {
  runId: string
  format: DetectedFormat
  total: number
  imported: number
  updated: number
  skipped: number
  conflicts: number
  invalid: number
  duplicates: number
  categoriesCreated: number
  tagsCreated: number
  tagsLinked: number
  truncated: boolean
}

export interface ImportRun {
  id: string
  format: DetectedFormat
  status: 'completed' | 'failed'
  total: number
  imported: number
  updated: number
  skipped: number
  conflicts: number
  invalid: number
  categoriesCreated: number
  tagsCreated: number
  createdAt: string
}

export interface ImportHistoryResponse {
  items: ImportRun[]
}
