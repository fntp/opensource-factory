/**
 * 分类树纯逻辑单测（node --test）
 * 运行：cd edge && npm run test:scripts
 */
import assert from 'node:assert/strict';
import test from 'node:test';
import {
  buildCategoryTree,
  CategoryTreeError,
  collectDescendantIds,
  planCategoryMove,
} from '../src/categories/tree.ts';

/** 构造分类行 */
function row(id, parentId = null, sortOrder = 0, name = id) {
  return { id, name, parentId, sortOrder };
}

test('buildCategoryTree：按 sortOrder / name 排序并支持无限层级', () => {
  const rows = [
    row('root-b', null, 1, 'B'),
    row('root-a', null, 0, 'A'),
    row('child-a2', 'root-a', 1, 'A2'),
    row('child-a1', 'root-a', 0, 'A1'),
    row('grand-a1', 'child-a1', 0, 'Grand'),
    row('great', 'grand-a1', 0, 'Great'),
  ];

  const tree = buildCategoryTree(rows);
  assert.deepEqual(
    tree.map((node) => node.id),
    ['root-a', 'root-b']
  );
  assert.deepEqual(
    tree[0].children.map((node) => node.id),
    ['child-a1', 'child-a2']
  );
  assert.equal(tree[0].children[0].children[0].id, 'grand-a1');
  assert.equal(tree[0].children[0].children[0].children[0].id, 'great');
});

test('buildCategoryTree：孤儿节点按根节点处理', () => {
  const tree = buildCategoryTree([row('orphan', 'missing', 0)]);
  assert.deepEqual(
    tree.map((node) => node.id),
    ['orphan']
  );
});

test('buildCategoryTree：父链成环时提升为根，不丢节点', () => {
  const tree = buildCategoryTree([row('a', 'b', 0), row('b', 'a', 1)]);
  assert.equal(tree.length, 2);
  assert.deepEqual(
    tree.map((node) => node.id).sort(),
    ['a', 'b']
  );
});

test('collectDescendantIds：收集多层后代且不含自身', () => {
  const rows = [
    row('root'),
    row('child', 'root'),
    row('grand', 'child'),
    row('other', 'root'),
    row('unrelated'),
  ];
  assert.deepEqual([...collectDescendantIds(rows, 'root')].sort(), ['child', 'grand', 'other']);
  assert.equal(collectDescendantIds(rows, 'grand').size, 0);
});

test('planCategoryMove：同级上移 / 下移', () => {
  const rows = [row('a', null, 0), row('b', null, 1), row('c', null, 2)];

  const down = planCategoryMove(rows, 'a', null, 'c');
  assert.deepEqual(down.targetOrder, ['b', 'a', 'c']);
  assert.equal(down.sourceParentId, null);
  assert.deepEqual(down.sourceOrder, ['b', 'c']);

  const up = planCategoryMove(rows, 'c', null, 'a');
  assert.deepEqual(up.targetOrder, ['c', 'a', 'b']);
});

test('planCategoryMove：换父级时追加到目标组末尾', () => {
  const rows = [
    row('root-a'),
    row('root-b'),
    row('child-a', 'root-a'),
    row('child-b1', 'root-b', 0),
    row('child-b2', 'root-b', 1),
  ];

  const plan = planCategoryMove(rows, 'child-a', 'root-b');
  assert.equal(plan.parentId, 'root-b');
  assert.deepEqual(plan.targetOrder, ['child-b1', 'child-b2', 'child-a']);
  assert.deepEqual(plan.sourceOrder, []);
});

test('planCategoryMove：移动到自己的后代之下被拒绝', () => {
  const rows = [row('root'), row('child', 'root'), row('grand', 'child')];
  assert.throws(
    () => planCategoryMove(rows, 'root', 'grand'),
    (err) => err instanceof CategoryTreeError && err.code === 'category_cycle'
  );
});

test('planCategoryMove：目标位置不在目标父级下被拒绝', () => {
  const rows = [row('a'), row('b'), row('c', 'a')];
  assert.throws(
    () => planCategoryMove(rows, 'b', null, 'c'),
    (err) => err instanceof CategoryTreeError && err.code === 'invalid_before'
  );
});

test('planCategoryMove：分类不存在被拒绝', () => {
  assert.throws(
    () => planCategoryMove([], 'missing', null),
    (err) => err instanceof CategoryTreeError && err.code === 'category_not_found'
  );
});
