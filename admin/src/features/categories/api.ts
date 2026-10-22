import { fetchWithFallback } from '@/lib/api'

export interface Category {
  id: string
  name: string
  count: number
  description: string
}

export interface Tag {
  name: string
  count: number
}

export interface CategoriesPayload {
  categories: Category[]
  tags: Tag[]
}

export const MOCK_CATEGORIES: Category[] = [
  { id: '1', name: 'AI/LLM', count: 42, description: '大模型、推理框架与 AI 应用' },
  { id: '2', name: '前端开发', count: 21, description: '框架、组件库与构建工具' },
  { id: '3', name: '后端与 API', count: 18, description: 'Web 框架、网关与服务端工具' },
  { id: '4', name: '开发工具', count: 15, description: '编辑器、CLI 与效率工具' },
  { id: '5', name: '桌面端', count: 8, description: '跨平台桌面应用与运行时' },
  { id: '6', name: '数据库', count: 7, description: '数据库、缓存与存储引擎' },
  { id: '7', name: 'DevOps', count: 6, description: 'CI/CD、容器与可观测性' },
  { id: '8', name: '数据工程', count: 5, description: '数据管道、调度与 ETL' },
  { id: '9', name: '学习资源', count: 6, description: '教程、课程与示例仓库' },
]

export const MOCK_TAGS: Tag[] = [
  { name: 'LLM', count: 18 },
  { name: 'Python', count: 16 },
  { name: 'TypeScript', count: 14 },
  { name: '框架', count: 12 },
  { name: '组件', count: 9 },
  { name: 'Rust', count: 7 },
  { name: 'Go', count: 7 },
  { name: '工具', count: 6 },
  { name: '设计', count: 5 },
  { name: '跨平台', count: 4 },
  { name: '推荐', count: 3 },
  { name: '资产', count: 2 },
]

export function fetchCategories(): Promise<CategoriesPayload> {
  return fetchWithFallback<CategoriesPayload>('/api/categories', {
    categories: MOCK_CATEGORIES,
    tags: MOCK_TAGS,
  })
}
