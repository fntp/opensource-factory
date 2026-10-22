import { describe, expect, it } from 'vitest'
import type { Category } from './api'
import {
  applyCategoryMove,
  buildCategoryTree,
  collectDescendantIds,
  getParentOptions,
  getReorderTarget,
  getSiblingPosition,
} from './tree'

function category(
  id: string,
  parentId: string | null = null,
  sortOrder = 0,
  name = id
): Category {
  return { id, name, parentId, sortOrder, description: null, count: 0 }
}

describe('buildCategoryTree', () => {
  it('按 sortOrder 与名称排序并支持无限层级', () => {
    const tree = buildCategoryTree([
      category('b', null, 1, 'B'),
      category('a', null, 0, 'A'),
      category('a2', 'a', 1, 'A2'),
      category('a1', 'a', 0, 'A1'),
      category('g', 'a1', 0, 'G'),
      category('gg', 'g', 0, 'GG'),
    ])

    expect(tree.map((node) => node.id)).toEqual(['a', 'b'])
    expect(tree[0].children.map((node) => node.id)).toEqual(['a1', 'a2'])
    expect(tree[0].children[0].children[0].id).toBe('g')
    expect(tree[0].children[0].children[0].children[0].id).toBe('gg')
  })

  it('父级缺失的孤儿节点按根节点处理', () => {
    expect(buildCategoryTree([category('x', 'missing')]).map((node) => node.id)).toEqual(['x'])
  })

  it('父链成环时不丢节点', () => {
    const tree = buildCategoryTree([category('a', 'b'), category('b', 'a', 1)])
    expect(tree.map((node) => node.id).sort()).toEqual(['a', 'b'])
  })
})

describe('collectDescendantIds', () => {
  it('收集全部层级后代且不含自身', () => {
    const categories = [
      category('root'),
      category('child', 'root'),
      category('grand', 'child'),
      category('other', 'root'),
      category('unrelated'),
    ]
    expect([...collectDescendantIds(categories, 'root')].sort()).toEqual([
      'child',
      'grand',
      'other',
    ])
    expect(collectDescendantIds(categories, 'grand').size).toBe(0)
  })
})

describe('getParentOptions', () => {
  it('编辑时排除自身与自身后代，并保留层级深度', () => {
    const categories = [
      category('root'),
      category('child', 'root'),
      category('grand', 'child'),
      category('sibling', null, 1),
    ]
    const options = getParentOptions(categories, 'child')
    expect(options.map((option) => option.id)).toEqual(['root', 'sibling'])
    expect(options[0].depth).toBe(0)
  })

  it('新建时不排除任何节点', () => {
    const categories = [category('root'), category('child', 'root')]
    expect(getParentOptions(categories).map((option) => option.id)).toEqual(['root', 'child'])
    expect(getParentOptions(categories)[1].depth).toBe(1)
  })
})

describe('getReorderTarget', () => {
  const categories = [category('a', null, 0), category('b', null, 1), category('c', null, 2)]

  it('上移返回前一个兄弟作为插入点', () => {
    expect(getReorderTarget(categories, 'b', 'up')).toEqual({ parentId: null, beforeId: 'a' })
  })

  it('下移指向下下个兄弟，末尾时为 null', () => {
    expect(getReorderTarget(categories, 'a', 'down')).toEqual({ parentId: null, beforeId: 'c' })
    expect(getReorderTarget(categories, 'b', 'down')).toEqual({ parentId: null, beforeId: null })
  })

  it('边界返回 null', () => {
    expect(getReorderTarget(categories, 'a', 'up')).toBeNull()
    expect(getReorderTarget(categories, 'c', 'down')).toBeNull()
  })

  it('同级位置用于禁用按钮', () => {
    expect(getSiblingPosition(categories, 'a')).toEqual({ index: 0, total: 3 })
    expect(getSiblingPosition(categories, 'c')).toEqual({ index: 2, total: 3 })
  })
})

describe('applyCategoryMove', () => {
  it('同级移动后重新编号', () => {
    const categories = [category('a', null, 0), category('b', null, 1), category('c', null, 2)]
    const next = applyCategoryMove(categories, 'a', { parentId: null, beforeId: 'c' })
    const order = [...next].sort((x, y) => x.sortOrder - y.sortOrder).map((item) => item.id)
    expect(order).toEqual(['b', 'a', 'c'])
    expect(next.find((item) => item.id === 'a')?.sortOrder).toBe(1)
  })

  it('换父级时目标组与源组都重新编号', () => {
    const categories = [
      category('root-a'),
      category('root-b'),
      category('child-a', 'root-a'),
      category('b1', 'root-b', 0),
      category('b2', 'root-b', 1),
    ]
    const next = applyCategoryMove(categories, 'child-a', { parentId: 'root-b', beforeId: 'b1' })
    const bGroup = next
      .filter((item) => item.parentId === 'root-b')
      .sort((x, y) => x.sortOrder - y.sortOrder)
      .map((item) => item.id)
    expect(bGroup).toEqual(['child-a', 'b1', 'b2'])
    expect(next.find((item) => item.id === 'child-a')?.sortOrder).toBe(0)
  })
})
