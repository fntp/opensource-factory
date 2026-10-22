import { apiFetch } from '@/lib/api'

/** 分类（parentId / sortOrder 在分类树接口上线后返回，旧接口可为空） */
export interface Category {
  id: string
  name: string
  parentId?: string | null
  description: string | null
  sortOrder?: number
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

/** 分类 + 标签 */
export function fetchCategories(): Promise<CategoriesPayload> {
  return apiFetch<CategoriesPayload>('/api/categories')
}
