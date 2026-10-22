# 实施计划 · REQ-202610-0901 分类树 CRUD（无限级、排序、移动）

> 对应需求：REQ-202610-0901（backlog M1-09 / IT-0008）｜ 分支：`feat/req-202610-0901-category-tree`｜ 日期：2026-10-22｜ 状态：已完成

## 1. 目标

把「分类树」从只读骨架补成可用的 CRUD 闭环：

1. **无限级**：`categories.parent_id` 自关联，新增 / 编辑可指定任意层级父分类，服务端阻止环；
2. **排序**：同级按 `sort_order` 升序，支持上移 / 下移，写入时归一化为 0..n-1；
3. **移动**：支持「换父级 + 指定插入位置」的一次性移动，父子层级与排序同步维护；
4. **CRUD**：列表（含仓库计数）、新建、编辑（名称 / 描述 / 父级）、删除（含子分类或仍被仓库引用时拒绝）；
5. **前端**：分类页由只读列表升级为可展开的分类树，提供新建 / 编辑 / 删除 / 上移 / 下移 / 新建子分类；
6. **演示模式**：无后端时所有操作在本地演示数据上生效，保持项目「无后端必须可用」的约定。

## 2. 现状与约束

- `categories` 表已有 `id / name / parent_id / description / sort_order`，无需改表结构，仅补索引；
- `GET /api/categories` 目前只返回扁平列表（id / name / count / description），前端也只读展示；
- 分类为全局数据（无 `user_id`），读接口保持公开；写接口要求登录会话；
- 依赖 M1-02（D1 迁移）尚未在云端落地，本地可用 `wrangler --local` 验证；
- 资源红线：前端构建 / 测试一律通过 `bacs-heavy` 排队执行，不并行重活。

## 3. 方案

### 3.1 数据与索引

新增迁移 `edge/migrations/0002_category_tree_index.sql`：

```sql
CREATE INDEX IF NOT EXISTS idx_categories_parent_sort
    ON categories (parent_id, sort_order, name);
```

同步更新 `docs/assets/d1-schema.sql`（索引区）。

### 3.2 edge API（`edge/src/routes/categories.ts`）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/categories` | 分类扁平列表（新增 `parentId` / `sortOrder`）+ 标签计数 |
| POST | `/api/categories` | 新建；`{ name, parentId?, description?, sortOrder? }` |
| PATCH | `/api/categories/:id` | 编辑名称 / 描述 / 父级 / 排序；换父级时做环检测 |
| DELETE | `/api/categories/:id` | 删除；有子分类（409 `category_has_children`）或被仓库引用（409 `category_in_use`）时拒绝 |
| POST | `/api/categories/:id/move` | 移动：`{ parentId, beforeId? }`，用于换父级与同级重排 |

规则：

- 名称去空格后 1–100 字符，同一父级下不允许重名（409 `category_name_exists`）；
- 父级必须存在（400 `invalid_parent`），且不能是自身或自身后代（409 `category_cycle`）；
- 新建未给 `sortOrder` 时追加到同级末尾；显式位置时其余同级顺延；
- `move` 以「目标父级 + 插到哪个兄弟之前」表达，服务端重排目标组并归一化原组；
- 纯逻辑抽到 `edge/src/categories/tree.ts`（建树 / 环检测 / 移动计划），供路由与测试复用。

### 3.3 admin 分类页

- `features/categories/tree.ts`：建树（按 `sortOrder`、`name` 排序）、扁平化、后代集合、可移动目标、上移 / 下移目标计算；
- `features/categories/api.ts`：`Category` 增加 `parentId` / `sortOrder`，新增 `createCategory` / `updateCategory` / `deleteCategory` / `moveCategory`，演示数据改为三层树；
- `features/categories/index.tsx`：分类树（展开 / 收起、缩进、计数）、行内操作菜单（新建子分类 / 编辑 / 上移 / 下移 / 删除）、新建 / 编辑对话框、删除确认；
- 演示模式（`DEMO_MODE`）下操作只改本地状态并提示，不发请求。

### 3.4 测试

- `admin/src/features/categories/tree.test.ts`：建树顺序、孤儿节点、后代集合、移动目标、上移 / 下移边界；
- `edge/scripts/categories-tree.test.mjs`：用 `node --test` 覆盖 edge 纯逻辑（建树、环检测、移动计划），`npm run test:scripts` 一键执行；
- 常规检查：`admin` lint / build / test，`edge` typecheck。

## 4. 文件清单

| 文件 | 说明 |
| --- | --- |
| `edge/src/categories/tree.ts` | 分类树纯逻辑（建树 / 环检测 / 移动计划） |
| `edge/src/routes/categories.ts` | 分类 CRUD + 移动接口 |
| `edge/src/types.ts` | 分类 DTO 契约 |
| `edge/migrations/0002_category_tree_index.sql` | 分类树索引 |
| `edge/scripts/categories-tree.test.mjs` | edge 纯逻辑单测 |
| `edge/package.json` | `test:scripts` 脚本 |
| `admin/src/features/categories/tree.ts` | 前端建树 / 移动工具 |
| `admin/src/features/categories/tree.test.ts` | 前端工具单测 |
| `admin/src/features/categories/api.ts` | 分类接口与演示数据 |
| `admin/src/features/categories/index.tsx` | 分类树页面 |
| `admin/src/features/categories/category-dialog.tsx` | 新建 / 编辑对话框 |
| `admin/src/lib/api.ts` | `ApiHttpError` 附带后端错误码（用于删除冲突提示） |
| `docs/architecture/overview.md` | 接口边界表补充分类写接口 |
| `docs/architecture/data-model.md` | 分类树字段说明与索引 |
| `docs/requirements/backlog.md` / `docs/planning/task-planning.md` | 状态同步 |
| `docs/planning/plan-req-202610-0901-category-tree.md` | 本计划 |

## 5. 验收标准

1. 新建顶级 / 子分类后，`GET /api/categories` 返回的 `parentId`、`sortOrder` 正确；
2. 将父分类移动到自己的后代之下返回 409，数据不变；
3. 同级上移 / 下移后顺序稳定，`sort_order` 归一化；
4. 含子分类或仍被仓库引用的分类删除被拒绝，空分类可删除；
5. 前端分类页可展开三层以上树、完成新建 / 编辑 / 删除 / 移动，演示模式无后端也可操作；
6. `admin` lint / build / test 全绿，`edge` typecheck 与 `test:scripts` 全绿。

## 6. 风险与人工事项

- 分类为全局数据，当前无用户隔离；若后续需要「每人一棵分类树」，需加 `user_id` 并迁移，属独立需求；
- 删除策略选择「有子分类 / 被引用即拒绝」，不做级联删除，避免误删资产关联；
- 真实 D1 迁移需 M1-02 的 Cloudflare 凭据，本需求只保证本地迁移与代码就绪。

## 7. 执行结果（2026-10-22）

- **edge**
  - `npm run typecheck` → 通过；
  - `npm run test:scripts` → 9/9 通过（树构建 / 孤儿 / 环 / 后代 / 重排 / 换父级 / 非法 before）；
  - `npm run test:categories` → 13/13 通过（wrangler dev + 本地 D1 真实 HTTP：CRUD、移动、环检测、删除保护、401）。
- **admin**
  - `npm run lint` → 通过；
  - `npm run build` → 通过；
  - `npm run test` → 11 个测试文件 / 85 个用例通过（含分类树逻辑 10 例）。
- **文档**：`overview.md` 接口表、`data-model.md` 分类表与索引、`backlog.md` / `task-planning.md` 状态、`open-questions.md` Q10 已同步。
