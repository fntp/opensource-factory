/**
 * 分类树纯逻辑：建树、后代判定、移动计划。
 *
 * 不依赖 D1 / Hono，路由与单测共用；所有遍历均为迭代实现，
 * 以支撑「无限级」分类而不受调用栈深度限制。
 */

export interface CategoryLike {
  id: string;
  name: string;
  parentId: string | null;
  sortOrder: number | null;
}

export type CategoryTreeNode<T extends CategoryLike> = T & {
  children: CategoryTreeNode<T>[];
};

export type CategoryTreeErrorCode =
  | 'category_not_found'
  | 'invalid_parent'
  | 'category_cycle'
  | 'invalid_before';

/** 分类树操作错误：路由层按 code 映射 HTTP 状态码 */
export class CategoryTreeError extends Error {
  code: CategoryTreeErrorCode;

  constructor(code: CategoryTreeErrorCode, message?: string) {
    super(message ?? code);
    this.name = 'CategoryTreeError';
    this.code = code;
  }
}

/** 同级排序：sort_order 升序，其次名称（按 UTF-16 码点，稳定且不依赖 ICU） */
export function compareCategories(a: CategoryLike, b: CategoryLike): number {
  const orderDiff = (a.sortOrder ?? 0) - (b.sortOrder ?? 0);
  if (orderDiff !== 0) return orderDiff;
  if (a.name < b.name) return -1;
  if (a.name > b.name) return 1;
  return 0;
}

/** 返回排序后的副本 */
export function sortCategories<T extends CategoryLike>(rows: T[]): T[] {
  return [...rows].sort(compareCategories);
}

function sortTree<T extends CategoryLike>(nodes: CategoryTreeNode<T>[]): CategoryTreeNode<T>[] {
  nodes.sort(compareCategories);
  for (const node of nodes) sortTree(node.children);
  return nodes;
}

/**
 * 把扁平分类行组装为树。
 *
 * - 父级不存在（孤儿）或指向自身的行按根节点处理；
 * - 若数据中存在父链环，环上的节点会被提升为根节点，避免整棵树丢节点。
 */
export function buildCategoryTree<T extends CategoryLike>(rows: T[]): CategoryTreeNode<T>[] {
  const nodes = new Map<string, CategoryTreeNode<T>>();
  for (const row of rows) {
    nodes.set(row.id, { ...row, children: [] });
  }

  const roots: CategoryTreeNode<T>[] = [];
  for (const node of sortCategories([...nodes.values()])) {
    const parent = node.parentId ? nodes.get(node.parentId) : undefined;
    if (parent && parent.id !== node.id) {
      parent.children.push(node);
    } else {
      roots.push(node);
    }
  }

  // 兜底：从根出发不可达的节点（父链成环）提升为根
  const reachable = new Set<string>();
  const stack = [...roots];
  while (stack.length > 0) {
    const node = stack.pop() as CategoryTreeNode<T>;
    if (reachable.has(node.id)) continue;
    reachable.add(node.id);
    stack.push(...node.children);
  }
  for (const node of nodes.values()) {
    if (reachable.has(node.id)) continue;
    const parent = node.parentId ? nodes.get(node.parentId) : undefined;
    if (parent) {
      parent.children = parent.children.filter((child) => child.id !== node.id);
    }
    roots.push(node);
  }

  return sortTree(roots);
}

/** 收集某分类的全部后代 id（不含自身；环数据下也不会死循环） */
export function collectDescendantIds(rows: CategoryLike[], id: string): Set<string> {
  const childrenByParent = new Map<string, string[]>();
  for (const row of rows) {
    if (!row.parentId) continue;
    const list = childrenByParent.get(row.parentId) ?? [];
    list.push(row.id);
    childrenByParent.set(row.parentId, list);
  }

  const result = new Set<string>();
  const stack = [...(childrenByParent.get(id) ?? [])];
  while (stack.length > 0) {
    const current = stack.pop() as string;
    if (result.has(current)) continue;
    result.add(current);
    stack.push(...(childrenByParent.get(current) ?? []));
  }
  return result;
}

/** 目标父级是否合法：存在、不是自身、也不是自身后代 */
export function assertValidParent(
  rows: CategoryLike[],
  id: string,
  parentId: string | null
): void {
  if (parentId === null) return;
  if (parentId === id) {
    throw new CategoryTreeError('category_cycle', '分类不能作为自己的父级');
  }
  if (!rows.some((row) => row.id === parentId)) {
    throw new CategoryTreeError('invalid_parent', '父分类不存在');
  }
  if (collectDescendantIds(rows, id).has(parentId)) {
    throw new CategoryTreeError('category_cycle', '分类不能移动到自己的后代之下');
  }
}

export interface CategoryMovePlan {
  /** 移动后的父级 */
  parentId: string | null;
  /** 目标父级下最终的兄弟顺序（含被移动项） */
  targetOrder: string[];
  /** 移动前的父级 */
  sourceParentId: string | null;
  /** 原父级下剩余兄弟顺序（不含被移动项） */
  sourceOrder: string[];
}

/**
 * 计算移动计划：把 `id` 移到 `parentId` 下，并插到 `beforeId` 之前（null = 末尾）。
 *
 * 只做纯计算，不写库；调用方按 targetOrder / sourceOrder 归一化 sort_order。
 */
export function planCategoryMove(
  rows: CategoryLike[],
  id: string,
  parentId: string | null,
  beforeId: string | null = null
): CategoryMovePlan {
  const moving = rows.find((row) => row.id === id);
  if (!moving) throw new CategoryTreeError('category_not_found', '分类不存在');

  assertValidParent(rows, id, parentId);

  const targetSiblings = sortCategories(
    rows.filter((row) => row.parentId === parentId && row.id !== id)
  );
  if (beforeId !== null) {
    const before = targetSiblings.find((row) => row.id === beforeId);
    if (!before) {
      throw new CategoryTreeError('invalid_before', '目标位置不在目标父级下');
    }
  }

  const insertAt =
    beforeId === null
      ? targetSiblings.length
      : targetSiblings.findIndex((row) => row.id === beforeId);
  const targetOrder = [
    ...targetSiblings.slice(0, insertAt).map((row) => row.id),
    id,
    ...targetSiblings.slice(insertAt).map((row) => row.id),
  ];

  const sourceParentId = moving.parentId;
  const sourceOrder = sortCategories(
    rows.filter((row) => row.parentId === sourceParentId && row.id !== id)
  ).map((row) => row.id);

  return { parentId, targetOrder, sourceParentId, sourceOrder };
}
