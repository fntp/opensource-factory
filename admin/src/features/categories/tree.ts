import type { Category, CategoryMoveInput } from './api'

export type CategoryNode = Category & { children: CategoryNode[] }

export interface FlatCategoryNode {
  node: CategoryNode
  depth: number
}

export interface ParentOption {
  id: string
  name: string
  depth: number
}

export type MoveDirection = 'up' | 'down'

/** 同级排序：sortOrder 升序，其次名称 */
export function compareCategories(a: Category, b: Category): number {
  const orderDiff = a.sortOrder - b.sortOrder
  if (orderDiff !== 0) return orderDiff
  if (a.name < b.name) return -1
  if (a.name > b.name) return 1
  return 0
}

function sortTree(nodes: CategoryNode[]): CategoryNode[] {
  nodes.sort(compareCategories)
  for (const node of nodes) sortTree(node.children)
  return nodes
}

/**
 * 扁平分类 → 树。
 *
 * - 父级不存在的孤儿节点按根处理；
 * - 数据异常出现父链环时，环上节点提升为根，避免丢节点。
 */
export function buildCategoryTree(categories: Category[]): CategoryNode[] {
  const nodes = new Map<string, CategoryNode>()
  for (const category of categories) {
    nodes.set(category.id, { ...category, children: [] })
  }

  const roots: CategoryNode[] = []
  for (const node of [...nodes.values()].sort(compareCategories)) {
    const parent = node.parentId ? nodes.get(node.parentId) : undefined
    if (parent && parent.id !== node.id) {
      parent.children.push(node)
    } else {
      roots.push(node)
    }
  }

  const reachable = new Set<string>()
  const stack = [...roots]
  while (stack.length > 0) {
    const node = stack.pop() as CategoryNode
    if (reachable.has(node.id)) continue
    reachable.add(node.id)
    stack.push(...node.children)
  }
  for (const node of nodes.values()) {
    if (reachable.has(node.id)) continue
    const parent = node.parentId ? nodes.get(node.parentId) : undefined
    if (parent) {
      parent.children = parent.children.filter((child) => child.id !== node.id)
    }
    roots.push(node)
  }

  return sortTree(roots)
}

/** 深度优先扁平化（含全部层级） */
export function flattenCategoryTree(nodes: CategoryNode[]): FlatCategoryNode[] {
  const result: FlatCategoryNode[] = []
  const stack = nodes
    .slice()
    .reverse()
    .map((node) => ({ node, depth: 0 }))
  while (stack.length > 0) {
    const current = stack.pop() as FlatCategoryNode
    result.push(current)
    for (let i = current.node.children.length - 1; i >= 0; i -= 1) {
      stack.push({ node: current.node.children[i], depth: current.depth + 1 })
    }
  }
  return result
}

/** 只保留「所有祖先都展开」的节点，用于折叠态渲染 */
export function flattenVisibleTree(
  nodes: CategoryNode[],
  isCollapsed: (id: string) => boolean
): FlatCategoryNode[] {
  const result: FlatCategoryNode[] = []
  const stack = nodes
    .slice()
    .reverse()
    .map((node) => ({ node, depth: 0 }))
  while (stack.length > 0) {
    const current = stack.pop() as FlatCategoryNode
    result.push(current)
    if (isCollapsed(current.node.id)) continue
    for (let i = current.node.children.length - 1; i >= 0; i -= 1) {
      stack.push({ node: current.node.children[i], depth: current.depth + 1 })
    }
  }
  return result
}

/** 某分类的全部后代 id（不含自身） */
export function collectDescendantIds(categories: Category[], id: string): Set<string> {
  const childrenByParent = new Map<string, string[]>()
  for (const category of categories) {
    if (!category.parentId) continue
    const list = childrenByParent.get(category.parentId) ?? []
    list.push(category.id)
    childrenByParent.set(category.parentId, list)
  }

  const result = new Set<string>()
  const stack = [...(childrenByParent.get(id) ?? [])]
  while (stack.length > 0) {
    const current = stack.pop() as string
    if (result.has(current)) continue
    result.add(current)
    stack.push(...(childrenByParent.get(current) ?? []))
  }
  return result
}

/** 父级下拉选项：排除自身与自身后代，避免形成环 */
export function getParentOptions(categories: Category[], excludeId?: string): ParentOption[] {
  const excluded = new Set<string>()
  if (excludeId) {
    excluded.add(excludeId)
    for (const id of collectDescendantIds(categories, excludeId)) excluded.add(id)
  }
  return flattenCategoryTree(buildCategoryTree(categories))
    .filter(({ node }) => !excluded.has(node.id))
    .map(({ node, depth }) => ({ id: node.id, name: node.name, depth }))
}

/** 同级位置（用于禁用首项上移 / 末项下移） */
export function getSiblingPosition(
  categories: Category[],
  id: string
): { index: number; total: number } {
  const current = categories.find((category) => category.id === id)
  if (!current) return { index: -1, total: 0 }
  const siblings = categories
    .filter((category) => category.parentId === current.parentId)
    .sort(compareCategories)
  return { index: siblings.findIndex((category) => category.id === id), total: siblings.length }
}

/**
 * 计算上移 / 下移的移动参数；已在边界时返回 null。
 *
 * API 语义是「插到 beforeId 之前」，因此下移要指向「下下个」兄弟。
 */
export function getReorderTarget(
  categories: Category[],
  id: string,
  direction: MoveDirection
): CategoryMoveInput | null {
  const current = categories.find((category) => category.id === id)
  if (!current) return null
  const siblings = categories
    .filter((category) => category.parentId === current.parentId)
    .sort(compareCategories)
  const index = siblings.findIndex((category) => category.id === id)

  if (direction === 'up') {
    if (index <= 0) return null
    return { parentId: current.parentId, beforeId: siblings[index - 1].id }
  }

  if (index < 0 || index >= siblings.length - 1) return null
  const afterNext = siblings[index + 2]
  return { parentId: current.parentId, beforeId: afterNext ? afterNext.id : null }
}

/**
 * 在本地演示数据上应用一次移动（与 edge 的 move 语义一致）：
 * 目标组与（换父级时的）原组都会重新编号为 0..n-1。
 */
export function applyCategoryMove(
  categories: Category[],
  id: string,
  input: CategoryMoveInput
): Category[] {
  const moving = categories.find((category) => category.id === id)
  if (!moving) return categories

  const parentId = input.parentId
  const targetSiblings = categories
    .filter((category) => category.parentId === parentId && category.id !== id)
    .sort(compareCategories)
  const beforeId = input.beforeId ?? null
  const beforeIndex =
    beforeId === null ? -1 : targetSiblings.findIndex((category) => category.id === beforeId)
  const insertAt = beforeIndex === -1 ? targetSiblings.length : beforeIndex

  const targetOrder = [
    ...targetSiblings.slice(0, insertAt).map((category) => category.id),
    id,
    ...targetSiblings.slice(insertAt).map((category) => category.id),
  ]

  const nextSortOrder = new Map<string, number>()
  targetOrder.forEach((categoryId, index) => nextSortOrder.set(categoryId, index))

  if (moving.parentId !== parentId) {
    const sourceSiblings = categories
      .filter((category) => category.parentId === moving.parentId && category.id !== id)
      .sort(compareCategories)
    sourceSiblings.forEach((category, index) => nextSortOrder.set(category.id, index))
  }

  return categories.map((category) => {
    if (category.id === id) {
      return {
        ...category,
        parentId,
        sortOrder: nextSortOrder.get(id) ?? 0,
      }
    }
    const sortOrder = nextSortOrder.get(category.id)
    return sortOrder === undefined ? category : { ...category, sortOrder }
  })
}
