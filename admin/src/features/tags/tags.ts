import { ApiHttpError } from '@/lib/api'
import type { Tag } from './api'

export type TagSort = 'name' | 'count'
export type SortOrder = 'asc' | 'desc'

export const TAG_NAME_MAX_LENGTH = 50

/** 是否包含 ASCII 控制字符（避免使用 control-char 正则触发 lint） */
export function hasControlChars(value: string): boolean {
  for (const char of value) {
    const code = char.codePointAt(0) ?? 0
    if (code < 0x20 || code === 0x7f) return true
  }
  return false
}

/** 客户端名称归一化（与服务端规则保持一致） */
export function normalizeTagName(raw: string): string {
  return raw.replace(/\s+/g, ' ').trim()
}

/** 客户端名称校验：返回错误文案，合法返回 null */
export function validateTagName(raw: string): string | null {
  const name = normalizeTagName(raw)
  if (!name) return '标签名称不能为空'
  if ([...name].length > TAG_NAME_MAX_LENGTH) {
    return `标签名称不能超过 ${TAG_NAME_MAX_LENGTH} 个字符`
  }
  if (name.includes(',') || hasControlChars(name)) {
    return '标签名称不能包含逗号或控制字符'
  }
  return null
}

/** 关键词过滤（大小写不敏感） */
export function filterTags(tags: Tag[], keyword: string): Tag[] {
  const q = keyword.trim().toLowerCase()
  if (!q) return tags
  return tags.filter((tag) => tag.name.toLowerCase().includes(q))
}

/** 名称比较：小写后按码点排序，保证不同浏览器 / 语言环境结果一致 */
function compareName(a: string, b: string): number {
  const left = a.toLowerCase()
  const right = b.toLowerCase()
  if (left < right) return -1
  if (left > right) return 1
  return 0
}

/** 排序：名称按码点比较，引用数相同时按名称兜底 */
export function sortTags(tags: Tag[], sort: TagSort, order: SortOrder): Tag[] {
  const direction = order === 'asc' ? 1 : -1
  return [...tags].sort((a, b) => {
    if (sort === 'count') {
      const byCount = (a.count - b.count) * direction
      if (byCount !== 0) return byCount
      return compareName(a.name, b.name)
    }
    return compareName(a.name, b.name) * direction
  })
}

export interface TagSummary {
  total: number
  used: number
  references: number
}

/** 页面统计：标签总数 / 已引用标签数 / 引用关联总数 */
export function summarizeTags(tags: Tag[]): TagSummary {
  return {
    total: tags.length,
    used: tags.filter((tag) => tag.count > 0).length,
    references: tags.reduce((sum, tag) => sum + Math.max(0, tag.count), 0),
  }
}

/** 把接口错误转成用户可读文案 */
export function tagErrorMessage(err: unknown): string {
  if (err instanceof ApiHttpError) {
    switch (err.code) {
      case 'tag_name_exists':
        return '已存在同名标签，可改用「合并」把两个标签合并为一个'
      case 'tag_name_required':
        return '标签名称不能为空'
      case 'tag_name_too_long':
        return `标签名称不能超过 ${TAG_NAME_MAX_LENGTH} 个字符`
      case 'tag_name_invalid_chars':
        return '标签名称不能包含逗号或控制字符'
      case 'tag_not_found':
        return '标签不存在或已被删除'
      case 'invalid_merge_target':
        return '不能把标签合并到自身'
      case 'unauthorized':
        return '登录已过期，请重新登录'
      default:
        return `操作失败（${err.status}）`
    }
  }
  return err instanceof Error ? err.message : '操作失败，请稍后重试'
}
