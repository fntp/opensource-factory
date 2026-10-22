import { ApiHttpError, apiFetch, fetchWithFallback } from '@/lib/api'

export interface Category {
  id: string
  name: string
  parentId: string | null
  description: string | null
  sortOrder: number
  count: number
}

export interface Tag {
  name: string
  count: number
}

export interface CategoriesPayload {
  categories: Category[]
  tags: Tag[]
}

/** 新建 / 编辑分类的请求体 */
export interface CategoryInput {
  name: string
  parentId: string | null
  description: string | null
  sortOrder?: number
}

/** 移动分类：换到 parentId 下，并插到 beforeId 之前（null = 末尾） */
export interface CategoryMoveInput {
  parentId: string | null
  beforeId?: string | null
}

/** 演示数据：三层分类树 */
export const MOCK_CATEGORIES: Category[] = [
  { id: '1', name: 'AI/LLM', parentId: null, description: '大模型、推理框架与 AI 应用', sortOrder: 0, count: 42 },
  { id: '11', name: '大模型', parentId: '1', description: '模型与推理服务', sortOrder: 0, count: 18 },
  { id: '111', name: '推理框架', parentId: '11', description: 'vLLM / llama.cpp / Ollama', sortOrder: 0, count: 7 },
  { id: '12', name: 'AI 应用', parentId: '1', description: 'Agent、RAG 与工作流', sortOrder: 1, count: 9 },
  { id: '2', name: '前端开发', parentId: null, description: '框架、组件库与构建工具', sortOrder: 1, count: 21 },
  { id: '21', name: '框架', parentId: '2', description: 'React / Vue / Svelte', sortOrder: 0, count: 8 },
  { id: '3', name: '后端与 API', parentId: null, description: 'Web 框架、网关与服务端工具', sortOrder: 2, count: 18 },
  { id: '4', name: '开发工具', parentId: null, description: '编辑器、CLI 与效率工具', sortOrder: 3, count: 15 },
  { id: '5', name: '桌面端', parentId: null, description: '跨平台桌面应用与运行时', sortOrder: 4, count: 8 },
  { id: '6', name: '数据库', parentId: null, description: '数据库、缓存与存储引擎', sortOrder: 5, count: 7 },
  { id: '7', name: 'DevOps', parentId: null, description: 'CI/CD、容器与可观测性', sortOrder: 6, count: 6 },
  { id: '8', name: '数据工程', parentId: null, description: '数据管道、调度与 ETL', sortOrder: 7, count: 5 },
  { id: '9', name: '学习资源', parentId: null, description: '教程、课程与示例仓库', sortOrder: 8, count: 6 },
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

/** 把分类接口错误转成用户可读文案 */
export function categoryErrorMessage(err: unknown): string {
  if (err instanceof ApiHttpError) {
    switch (err.code) {
      case 'category_name_exists':
        return '同一父级下已存在同名分类'
      case 'category_cycle':
        return '不能把分类移动到自己的子分类下'
      case 'invalid_parent':
        return '父分类不存在或已被删除'
      case 'category_has_children':
        return '该分类下还有子分类，请先删除或移动子分类'
      case 'category_in_use':
        return '该分类仍被仓库引用，请先调整仓库分类'
      case 'unauthorized':
        return '登录已过期，请重新登录'
      default:
        return `操作失败（${err.status}）`
    }
  }
  return err instanceof Error ? err.message : '操作失败，请稍后重试'
}

/** 分类 + 标签（失败时回退演示数据） */
export function fetchCategories(): Promise<CategoriesPayload> {
  return fetchWithFallback<CategoriesPayload>('/api/categories', {
    categories: MOCK_CATEGORIES,
    tags: MOCK_TAGS,
  })
}

/** 新建分类 */
export function createCategory(input: CategoryInput): Promise<Category> {
  return apiFetch<Category>('/api/categories', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  })
}

/** 编辑分类（名称 / 描述 / 父级 / 排序） */
export function updateCategory(
  id: string,
  input: Partial<CategoryInput>
): Promise<Category> {
  return apiFetch<Category>(`/api/categories/${encodeURIComponent(id)}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  })
}

/** 删除分类（服务端会拒绝仍有子分类或被仓库引用的分类） */
export function deleteCategory(id: string): Promise<void> {
  return apiFetch<void>(`/api/categories/${encodeURIComponent(id)}`, {
    method: 'DELETE',
  })
}

/** 移动分类（换父级 / 同级重排） */
export function moveCategory(
  id: string,
  input: CategoryMoveInput
): Promise<Category> {
  return apiFetch<Category>(`/api/categories/${encodeURIComponent(id)}/move`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  })
}
