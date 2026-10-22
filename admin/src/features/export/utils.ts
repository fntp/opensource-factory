import { buildStoreZip, type ZipEntry } from './zip'
import type {
  DemoExportFile,
  ExportFormat,
  ExportGroupBy,
  ExportRequest,
  KnowledgeExportData,
  KnowledgeExportRepo,
} from './types'

export const FORMAT_OPTIONS: Array<{
  key: ExportFormat
  label: string
  description: string
  extension: string
  bullets: string[]
}> = [
  {
    key: 'markdown',
    label: 'Markdown',
    description: '单文件知识库，适合 Notion、Git 仓库或任意编辑器',
    extension: '.md',
    bullets: ['按分类生成目录与条目', '保留语言 / Star / 标签', '可选 README 摘要'],
  },
  {
    key: 'json',
    label: 'JSON',
    description: '结构化数据，适合备份、脚本处理与二次分析',
    extension: '.json',
    bullets: ['openfactory.knowledge.v1', '完整仓库 / 分类 / 标签', '可直接被脚本消费'],
  },
  {
    key: 'obsidian',
    label: 'Obsidian',
    description: 'ZIP 仓库，解压后作为 Obsidian Vault 直接打开',
    extension: '.zip',
    bullets: ['仓库笔记 + YAML frontmatter', '分类索引与双链', '标签自动转为 Obsidian 标签'],
  },
]

export function formatLabel(format: ExportFormat): string {
  return FORMAT_OPTIONS.find((option) => option.key === format)?.label ?? 'Markdown'
}

export function formatCompactNumber(value: number): string {
  if (!Number.isFinite(value) || value <= 0) return '0'
  if (value >= 1000) {
    return `${(value / 1000).toFixed(1).replace(/\.0$/, '')}k`
  }
  return String(Math.round(value))
}

export function fallbackFileName(
  format: ExportFormat,
  generatedAt: string = new Date().toISOString()
): string {
  const date = generatedAt.slice(0, 10) || 'export'
  if (format === 'json') return `openfactory-knowledge-${date}.json`
  if (format === 'obsidian') return `openfactory-obsidian-vault-${date}.zip`
  return `openfactory-knowledge-${date}.md`
}

const DEMO_REPOS: KnowledgeExportRepo[] = [
  {
    id: 'langchain-ai/langchain',
    fullName: 'langchain-ai/langchain',
    platform: 'github',
    description: '构建上下文感知推理应用的开源框架',
    summary: '面向 LLM 应用开发的编排框架，覆盖链、工具、记忆与检索增强。',
    language: 'Python',
    stars: 94210,
    forks: 15230,
    categoryId: 'ai',
    category: 'AI/LLM',
    tags: ['LLM', '框架', 'RAG'],
    url: 'https://github.com/langchain-ai/langchain',
    createdAt: '2026-09-12 08:00:00',
    updatedAt: '2026-10-20T08:00:00Z',
  },
  {
    id: 'ollama/ollama',
    fullName: 'ollama/ollama',
    platform: 'github',
    description: '在本地轻松运行大语言模型',
    summary: '本地模型运行时，支持模型拉取、量化与 OpenAI 兼容接口。',
    language: 'Go',
    stars: 102340,
    forks: 8100,
    categoryId: 'ai',
    category: 'AI/LLM',
    tags: ['本地模型', '推理', 'LLM'],
    url: 'https://github.com/ollama/ollama',
    createdAt: '2026-09-15 08:00:00',
    updatedAt: '2026-10-19T08:00:00Z',
  },
  {
    id: 'fastapi/fastapi',
    fullName: 'fastapi/fastapi',
    platform: 'github',
    description: '高性能的现代 Python Web 框架',
    summary: '基于类型注解的异步 Web 框架，自带 OpenAPI 文档与依赖注入。',
    language: 'Python',
    stars: 82600,
    forks: 7100,
    categoryId: 'backend',
    category: '后端与 API',
    tags: ['API', '异步', 'Python'],
    url: 'https://github.com/fastapi/fastapi',
    createdAt: '2026-09-18 08:00:00',
    updatedAt: '2026-10-18T08:00:00Z',
  },
  {
    id: 'shadcn-ui/ui',
    fullName: 'shadcn-ui/ui',
    platform: 'github',
    description: '设计精美的组件集合，可复制到你的应用中',
    summary: '以复制粘贴方式使用的 React 组件集合，基于 Radix UI 与 Tailwind。',
    language: 'TypeScript',
    stars: 78120,
    forks: 4150,
    categoryId: 'frontend',
    category: '前端开发',
    tags: ['组件', '设计', 'React'],
    url: 'https://github.com/shadcn-ui/ui',
    createdAt: '2026-09-20 08:00:00',
    updatedAt: '2026-10-17T08:00:00Z',
  },
]

export function buildDemoKnowledgeExport(
  generatedAt: string = new Date().toISOString()
): KnowledgeExportData {
  const categoryMap = new Map<string, { id: string | null; name: string; parentId: null; repoCount: number }>()
  const tagMap = new Map<string, number>()
  for (const repo of DEMO_REPOS) {
    const categoryName = repo.category ?? '未分类'
    const category = categoryMap.get(categoryName)
    if (category) category.repoCount += 1
    else categoryMap.set(categoryName, { id: repo.categoryId, name: categoryName, parentId: null, repoCount: 1 })
    for (const tag of repo.tags) tagMap.set(tag, (tagMap.get(tag) ?? 0) + 1)
  }
  const categories = [...categoryMap.values()].sort(
    (a, b) => b.repoCount - a.repoCount || a.name.localeCompare(b.name, 'zh-Hans-CN')
  )
  const tags = [...tagMap.entries()]
    .map(([name, count]) => ({ name, count }))
    .sort((a, b) => b.count - a.count || a.name.localeCompare(b.name, 'zh-Hans-CN'))

  return {
    schema: 'openfactory.knowledge.v1',
    version: 1,
    generatedAt,
    generator: { name: 'OpenFactory', url: 'https://github.com/fntp/opensource-factory' },
    user: { login: 'demo', name: '演示用户' },
    stats: {
      totalRepos: DEMO_REPOS.length,
      withSummary: DEMO_REPOS.filter((repo) => Boolean(repo.summary)).length,
      categories: categories.length,
      tags: tags.length,
      totalStars: DEMO_REPOS.reduce((sum, repo) => sum + repo.stars, 0),
    },
    categories,
    tags,
    repositories: [...DEMO_REPOS].sort((a, b) => b.stars - a.stars),
  }
}

function escapeInline(value: string | null | undefined): string {
  if (!value) return ''
  return value
    .replace(/\s+/g, ' ')
    .replace(/([\\[\]()<>])/g, '\\$1')
    .trim()
}

function safeName(value: string, fallback = '未命名'): string {
  const cleaned = [...value]
    .map((char) => (char.charCodeAt(0) < 32 ? '-' : char))
    .join('')
    .replace(/[\\/:*?"<>|]/g, '-')
    .replace(/\s+/g, ' ')
    .replace(/^[.\s-]+|[.\s-]+$/g, '')
    .slice(0, 80)
    .trim()
  return cleaned || fallback
}

function obsidianTag(value: string, prefix: string): string {
  const cleaned = value
    .toLowerCase()
    .replace(/\s+/g, '-')
    .replace(/[#|[\],:{}()"'`]/g, '')
    .replace(/-+/g, '-')
    .replace(/^[-/]+|[-/]+$/g, '')
  return cleaned ? `${prefix}/${cleaned}` : ''
}

function yamlString(value: string): string {
  return JSON.stringify(value)
}

function groupRepos(
  data: KnowledgeExportData,
  groupBy: ExportGroupBy
): Array<{ name: string; repos: KnowledgeExportRepo[] }> {
  if (groupBy === 'none') {
    return data.repositories.length > 0 ? [{ name: '全部项目', repos: data.repositories }] : []
  }
  const groups = new Map<string, KnowledgeExportRepo[]>()
  for (const repo of data.repositories) {
    const name = repo.category?.trim() || '未分类'
    const list = groups.get(name)
    if (list) list.push(repo)
    else groups.set(name, [repo])
  }
  return [...groups.entries()]
    .map(([name, repos]) => ({ name, repos }))
    .sort((a, b) => {
      if (a.name === '未分类') return 1
      if (b.name === '未分类') return -1
      return b.repos.length - a.repos.length || a.name.localeCompare(b.name, 'zh-Hans-CN')
    })
}

export function buildDemoMarkdown(data: KnowledgeExportData, request: ExportRequest): string {
  const groups = groupRepos(data, request.groupBy)
  const lines: string[] = [
    '---',
    `title: ${yamlString('我的开源知识库（演示）')}`,
    `generatedAt: ${yamlString(data.generatedAt)}`,
    `repoCount: ${data.stats.totalRepos}`,
    '---',
    '',
    '# 我的开源知识库（演示）',
    '',
    `> 共 ${data.stats.totalRepos} 个项目 · ${data.stats.categories} 个分类 · ${data.stats.tags} 个标签`,
    '',
  ]
  if (groups.length === 0) {
    lines.push('_当前账号还没有收藏任何项目。_', '')
    return lines.join('\n')
  }
  lines.push('## 目录', '')
  for (const group of groups) lines.push(`- ${group.name}（${group.repos.length}）`)
  lines.push('')
  for (const group of groups) {
    lines.push(`## ${group.name}`, '')
    for (const repo of group.repos) {
      lines.push(`### [${escapeInline(repo.fullName)}](${repo.url})`, '')
      const meta = [repo.language, `⭐ ${formatCompactNumber(repo.stars)}`].filter(Boolean)
      if (repo.tags.length > 0) meta.push(`标签：${repo.tags.map((tag) => `\`${tag}\``).join(' ')}`)
      lines.push(`> ${meta.join(' · ')}`, '')
      if (repo.description) lines.push(escapeInline(repo.description), '')
      if (request.includeSummary && repo.summary) lines.push(`**摘要**：${escapeInline(repo.summary)}`, '')
    }
  }
  return lines.join('\n')
}

export function buildDemoObsidianEntries(
  data: KnowledgeExportData,
  request: ExportRequest
): ZipEntry[] {
  const groups = groupRepos(data, request.groupBy)
  const entries: ZipEntry[] = []
  const readme: string[] = [
    '---',
    `title: ${yamlString('OpenFactory 知识库（演示）')}`,
    'tags:',
    '  - "openfactory"',
    '---',
    '',
    '# OpenFactory 知识库（演示）',
    '',
    `> 共 ${data.stats.totalRepos} 个项目 · ${data.stats.categories} 个分类`,
    '',
    '## 分类',
    '',
  ]
  for (const group of groups) {
    readme.push(`- [[20-分类/${safeName(group.name)}|${group.name}]]（${group.repos.length}）`)
  }
  readme.push('')
  entries.push({ name: 'README.md', content: readme.join('\n') })

  for (const group of groups) {
    const note: string[] = [
      '---',
      `title: ${yamlString(group.name)}`,
      'tags:',
      '  - "openfactory"',
      `  - ${yamlString(obsidianTag(group.name, 'cat'))}`,
      '---',
      '',
      `# ${group.name}`,
      '',
    ]
    for (const repo of group.repos) {
      const noteName = safeName(repo.fullName.replace('/', '--'), 'repo')
      const path = request.groupBy === 'none' ? `10-项目/${noteName}` : `10-项目/${safeName(group.name)}/${noteName}`
      note.push(`- [[${path}|${repo.fullName}]]`)
    }
    note.push('')
    entries.push({ name: `20-分类/${safeName(group.name)}.md`, content: note.join('\n') })
  }

  for (const repo of data.repositories) {
    const noteName = safeName(repo.fullName.replace('/', '--'), 'repo')
    const path =
      request.groupBy === 'none'
        ? `10-项目/${noteName}.md`
        : `10-项目/${safeName(repo.category ?? '未分类')}/${noteName}.md`
    const tags = ['openfactory']
    if (repo.language) tags.push(obsidianTag(repo.language, 'lang'))
    for (const tag of repo.tags) tags.push(obsidianTag(tag, 'tag'))
    if (repo.category) tags.push(obsidianTag(repo.category, 'cat'))
    const note: string[] = [
      '---',
      `title: ${yamlString(repo.fullName)}`,
      'tags:',
      ...[...new Set(tags.filter(Boolean))].map((tag) => `  - ${yamlString(tag)}`),
      `category: ${yamlString(repo.category ?? '未分类')}`,
      `language: ${yamlString(repo.language ?? '')}`,
      `stars: ${repo.stars}`,
      `url: ${yamlString(repo.url)}`,
      '---',
      '',
      `# ${repo.fullName}`,
      '',
    ]
    if (repo.description) note.push(repo.description, '')
    if (request.includeSummary && repo.summary) note.push('## 摘要', '', repo.summary, '')
    note.push('## 链接', '', `- [GitHub](${repo.url})`, '')
    entries.push({ name: path, content: note.join('\n') })
  }

  return entries
}

export function buildDemoExport(
  request: ExportRequest,
  generatedAt: string = new Date().toISOString()
): DemoExportFile {
  const data = buildDemoKnowledgeExport(generatedAt)
  const fileName = fallbackFileName(request.format, generatedAt)
  if (request.format === 'json') {
    return { fileName, contentType: 'application/json; charset=utf-8', body: JSON.stringify(data, null, 2) }
  }
  if (request.format === 'obsidian') {
    return {
      fileName,
      contentType: 'application/zip',
      body: buildStoreZip(buildDemoObsidianEntries(data, request), new Date(generatedAt)),
    }
  }
  return {
    fileName,
    contentType: 'text/markdown; charset=utf-8',
    body: buildDemoMarkdown(data, request),
  }
}
