export type ExportFormat = 'markdown' | 'json' | 'obsidian'
export type ExportGroupBy = 'category' | 'none'

export interface ExportSummary {
  totalRepos: number
  withSummary: number
  categoryCount: number
  tagCount: number
  totalStars: number
  generatedAt: string
}

export interface ExportRequest {
  format: ExportFormat
  includeSummary: boolean
  groupBy: ExportGroupBy
}

export interface DemoExportFile {
  fileName: string
  contentType: string
  body: string | Uint8Array
}

export interface KnowledgeExportRepo {
  id: string
  fullName: string
  platform: string
  description: string | null
  summary: string | null
  language: string | null
  stars: number
  forks: number
  categoryId: string | null
  category: string | null
  tags: string[]
  url: string
  createdAt: string | null
  updatedAt: string | null
}

export interface KnowledgeExportData {
  schema: 'openfactory.knowledge.v1'
  version: 1
  generatedAt: string
  generator: { name: string; url: string }
  user: { login: string; name: string | null }
  stats: {
    totalRepos: number
    withSummary: number
    categories: number
    tags: number
    totalStars: number
  }
  categories: Array<{ id: string | null; name: string; parentId: null; repoCount: number }>
  tags: Array<{ name: string; count: number }>
  repositories: KnowledgeExportRepo[]
}
